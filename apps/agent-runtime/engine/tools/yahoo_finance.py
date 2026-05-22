from __future__ import annotations

import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult

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
    "natgas_henry_hub": "NG=F",
    "natgas_ttf": "TTF=F",
    "heating_oil": "HO=F",
    "rbob_gasoline": "RB=F",
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
                "default": "1y",
                "description": (
                    "History period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"
                ),
            },
            "history_days": {
                "type": "integer",
                "description": (
                    "Optional shortcut for commodity_future: window in days. "
                    "Overrides period when set."
                ),
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        symbol = arguments.get("symbol", "")
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
                period = f"{max(history_days, 5)}d"
            if not resolved_symbol:
                return ToolResult(
                    content="Error: symbol or alias required", is_error=True
                )
            try:
                import yfinance as yf
            except ImportError:
                return ToolResult(content="yfinance not installed", is_error=True)
            try:
                ticker = yf.Ticker(resolved_symbol)
                result = self._stock_price(ticker, resolved_symbol, period)
                if alias_used:
                    result.metadata = {
                        **(result.metadata or {}),
                        "alias": alias_used,
                        "resolved_symbol": resolved_symbol,
                    }
                return result
            except Exception as e:
                return ToolResult(
                    content=f"Yahoo error for {resolved_symbol}: {e}", is_error=True
                )

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
            return ToolResult(content=f"No price data found for {symbol}")

        latest = hist.iloc[-1]
        first = hist.iloc[0]
        change = ((latest["Close"] - first["Close"]) / first["Close"]) * 100

        lines = [
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

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "symbol": symbol,
                "latest_close": round(float(latest["Close"]), 2),
                "period_change_pct": round(change, 2),
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
        fred_key = os.environ.get("FRED_API_KEY", "")
        if not fred_key:
            return ToolResult(
                content=(
                    "Error: FRED_API_KEY environment variable is not set. "
                    "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html "
                    "and set it with: export FRED_API_KEY=your_key"
                ),
                is_error=True,
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
