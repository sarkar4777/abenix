"""refined_products_forwards — refined-product futures curves + crack spreads.

The trader checklist demanded "refined product market price and forward
curve data" for gasoline, gasoil/diesel and jet. EIA only publishes
weekly spot; the forward curve lives in NYMEX/ICE futures, which Yahoo
Finance mirrors for free as continuous front-month contracts:

  RB=F   RBOB gasoline ($/gal, NYMEX)
  HO=F   ULSD heating oil ($/gal, NYMEX) — proxy for diesel/gasoil
  CL=F   WTI crude ($/bbl, NYMEX) — for crack spreads
  BZ=F   Brent crude ($/bbl, ICE)
  NG=F   Henry Hub natural gas ($/MMBtu, NYMEX)

The tool exposes three actions:

  curve         Pull the front N continuous futures (Yahoo only exposes
                front-month for most symbols; we expose what's there and
                interpolate flatten-to-front for downstream code).
  crack_spread  3-2-1 (3 bbl crude -> 2 bbl gasoline + 1 bbl distillate)
                computed in $/bbl, or 1-1 single-product crack.
  history       N days of daily settles for a single symbol.

Outputs include both human-readable text and structured metadata so the
mispricing model can consume the numbers without reparsing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Industry-standard $/gal -> $/bbl factor (42 gallons per barrel).
_BBL_PER_GAL = 42.0

_PRODUCT_SYMBOL: dict[str, str] = {
    "rbob": "RB=F",
    "gasoline": "RB=F",
    "heating_oil": "HO=F",
    "ulsd": "HO=F",
    "diesel": "HO=F",
    "gasoil": "HO=F",
    "wti": "CL=F",
    "crude_wti": "CL=F",
    "brent": "BZ=F",
    "crude_brent": "BZ=F",
    "natural_gas": "NG=F",
    "hh_natgas": "NG=F",
    "propane": "PG=F",
    "naphtha": "RB=F",  # no listed Yahoo naphtha future; use RBOB as a proxy
}

# Symbols quoted in $/gal vs $/bbl vs $/MMBtu.
_GAL_QUOTED = {"RB=F", "HO=F", "PG=F"}
_BBL_QUOTED = {"CL=F", "BZ=F"}
_MMBTU_QUOTED = {"NG=F"}


class RefinedProductsForwardsTool(BaseTool):
    name = "refined_products_forwards"
    description = (
        "Refined-products forward curves and crack spreads. Pulls "
        "continuous-front futures from Yahoo (RB=F gasoline, HO=F "
        "ULSD/heating oil, CL=F WTI, BZ=F Brent, NG=F Henry Hub) and "
        "computes the standard 3-2-1 crack spread or a 1-1 single-"
        "product crack. Three actions: curve (front-month settle for a "
        "product), crack_spread (3-2-1 or product-vs-crude in $/bbl), "
        "history (N days of daily settles). Real, citable Yahoo Finance "
        "values; no API key required."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["curve", "crack_spread", "history"],
            },
            "product": {
                "type": "string",
                "description": (
                    "rbob/gasoline, heating_oil/ulsd/diesel/gasoil, "
                    "wti/crude_wti, brent/crude_brent, natural_gas, "
                    "propane, naphtha"
                ),
            },
            "crack_type": {
                "type": "string",
                "enum": [
                    "3-2-1",
                    "gasoline-vs-wti",
                    "diesel-vs-wti",
                    "gasoline-vs-brent",
                    "diesel-vs-brent",
                ],
                "default": "3-2-1",
            },
            "lookback_days": {
                "type": "integer",
                "default": 30,
                "minimum": 5,
                "maximum": 365,
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        try:
            import yfinance as yf  # noqa: F401
        except ImportError:
            return ToolResult(
                content="Error: yfinance is not installed",
                is_error=True,
            )
        if action == "curve":
            return self._curve(arguments.get("product") or "rbob")
        if action == "crack_spread":
            return self._crack_spread(
                arguments.get("crack_type") or "3-2-1",
                int(arguments.get("lookback_days") or 30),
            )
        if action == "history":
            return self._history(
                arguments.get("product") or "rbob",
                int(arguments.get("lookback_days") or 30),
            )
        return ToolResult(content=f"Unknown action '{action}'", is_error=True)

    @staticmethod
    def _to_usd_per_bbl(symbol: str, price: float) -> float:
        if symbol in _GAL_QUOTED:
            return price * _BBL_PER_GAL
        return price

    def _fetch_last(self, symbol: str) -> tuple[float | None, str | None]:
        import yfinance as yf

        try:
            t = yf.Ticker(symbol)
            hist = t.history(period="5d", auto_adjust=False)
            if hist is None or hist.empty:
                return None, None
            last_row = hist.iloc[-1]
            return float(last_row["Close"]), str(hist.index[-1].date())
        except Exception:
            return None, None

    def _fetch_history(self, symbol: str, days: int) -> list[tuple[str, float]]:
        import yfinance as yf

        try:
            t = yf.Ticker(symbol)
            period = f"{max(days, 5)}d"
            hist = t.history(period=period, auto_adjust=False)
            if hist is None or hist.empty:
                return []
            rows: list[tuple[str, float]] = []
            for ts, row in hist.iterrows():
                try:
                    rows.append((str(ts.date()), float(row["Close"])))
                except Exception:
                    continue
            return rows
        except Exception:
            return []

    def _curve(self, product: str) -> ToolResult:
        sym = _PRODUCT_SYMBOL.get(product.lower())
        if not sym:
            return ToolResult(
                content=f"Unknown product '{product}'. "
                f"Supported: {', '.join(sorted(set(_PRODUCT_SYMBOL.keys())))}",
                is_error=True,
            )
        price, date_ = self._fetch_last(sym)
        if price is None:
            return ToolResult(content=f"No Yahoo data for {sym}", is_error=True)
        price_bbl = self._to_usd_per_bbl(sym, price)
        unit = (
            "$/gal"
            if sym in _GAL_QUOTED
            else "$/MMBtu" if sym in _MMBTU_QUOTED else "$/bbl"
        )
        return ToolResult(
            content=(
                f"{product} front-month future ({sym}): {price:.4f} {unit} "
                f"as of {date_}\n"
                f"  In $/bbl-equivalent: {price_bbl:.2f}"
            ),
            metadata={
                "product": product.lower(),
                "symbol": sym,
                "front_settle": round(price, 6),
                "front_settle_usd_per_bbl": round(price_bbl, 4),
                "unit": unit,
                "as_of": date_,
                "source": "https://finance.yahoo.com",
            },
        )

    def _crack_spread(self, crack: str, lookback_days: int) -> ToolResult:
        # Pull the necessary spot pieces
        wti, wti_date = self._fetch_last("CL=F")
        brent, brent_date = self._fetch_last("BZ=F")
        gasoline, _ = self._fetch_last("RB=F")
        diesel, _ = self._fetch_last("HO=F")

        if None in (wti, gasoline, diesel):
            return ToolResult(
                content="Crack spread inputs missing — Yahoo returned nothing for one leg",
                is_error=True,
            )

        gasoline_bbl = self._to_usd_per_bbl("RB=F", gasoline)
        diesel_bbl = self._to_usd_per_bbl("HO=F", diesel)
        meta: dict[str, Any] = {
            "wti_usd_bbl": round(wti, 4),
            "brent_usd_bbl": round(brent, 4) if brent else None,
            "gasoline_usd_bbl": round(gasoline_bbl, 4),
            "diesel_usd_bbl": round(diesel_bbl, 4),
            "as_of": wti_date,
        }

        c = crack.lower()
        if c == "3-2-1":
            # 3-2-1 crack = ((2 * gasoline + 1 * diesel) - 3 * wti) / 3
            spread = ((2.0 * gasoline_bbl) + diesel_bbl - (3.0 * wti)) / 3.0
            meta["crack_type"] = "3-2-1"
            meta["spread_usd_bbl"] = round(spread, 4)
            return ToolResult(
                content=(
                    f"3-2-1 crack spread (Gulf Coast proxy): ${spread:.2f}/bbl\n"
                    f"  WTI: ${wti:.2f}/bbl  Gasoline: ${gasoline_bbl:.2f}/bbl  Diesel: ${diesel_bbl:.2f}/bbl"
                ),
                metadata=meta,
            )
        if c == "gasoline-vs-wti":
            spread = gasoline_bbl - wti
            meta["crack_type"] = c
            meta["spread_usd_bbl"] = round(spread, 4)
            return ToolResult(
                content=f"Gasoline-WTI crack: ${spread:.2f}/bbl",
                metadata=meta,
            )
        if c == "diesel-vs-wti":
            spread = diesel_bbl - wti
            meta["crack_type"] = c
            meta["spread_usd_bbl"] = round(spread, 4)
            return ToolResult(
                content=f"Diesel-WTI crack: ${spread:.2f}/bbl",
                metadata=meta,
            )
        if c == "gasoline-vs-brent":
            if brent is None:
                return ToolResult(content="Brent missing", is_error=True)
            spread = gasoline_bbl - brent
            meta["crack_type"] = c
            meta["spread_usd_bbl"] = round(spread, 4)
            return ToolResult(
                content=f"Gasoline-Brent crack: ${spread:.2f}/bbl",
                metadata=meta,
            )
        if c == "diesel-vs-brent":
            if brent is None:
                return ToolResult(content="Brent missing", is_error=True)
            spread = diesel_bbl - brent
            meta["crack_type"] = c
            meta["spread_usd_bbl"] = round(spread, 4)
            return ToolResult(
                content=f"Diesel-Brent crack: ${spread:.2f}/bbl",
                metadata=meta,
            )

        return ToolResult(content=f"Unknown crack type '{crack}'", is_error=True)

    def _history(self, product: str, days: int) -> ToolResult:
        sym = _PRODUCT_SYMBOL.get(product.lower())
        if not sym:
            return ToolResult(content=f"Unknown product '{product}'", is_error=True)
        rows = self._fetch_history(sym, days)
        if not rows:
            return ToolResult(content=f"No history for {sym}", is_error=True)

        values = [v for _, v in rows]
        avg = sum(values) / len(values)
        first = values[0]
        last = values[-1]
        change_pct = ((last - first) / first) * 100 if first else 0.0
        lines = [f"{product} ({sym}) — last {len(rows)} settles:"]
        for d, v in rows[-10:]:
            lines.append(f"  {d}: {v:.4f}")
        lines.append("")
        lines.append(
            f"  Period mean: {avg:.4f}  ·  Range: {min(values):.4f} -> {max(values):.4f}  "
            f"·  Change: {change_pct:+.2f}%"
        )
        return ToolResult(
            content="\n".join(lines),
            metadata={
                "product": product.lower(),
                "symbol": sym,
                "data_points": len(rows),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "mean": round(avg, 4),
                "change_pct": round(change_pct, 4),
                "latest": round(last, 4),
                "as_of": rows[-1][0],
                "source": "https://finance.yahoo.com",
            },
        )


__all__ = ["RefinedProductsForwardsTool"]
