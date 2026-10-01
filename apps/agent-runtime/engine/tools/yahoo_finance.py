from __future__ import annotations

import asyncio
import datetime as _dt
import json as _json
import logging
import os
import time
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, ToolResult

logger = logging.getLogger(__name__)

# Concurrent forward runs for the same commodity were racing on the spot
# fetch — two coroutines would each hit yfinance, one would land on a stale
# back-month or wrong-ticker fixture, and the saved spot_anchor would flip
# (Brent: 80 -> 126 USD/bbl, ~56% spread). The original in-process lock +
# TTL cache fixed single-pod racing but the runtime runs as 4 KEDA pools
# so concurrent callers landing on different pods still each fetched their
# own value (94% spread observed: 65/78.8/80.59/126.1/126.1). The fix is
# a Redis-backed cache + SETNX leader election so exactly one pod fetches
# for a given (symbol, period, region, as_of_date) key and every other
# waiter reads the leader's result. In-process cache is kept as L1 for
# the common single-pod many-shot case.
_SPOT_TTL_SECS = 60.0
_SPOT_LOCK_TTL_SECS = 30  # leader holds the SETNX key while it fetches
_SPOT_WAIT_MAX_SECS = 25.0  # how long a follower waits for the leader
_SPOT_WAIT_POLL_SECS = 0.25
_SPOT_CACHE: dict[tuple, tuple[Any, float]] = {}
_SPOT_LOCKS: dict[tuple, asyncio.Lock] = {}
_SPOT_LOCKS_LOCK = asyncio.Lock()

# Lazy redis client — same pattern as engine/knowledge/search_cache.py so
# the tool degrades cleanly (back to single-pod in-process behaviour) if
# REDIS_URL is unset or the broker is unreachable.
_redis_client: Any | None = None
_redis_unavailable = False


def _get_redis() -> Any | None:
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        return _redis_client
    except Exception as e:
        logger.warning("yahoo_finance: redis unavailable, disabling: %s", e)
        _redis_unavailable = True
        return None


def _redis_keys(cache_key: tuple) -> tuple[str, str]:
    # cache_key is (resolved_symbol, period, region, as_of). Region may be
    # None — coerce to a stable string so the redis key is deterministic.
    sym, period, region, as_of = cache_key
    suffix = f"{sym}:{period}:{region or '_'}:{as_of}"
    return (f"yfspot:v1:val:{suffix}", f"yfspot:v1:lock:{suffix}")


def _serialize_result(result: ToolResult) -> str:
    return _json.dumps(
        {
            "content": result.content,
            "is_error": result.is_error,
            "metadata": result.metadata or {},
        },
        default=str,
    )


def _deserialize_result(raw: str) -> ToolResult:
    payload = _json.loads(raw)
    return ToolResult(
        content=payload.get("content", ""),
        is_error=bool(payload.get("is_error", False)),
        metadata=payload.get("metadata") or {},
    )


async def _get_spot_lock(key: tuple) -> asyncio.Lock:
    async with _SPOT_LOCKS_LOCK:
        return _SPOT_LOCKS.setdefault(key, asyncio.Lock())


# Friendly aliases for commodities, FX, indices — keeps prompts and saved
# presets readable. Add liberally; missing aliases fall back to the literal
# Yahoo symbol passed by the caller.
COMMODITY_ALIASES: dict[str, str] = {
    # Precious metals (front-month futures)
    "gold": "GC=F",
    "silver": "SI=F",
    "platinum": "PL=F",
    "palladium": "PA=F",
    "copper": "HG=F",
    # Energy (front-month futures)
    "wti": "CL=F",
    "brent": "BZ=F",
    # Namespaced crude aliases mirror the natgas_*/power_* convention so the
    # Crude fair-value agent can carry a region tag (BRENT/WTI) on the
    # canonical tool call and the post-processor band check picks it up.
    "crude_brent": "BZ=F",  # ICE Brent front-month (global benchmark)
    "crude_wti": "CL=F",  # NYMEX WTI front-month (US benchmark)
    "natgas_henry_hub": "NG=F",
    "natgas_ttf": "TTF=F",
    # JKM (Japan-Korea Marker, Asian LNG benchmark) — Yahoo lists it as JKM=F
    # front-month. If JKM=F is empty for a tenant region, callers should fall
    # back to natgas_ttf or natgas_henry_hub as documented LNG proxies.
    "natgas_jkm": "JKM=F",
    # Power (electricity) front-month proxies. Yahoo does not consistently
    # publish day-ahead power curves — EBR=F / EPR=F / FB=F / NPF=F return
    # empty `history()` results most days because EEX/Nord Pool settles
    # aren't on the free Yahoo feed. These aliases stay registered so the
    # agent can attempt them first (and we keep a record of what was
    # tried in the tool-call audit trail), but the Power fair-value
    # agent is wired to fall back to:
    #   - entso_e (ENTSOE_API_KEY) for EU regions (DE/FR/NL/...)
    #   - eia_open_data (ERCOT_NORTH_DA / PJM_WEST_DA) for US regions
    # If both anchors come back empty, the agent flags
    # data_quality='degraded' and the CIQ router converts 200+empty into
    # HTTP 503 so the UI shows "Live feed unavailable for DE power".
    "power_de_day_ahead": "EBR=F",  # EEX German Baseload front-month (Yahoo unreliable)
    "power_de_peakload": "EPR=F",  # EEX German Peakload front-month (Yahoo unreliable)
    "power_fr_day_ahead": "FB=F",  # EEX French Baseload front-month (Yahoo unreliable)
    "power_nordpool": "NPF=F",  # Nord Pool System Price front-month (Yahoo unreliable)
    "power_ercot_north": "ERCN=F",  # ERCOT North hub front-month (rare)
    "power_pjm_west": "PJMW=F",  # PJM Western hub front-month (rare)
    # Coal swap proxies. Yahoo coverage on coal is thin — these resolve to
    # the cleanest tickers we know about per region; if Yahoo returns empty
    # the Coal fair-value agent degrades honestly (ICE clears API2/API4
    # cargoes daily but those settles aren't on a free feed).
    "coal_newcastle": "MTF=F",  # ICE Newcastle thermal coal front-month (Asia-Pac)
    "coal_api2": "API2=F",  # ICE Rotterdam (API2) front-month (Northwest Europe)
    "coal_api4": "API4=F",  # ICE Richards Bay (API4) front-month (South Africa)
    # Carbon — EU ETS EUA (European Union Allowance) front-month. Yahoo
    # does not publish a clean dedicated EUA future; KRBN is the canonical
    # free NAV proxy (KraneShares Global Carbon Strategy ETF, EUA-weighted
    # alongside CCA + RGGI), and CO2.L is the London-listed Carbon ETC
    # tracking ICE EUA. If both come back empty the agent flags
    # data_quality='degraded' (ICE EUA front-month direct is a paid feed).
    "carbon_eua": "KRBN",
    "carbon_eua_etc": "CO2.L",
    "heating_oil": "HO=F",
    "rbob_gasoline": "RB=F",
    # Namespaced refined-product aliases mirror the natgas_*/power_*/crude_*
    # convention so the Refined Products fair-value agent can carry a product
    # tag (RBOB/ULSD/JET) on the canonical tool call and the post-processor
    # band check picks it up. Jet kero has no reliable free Yahoo ticker —
    # JKER=F is the documented attempt; if it returns empty the agent must
    # flag degraded honestly rather than substitute a different fuel.
    "refined_rbob": "RB=F",  # NYMEX RBOB Gasoline front-month (USD/gal)
    "refined_ulsd": "HO=F",  # NYMEX ULSD Heating Oil front-month (USD/gal)
    "refined_jet": "JKER=F",  # Jet kero proxy (Yahoo coverage patchy; degrade if empty)
    # Agriculture
    "corn": "ZC=F",
    "wheat": "ZW=F",
    "soybean": "ZS=F",
    "coffee": "KC=F",
    "sugar": "SB=F",
    "cotton": "CT=F",
    # Metals ETFs (NAV proxy for AUM/flow)
    "etf_gld": "GLD",
    "etf_slv": "SLV",
    "etf_pplt": "PPLT",
    "etf_pall": "PALL",
    # FX
    "usdcny": "CNY=X",
    "usdjpy": "JPY=X",
    "eurusd": "EURUSD=X",
    # Equity benchmarks
    "sp500": "^GSPC",
    "vix": "^VIX",
}


class YahooFinanceTool(BaseTool):
    name = "yahoo_finance"
    config_fields = (
        ConfigField(
            "FRED_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="FRED",
            signup_url="https://fred.stlouisfed.org/docs/api/api_key.html",
        ),
    )
    description = (
        "Generic Yahoo Finance reader. One tool, every instrument: equities, "
        "indices, futures, FX, ETFs, FRED macro series. Use action="
        "'commodity_future' with a friendly alias (gold/silver/wti/brent/"
        "natgas_henry_hub/natgas_ttf/copper/corn/wheat/usdcny ...) or pass any "
        "raw Yahoo symbol. Configure per-tenant presets in /admin/tool-presets."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "stock_price",
                    "company_info",
                    "earnings",
                    "dividends",
                    "economic_indicator",
                    "market_index",
                    "commodity_future",
                    "fx_rate",
                    "list_aliases",
                ],
                "description": (
                    "stock_price/company_info/earnings/dividends for equities; "
                    "economic_indicator for FRED (needs FRED_API_KEY); "
                    "commodity_future for any commodity by alias or =F symbol; "
                    "fx_rate for FX (alias or =X symbol); "
                    "list_aliases returns the named-alias dictionary."
                ),
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Stock ticker (AAPL), FRED series (GDP, UNRATE), Yahoo "
                    "future (CL=F, GC=F, NG=F), FX (CNY=X, EURUSD=X), or "
                    "friendly alias (gold, wti, brent, natgas_henry_hub, "
                    "natgas_ttf, corn, usdcny). Run action=list_aliases to "
                    "see them all."
                ),
            },
            "period": {
                "type": "string",
                "description": (
                    "History period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max. "
                    "Default 1y for equities, 90d for commodity_future/fx_rate "
                    "(realized_vol_calc needs >=60 closes for its 60-day mean)."
                ),
            },
            "history_days": {
                "type": "integer",
                "description": (
                    "Optional shortcut for commodity_future/fx_rate: window in "
                    "days. Overrides period; floored at 60 so the realized-vol "
                    "60-day mean has data."
                ),
            },
            "region": {
                "type": "string",
                "description": (
                    "Optional region tag for commodity_future/fx_rate spot "
                    "cache isolation (e.g. EU, US, ASIA). Sharpens the cache "
                    "key when the same ticker serves multiple regions."
                ),
            },
            "as_of": {
                "type": "string",
                "description": (
                    "Optional ISO date (YYYY-MM-DD) for spot cache "
                    "partitioning. Defaults to today (UTC) so yesterday's "
                    "value never bleeds into today's run."
                ),
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        symbol = arguments.get("symbol", "")
        # Default lookback is 90 days for commodity/fx callers — the
        # realized_vol_calc downstream needs >=60 closes for the 60-day
        # mean. Equity-style actions still default to 1y.
        if action in ("commodity_future", "fx_rate"):
            period = arguments.get("period", "90d")
        else:
            period = arguments.get("period", "1y")

        if not action:
            return ToolResult(content="Error: 'action' is required", is_error=True)

        if action == "list_aliases":
            lines = ["Named aliases (alias -> yahoo symbol):"]
            for k, v in sorted(COMMODITY_ALIASES.items()):
                lines.append(f"  {k:<22} -> {v}")
            return ToolResult(
                content="\n".join(lines),
                metadata={
                    "aliases": COMMODITY_ALIASES,
                    "count": len(COMMODITY_ALIASES),
                },
            )

        # Resolve friendly alias -> raw Yahoo symbol. Pass-through if unknown.
        resolved_symbol = COMMODITY_ALIASES.get((symbol or "").lower(), symbol)
        alias_used = symbol if symbol and symbol.lower() in COMMODITY_ALIASES else None

        if action in ("commodity_future", "fx_rate"):
            history_days = arguments.get("history_days")
            if isinstance(history_days, int) and history_days > 0:
                # Floor at 60 so realized_vol_calc's 60-day mean has data.
                period = f"{max(history_days, 60)}d"
            if not resolved_symbol:
                return ToolResult(
                    content="Error: symbol or alias required", is_error=True
                )

            # Cache key uses (resolved_symbol, region, as_of_date). Region
            # and as_of are optional caller hints — when the agent passes
            # them through we get finer grained isolation; when it doesn't
            # we still key on the date so a stale cache from yesterday's
            # run never bleeds into today.
            region = (arguments.get("region") or "").upper() or None
            as_of_raw = arguments.get("as_of")
            if isinstance(as_of_raw, str) and as_of_raw:
                as_of = as_of_raw[:10]
            else:
                as_of = _dt.datetime.utcnow().date().isoformat()
            cache_key = (resolved_symbol, period, region, as_of)
            val_key, lock_key = _redis_keys(cache_key)

            def _stamp(result: ToolResult, source: str) -> ToolResult:
                # Always stamp resolved_symbol so the router/agent can
                # detect alias→symbol resolution even on cache hits where
                # the alias_used flag is local to the caller.
                result.metadata = {
                    **(result.metadata or {}),
                    "resolved_symbol": resolved_symbol,
                    "spot_cache": source,
                }
                if alias_used:
                    result.metadata["alias"] = alias_used
                return result

            now_mono = time.monotonic()
            cached = _SPOT_CACHE.get(cache_key)
            if cached and cached[1] > now_mono:
                return _stamp(cached[0], "l1_hit")

            redis = _get_redis()

            # L2: cross-pod Redis cache. If the leader on any pod has
            # already populated this key within the TTL window, every
            # other pod (and every other coroutine on the same pod)
            # reads the same canonical value.
            if redis is not None:
                try:
                    raw = await redis.get(val_key)
                    if raw:
                        result = _deserialize_result(raw)
                        _SPOT_CACHE[cache_key] = (
                            result,
                            time.monotonic() + _SPOT_TTL_SECS,
                        )
                        return _stamp(result, "l2_hit")
                except Exception as e:
                    logger.debug("yahoo_finance: redis GET failed: %s", e)

            # Per-coroutine lock still useful as L1 serialization so that
            # within one pod we don't race in the gap between SETNX and GET.
            lock = await _get_spot_lock(cache_key)
            async with lock:
                # Double-check L1 inside the lock.
                now_mono = time.monotonic()
                cached = _SPOT_CACHE.get(cache_key)
                if cached and cached[1] > now_mono:
                    return _stamp(cached[0], "l1_hit")

                leader = True
                if redis is not None:
                    try:
                        # SETNX with TTL: exactly one pod becomes the leader.
                        # nx=True returns True only if the key did not exist.
                        leader = bool(
                            await redis.set(
                                lock_key,
                                "1",
                                nx=True,
                                ex=_SPOT_LOCK_TTL_SECS,
                            )
                        )
                    except Exception as e:
                        logger.debug("yahoo_finance: redis SETNX failed: %s", e)
                        leader = True  # degrade to per-pod leader

                if not leader and redis is not None:
                    # Follower path: poll the value key until the leader
                    # writes it, or the lock TTL elapses and we fall
                    # through to our own fetch as a safety net.
                    deadline = time.monotonic() + _SPOT_WAIT_MAX_SECS
                    while time.monotonic() < deadline:
                        await asyncio.sleep(_SPOT_WAIT_POLL_SECS)
                        try:
                            raw = await redis.get(val_key)
                        except Exception:
                            raw = None
                        if raw:
                            result = _deserialize_result(raw)
                            _SPOT_CACHE[cache_key] = (
                                result,
                                time.monotonic() + _SPOT_TTL_SECS,
                            )
                            return _stamp(result, "l2_wait")
                        # Lock disappeared without a value (leader crashed
                        # mid-fetch). Promote ourselves to leader and break.
                        try:
                            still_locked = await redis.exists(lock_key)
                        except Exception:
                            still_locked = 1
                        if not still_locked:
                            try:
                                leader = bool(
                                    await redis.set(
                                        lock_key,
                                        "1",
                                        nx=True,
                                        ex=_SPOT_LOCK_TTL_SECS,
                                    )
                                )
                            except Exception:
                                leader = True
                            if leader:
                                break

                try:
                    import yfinance as yf
                except ImportError:
                    return ToolResult(content="yfinance not installed", is_error=True)
                try:
                    ticker = yf.Ticker(resolved_symbol)
                    result = self._stock_price(ticker, resolved_symbol, period)
                except Exception as e:
                    return ToolResult(
                        content=f"Yahoo error for {resolved_symbol}: {e}", is_error=True
                    )

                if not result.is_error:
                    _SPOT_CACHE[cache_key] = (
                        result,
                        time.monotonic() + _SPOT_TTL_SECS,
                    )
                    if redis is not None:
                        try:
                            await redis.set(
                                val_key,
                                _serialize_result(result),
                                ex=int(_SPOT_TTL_SECS),
                            )
                        except Exception as e:
                            logger.debug("yahoo_finance: redis SET failed: %s", e)
                # Best-effort release of the leader lock so a new fetch
                # can run immediately after TTL rather than waiting it out.
                if redis is not None:
                    try:
                        await redis.delete(lock_key)
                    except Exception:
                        pass
                return _stamp(result, "miss")

        if not symbol:
            return ToolResult(
                content="Error: 'symbol' is required for this action",
                is_error=True,
            )

        if action == "economic_indicator":
            return await self._fred_indicator(symbol, period)

        # All other actions use yfinance
        try:
            import yfinance as yf
        except ImportError:
            return ToolResult(
                content="Error: yfinance package is not installed. "
                "Install with: pip install yfinance",
                is_error=True,
            )

        try:
            ticker = yf.Ticker(symbol)

            if action == "stock_price":
                return self._stock_price(ticker, symbol, period)
            if action == "company_info":
                return self._company_info(ticker, symbol)
            if action == "earnings":
                return self._earnings(ticker, symbol)
            if action == "dividends":
                return self._dividends(ticker, symbol, period)
            if action == "market_index":
                return self._stock_price(ticker, symbol, period)

            return ToolResult(
                content=f"Error: unknown action '{action}'",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"Yahoo Finance error for {symbol}: {e}",
                is_error=True,
            )

    @staticmethod
    def _stock_price(ticker: Any, symbol: str, period: str) -> ToolResult:
        hist = ticker.history(period=period)
        if hist.empty:
            # Stamp metadata.status='empty' + an empty prices/closes array so
            # the agent and downstream guardrails can branch on the structured
            # field rather than scraping the prose. Power agents key on this
            # to invoke entso_e (EU) or eia_open_data (US) fall-backs.
            is_power = symbol.startswith(("EBR", "EPR", "FB=", "NPF", "ERCN", "PJMW"))
            reason = (
                "Yahoo does not consistently publish EU/Nordpool power "
                "front-month settles on the free feed. Fall back to "
                "entso_e (EU) or eia_open_data (US)."
                if is_power
                else "Yahoo history() returned an empty frame for this ticker."
            )
            return ToolResult(
                content=(f"No price data found for {symbol}. {reason}"),
                metadata={
                    "symbol": symbol,
                    "status": "empty",
                    "prices": [],
                    "closes": [],
                    "price_count": 0,
                    "empty_reason": reason,
                },
            )

        latest = hist.iloc[-1]
        first = hist.iloc[0]
        change = ((latest["Close"] - first["Close"]) / first["Close"]) * 100

        lines = [
            f"CANONICAL_SPOT={float(latest['Close']):.2f}  # use this exact value for spot_anchor",
            f"Stock Price: {symbol}",
            f"Period: {period}",
            f"Latest Close: ${latest['Close']:.2f}",
            f"Open: ${latest['Open']:.2f}",
            f"High: ${latest['High']:.2f}",
            f"Low: ${latest['Low']:.2f}",
            f"Volume: {int(latest['Volume']):,}",
            f"Period Change: {change:+.2f}%",
            "",
            f"Period High: ${hist['High'].max():.2f}",
            f"Period Low: ${hist['Low'].min():.2f}",
            f"Avg Volume: {int(hist['Volume'].mean()):,}",
        ]

        # Build a {date, close} series for downstream consumers
        # (realized_vol_calc, monte_carlo_curve). Keep latest_close +
        # period_change_pct for back-compat with older callers.
        prices: list[dict[str, Any]] = []
        closes: list[float] = []
        for idx, row in hist.iterrows():
            close_val = row.get("Close")
            if close_val is None or close_val != close_val:  # NaN guard
                continue
            date_str = (
                idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
            )
            c = round(float(close_val), 4)
            prices.append({"date": date_str, "close": c})
            closes.append(c)

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "symbol": symbol,
                "latest_close": round(float(latest["Close"]), 2),
                "period_change_pct": round(change, 2),
                "prices": prices,
                "closes": closes,
                "price_count": len(prices),
                "status": "ok",
            },
        )

    @staticmethod
    def _company_info(ticker: Any, symbol: str) -> ToolResult:
        info = ticker.info
        if not info:
            return ToolResult(content=f"No company info found for {symbol}")

        fields = [
            ("Company", "longName"),
            ("Sector", "sector"),
            ("Industry", "industry"),
            ("Market Cap", "marketCap"),
            ("Enterprise Value", "enterpriseValue"),
            ("P/E Ratio", "trailingPE"),
            ("Forward P/E", "forwardPE"),
            ("PEG Ratio", "pegRatio"),
            ("Price/Book", "priceToBook"),
            ("Revenue", "totalRevenue"),
            ("Profit Margin", "profitMargins"),
            ("ROE", "returnOnEquity"),
            ("Debt/Equity", "debtToEquity"),
            ("52w High", "fiftyTwoWeekHigh"),
            ("52w Low", "fiftyTwoWeekLow"),
            ("Dividend Yield", "dividendYield"),
            ("Beta", "beta"),
        ]

        lines = [f"Company Info: {symbol}", ""]
        for label, key in fields:
            val = info.get(key)
            if val is not None:
                if isinstance(val, float):
                    if key in ("profitMargins", "returnOnEquity", "dividendYield"):
                        lines.append(f"  {label}: {val:.2%}")
                    elif key in ("marketCap", "enterpriseValue", "totalRevenue"):
                        lines.append(f"  {label}: ${val:,.0f}")
                    else:
                        lines.append(f"  {label}: {val:.2f}")
                else:
                    lines.append(f"  {label}: {val}")

        summary = info.get("longBusinessSummary", "")
        if summary:
            lines.append("")
            lines.append(f"Summary: {summary[:300]}...")

        return ToolResult(
            content="\n".join(lines),
            metadata={"symbol": symbol, "name": info.get("longName", "")},
        )

    @staticmethod
    def _earnings(ticker: Any, symbol: str) -> ToolResult:
        try:
            pass
        except Exception:
            pass

        lines = [f"Earnings: {symbol}", ""]

        # Try quarterly earnings
        try:
            quarterly = ticker.quarterly_earnings
            if quarterly is not None and not quarterly.empty:
                lines.append("Quarterly Earnings:")
                for idx, row in quarterly.iterrows():
                    rev = row.get("Revenue", "N/A")
                    earn = row.get("Earnings", "N/A")
                    if isinstance(rev, (int, float)):
                        rev = f"${rev:,.0f}"
                    if isinstance(earn, (int, float)):
                        earn = f"${earn:,.0f}"
                    lines.append(f"  {idx}: Revenue={rev}, Earnings={earn}")
                lines.append("")
        except Exception:
            pass

        # Try income statement for annual overview
        try:
            income = ticker.income_stmt
            if income is not None and not income.empty:
                lines.append("Annual Income (latest):")
                latest_col = income.columns[0]
                for metric in ["Total Revenue", "Gross Profit", "Net Income", "EBITDA"]:
                    if metric in income.index:
                        val = income.loc[metric, latest_col]
                        if val and not (isinstance(val, float) and val != val):
                            lines.append(f"  {metric}: ${float(val):,.0f}")
        except Exception:
            pass

        if len(lines) <= 2:
            lines.append("No earnings data available.")

        return ToolResult(content="\n".join(lines), metadata={"symbol": symbol})

    @staticmethod
    def _dividends(ticker: Any, symbol: str, period: str) -> ToolResult:
        divs = ticker.dividends
        if divs is None or divs.empty:
            return ToolResult(content=f"No dividend data found for {symbol}")

        # Take last N entries based on period
        limit_map = {"1y": 4, "2y": 8, "5y": 20, "max": len(divs)}
        limit = limit_map.get(period, 4)
        recent = divs.tail(limit)

        lines = [f"Dividends: {symbol}", f"Period: {period}", ""]
        for date, amount in recent.items():
            date_str = (
                date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
            )
            lines.append(f"  {date_str}: ${float(amount):.4f}")

        total = float(recent.sum())
        lines.append("")
        lines.append(f"Total ({len(recent)} payments): ${total:.4f}")

        return ToolResult(
            content="\n".join(lines),
            metadata={"symbol": symbol, "payment_count": len(recent)},
        )

    @staticmethod
    async def _fred_indicator(series_id: str, period: str) -> ToolResult:
        fred_key = credentials.get("FRED_API_KEY")
        if not fred_key:
            return ToolResult(
                content=(
                    "FRED_API_KEY is not configured. An admin can add it under "
                    "Admin -> Tool Configuration. Get a key at "
                    "https://fred.stlouisfed.org/docs/api/api_key.html"
                ),
                is_error=True,
                metadata={"needs_configuration": "FRED_API_KEY"},
            )

        try:
            from fredapi import Fred
        except ImportError:
            return ToolResult(
                content="Error: fredapi package is not installed. "
                "Install with: pip install fredapi",
                is_error=True,
            )

        try:
            fred = Fred(api_key=fred_key)
            series = fred.get_series(series_id)

            if series is None or series.empty:
                return ToolResult(
                    content=f"No data found for FRED series: {series_id}",
                )

            # Apply period filter
            period_map = {
                "1mo": 30,
                "3mo": 90,
                "6mo": 180,
                "1y": 365,
                "2y": 730,
                "5y": 1825,
            }
            import datetime

            if period in period_map:
                cutoff = datetime.datetime.now() - datetime.timedelta(
                    days=period_map[period]
                )
                series = series[series.index >= cutoff]

            recent = series.tail(12)
            lines = [f"FRED Economic Indicator: {series_id}", ""]
            for date, value in recent.items():
                date_str = (
                    date.strftime("%Y-%m-%d")
                    if hasattr(date, "strftime")
                    else str(date)
                )
                lines.append(f"  {date_str}: {float(value):.2f}")

            latest = float(series.iloc[-1])
            lines.append("")
            lines.append(f"Latest Value: {latest:.2f}")

            if len(series) >= 2:
                prev = float(series.iloc[-2])
                change = latest - prev
                pct = (change / prev) * 100 if prev != 0 else 0
                lines.append(f"Change: {change:+.2f} ({pct:+.2f}%)")

            return ToolResult(
                content="\n".join(lines),
                metadata={"series_id": series_id, "latest_value": latest},
            )
        except Exception as e:
            return ToolResult(
                content=f"FRED API error for {series_id}: {e}",
                is_error=True,
            )
