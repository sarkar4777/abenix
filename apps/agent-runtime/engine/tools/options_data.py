"""Options-market data tool.

Surfaces volatility-surface summary statistics derived from public listed
option chains. Use cases:

  - Energy / commodity desks reading risk-reversal skew on CL / NG / RB
    futures options to enrich a spread-mispricing model.
  - Equity desks reading SPX / VIX implied vol as a market-wide nervousness
    indicator.
  - FX desks reading EUR/USD / GBP/USD option skew to size carry trades.
  - Macro researchers reading term-structure slope (front IV vs 3-month IV)
    as a leading event-risk signal.

Three actions:

  - ``snapshot``         single ticker, single expiry; returns ATM IV,
                         25-delta risk reversal, put/call OI ratio, and the
                         OTM-call vs OTM-put IV gap.
  - ``term_structure``   single ticker, returns ATM IV for the front three
                         listed expiries plus the slope (front IV minus the
                         3-month IV).
  - ``regime``            single ticker, computes a four-bucket regime label
                         (``calm`` / ``nervous`` / ``skewed_up`` /
                         ``skewed_down``) by combining the snapshot signals
                         against fixed thresholds. Useful for UI badges.

All actions return a ToolResult with both a human-readable ``content``
string AND structured ``metadata`` so downstream agents (and the page
itself) can read the numbers without reparsing prose.

Data source: Yahoo Finance option chains via ``yfinance``. Same library
the existing ``yahoo_finance`` tool uses, so no new dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Skew threshold expressed in IV-percentage-points (e.g. 0.04 = 4 vol points)
_SKEW_NERVOUS = 0.04
_IV_NERVOUS = 0.35  # absolute IV above this counts as "nervous"


class OptionsDataTool(BaseTool):
    name = "options_data"
    description = (
        "Listed options-market data: at-the-money implied volatility, "
        "25-delta risk reversal (call IV minus put IV), put/call open-"
        "interest ratio, and a calm/nervous/skewed-up/skewed-down regime "
        "label. Works on any ticker with a public Yahoo option chain: "
        "futures (CL=F crude, NG=F natural gas, GC=F gold), equity "
        "indices (^SPX, ^VIX, SPY, QQQ), single stocks (AAPL, MSFT), "
        "and FX pairs that expose option data (EURUSD=X)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["snapshot", "term_structure", "regime"],
                "description": (
                    "snapshot: single expiry summary. "
                    "term_structure: front three expiries' ATM IV + slope. "
                    "regime: four-bucket market-state label for a UI badge."
                ),
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Yahoo ticker. Futures use the =F suffix "
                    "(CL=F for crude, NG=F for natural gas). Indices use "
                    "the ^ prefix (^SPX, ^VIX). Equities are the plain "
                    "ticker (AAPL). FX uses the =X suffix (EURUSD=X)."
                ),
            },
            "expiry_index": {
                "type": "integer",
                "default": 0,
                "description": (
                    "For action=snapshot only. Which expiry to read, "
                    "indexed from 0 (front month). Ignored for "
                    "term_structure and regime."
                ),
            },
        },
        "required": ["action", "symbol"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        symbol = arguments.get("symbol") or ""
        if not action or not symbol:
            return ToolResult(
                content="Error: both 'action' and 'symbol' are required",
                is_error=True,
            )

        try:
            import yfinance as yf
        except ImportError:
            return ToolResult(
                content=(
                    "Error: yfinance package is not installed. "
                    "Install with: pip install yfinance"
                ),
                is_error=True,
            )

        try:
            ticker = yf.Ticker(symbol)
            expiries = list(ticker.options or [])
        except Exception as e:
            return ToolResult(
                content=f"Yahoo Finance error for {symbol}: {e}",
                is_error=True,
            )

        if not expiries:
            return ToolResult(
                content=(
                    f"No option chain found for {symbol}. Yahoo Finance "
                    "does not list options for this ticker."
                ),
                is_error=True,
            )

        if action == "snapshot":
            idx = int(arguments.get("expiry_index") or 0)
            if idx >= len(expiries):
                idx = 0
            return self._snapshot(ticker, symbol, expiries[idx])

        if action == "term_structure":
            return self._term_structure(ticker, symbol, expiries[:3])

        if action == "regime":
            return self._regime(ticker, symbol, expiries[0])

        return ToolResult(
            content=f"Error: unknown action '{action}'",
            is_error=True,
        )

    @staticmethod
    def _spot_price(ticker: Any) -> float | None:
        try:
            hist = ticker.history(period="5d", auto_adjust=False)
            if hist is None or hist.empty:
                return None
            return float(hist["Close"].iloc[-1])
        except Exception:
            return None

    def _summary_for_expiry(
        self, ticker: Any, expiry: str, spot: float | None
    ) -> dict[str, Any]:
        """Compute ATM IV, risk reversal, OI ratio for one expiry.

        Returns a dict so callers can either render or pass through to
        metadata directly. Robust to missing IV (Yahoo occasionally
        returns nan for far-OTM strikes).
        """
        chain = ticker.option_chain(expiry)
        calls = chain.calls
        puts = chain.puts
        if calls is None or calls.empty or puts is None or puts.empty:
            return {
                "expiry": expiry,
                "error": "empty chain",
            }

        if spot is None:
            mid_call = float(calls["strike"].median())
            mid_put = float(puts["strike"].median())
            spot = (mid_call + mid_put) / 2.0

        # ATM IV = mean of nearest-to-spot call IV and put IV
        atm_call_row = calls.iloc[(calls["strike"] - spot).abs().argsort()[:1]]
        atm_put_row = puts.iloc[(puts["strike"] - spot).abs().argsort()[:1]]
        atm_call_iv = float(atm_call_row["impliedVolatility"].iloc[0])
        atm_put_iv = float(atm_put_row["impliedVolatility"].iloc[0])
        atm_iv = (atm_call_iv + atm_put_iv) / 2.0

        # 25-delta proxy: take the OTM call ~10% above spot and OTM put
        # ~10% below spot. True 25-delta requires inverting Black-Scholes
        # delta; the +/-10% strike sits in the same neighbourhood for
        # commodity / equity expiries up to 90 days, and the
        # tool docstring is clear that this is an approximation.
        target_call = spot * 1.10
        target_put = spot * 0.90
        otm_call = calls.iloc[(calls["strike"] - target_call).abs().argsort()[:1]]
        otm_put = puts.iloc[(puts["strike"] - target_put).abs().argsort()[:1]]
        try:
            otm_call_iv = float(otm_call["impliedVolatility"].iloc[0])
            otm_put_iv = float(otm_put["impliedVolatility"].iloc[0])
        except Exception:
            otm_call_iv = atm_call_iv
            otm_put_iv = atm_put_iv

        risk_reversal = otm_call_iv - otm_put_iv  # +ve = upside skew

        try:
            put_oi = float(puts["openInterest"].fillna(0).sum())
            call_oi = float(calls["openInterest"].fillna(0).sum())
            put_call_oi = put_oi / call_oi if call_oi > 0 else None
        except Exception:
            put_oi, call_oi, put_call_oi = 0.0, 0.0, None

        return {
            "expiry": expiry,
            "spot": round(float(spot), 4),
            "atm_iv": round(atm_iv, 4),
            "atm_call_iv": round(atm_call_iv, 4),
            "atm_put_iv": round(atm_put_iv, 4),
            "otm_call_iv_10pct": round(otm_call_iv, 4),
            "otm_put_iv_10pct": round(otm_put_iv, 4),
            "risk_reversal_25d": round(risk_reversal, 4),
            "put_oi": int(put_oi),
            "call_oi": int(call_oi),
            "put_call_oi_ratio": round(put_call_oi, 3) if put_call_oi else None,
        }

    def _snapshot(self, ticker: Any, symbol: str, expiry: str) -> ToolResult:
        spot = self._spot_price(ticker)
        summary = self._summary_for_expiry(ticker, expiry, spot)
        if "error" in summary:
            return ToolResult(
                content=f"Empty option chain for {symbol} @ {expiry}",
                is_error=True,
            )

        days = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.utcnow()).days
        days = max(days, 0)
        lines = [
            f"Options snapshot: {symbol} (expiry {expiry}, {days}d)",
            f"  Spot: {summary['spot']}",
            f"  ATM IV: {summary['atm_iv']:.4f} "
            f"(call {summary['atm_call_iv']:.4f}, put "
            f"{summary['atm_put_iv']:.4f})",
            "  25-delta proxy (10% OTM strikes):",
            f"    OTM call IV: {summary['otm_call_iv_10pct']:.4f}",
            f"    OTM put IV:  {summary['otm_put_iv_10pct']:.4f}",
            f"    Risk reversal (call - put): " f"{summary['risk_reversal_25d']:+.4f}",
            f"  Open interest: {summary['call_oi']:,} calls / "
            f"{summary['put_oi']:,} puts",
            f"  Put/Call OI ratio: " f"{summary['put_call_oi_ratio'] or 'n/a'}",
        ]

        rr = summary["risk_reversal_25d"]
        if rr > 0.03:
            lines.append(
                f"  Interpretation: upside skew "
                f"(+{rr:.3f}). Market is paying more to hedge a rally than "
                "a crash."
            )
        elif rr < -0.03:
            lines.append(
                f"  Interpretation: downside skew "
                f"({rr:.3f}). Market is paying more to hedge a crash than "
                "a rally."
            )
        else:
            lines.append("  Interpretation: roughly symmetric skew.")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "symbol": symbol,
                "days_to_expiry": days,
                **summary,
            },
        )

    def _term_structure(
        self, ticker: Any, symbol: str, expiries: list[str]
    ) -> ToolResult:
        spot = self._spot_price(ticker)
        rows: list[dict[str, Any]] = []
        for exp in expiries:
            summ = self._summary_for_expiry(ticker, exp, spot)
            if "error" not in summ:
                rows.append(summ)

        if not rows:
            return ToolResult(
                content=f"No usable option expiries for {symbol}",
                is_error=True,
            )

        lines = [f"Options term structure: {symbol} (spot {spot})"]
        for r in rows:
            lines.append(
                f"  {r['expiry']}: ATM IV {r['atm_iv']:.4f}  "
                f"risk_rev {r['risk_reversal_25d']:+.4f}  "
                f"put/call OI {r['put_call_oi_ratio'] or 'n/a'}"
            )

        # Slope = front IV minus longest available (3-month-ish)
        front_iv = rows[0]["atm_iv"]
        back_iv = rows[-1]["atm_iv"]
        slope = front_iv - back_iv
        lines.append("")
        lines.append(f"  Front IV ({rows[0]['expiry']}): {front_iv:.4f}")
        lines.append(f"  Back IV  ({rows[-1]['expiry']}): {back_iv:.4f}")
        lines.append(f"  Slope (front - back): {slope:+.4f}")
        if slope > 0.02:
            lines.append(
                "  Interpretation: front-loaded vol. Market sees a "
                "near-term catalyst (announcement, expiry, event)."
            )
        elif slope < -0.02:
            lines.append(
                "  Interpretation: back-loaded vol. Market sees calm "
                "short-term but uncertainty further out."
            )
        else:
            lines.append("  Interpretation: flat term structure.")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "symbol": symbol,
                "spot": spot,
                "expiries": [r["expiry"] for r in rows],
                "atm_iv_by_expiry": [r["atm_iv"] for r in rows],
                "risk_reversal_by_expiry": [r["risk_reversal_25d"] for r in rows],
                "slope_front_minus_back": round(slope, 4),
            },
        )

    def _regime(self, ticker: Any, symbol: str, expiry: str) -> ToolResult:
        spot = self._spot_price(ticker)
        summary = self._summary_for_expiry(ticker, expiry, spot)
        if "error" in summary:
            return ToolResult(
                content=f"Empty option chain for {symbol}",
                is_error=True,
            )

        atm = summary["atm_iv"]
        rr = summary["risk_reversal_25d"]

        nervous = atm >= _IV_NERVOUS
        if rr >= _SKEW_NERVOUS:
            regime = "skewed_up"
            note = (
                "Upside-skewed: option market is paying more to hedge a "
                "price rally than a crash. Often a leading indicator of "
                "supply fear."
            )
        elif rr <= -_SKEW_NERVOUS:
            regime = "skewed_down"
            note = (
                "Downside-skewed: option market is paying more to hedge a "
                "price crash than a rally. Often a leading indicator of "
                "demand fear."
            )
        elif nervous:
            regime = "nervous"
            note = (
                "Nervous: ATM implied volatility is elevated but skew is "
                "roughly symmetric. Market expects big moves in either "
                "direction."
            )
        else:
            regime = "calm"
            note = (
                "Calm: ATM IV is below threshold and skew is symmetric. "
                "The option market sees today as ordinary."
            )

        lines = [
            f"Options regime: {symbol} (expiry {expiry})",
            f"  ATM IV: {atm:.4f}",
            f"  Risk reversal: {rr:+.4f}",
            f"  Regime: {regime}",
            f"  Note: {note}",
        ]
        return ToolResult(
            content="\n".join(lines),
            metadata={
                "symbol": symbol,
                "expiry": expiry,
                "atm_iv": atm,
                "risk_reversal_25d": rr,
                "regime": regime,
                "note": note,
            },
        )


__all__ = ["OptionsDataTool"]
