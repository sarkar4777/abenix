from __future__ import annotations

import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class YahooFinanceTool(BaseTool):
    name = "yahoo_finance"
    description = (
        "Get financial data: stock prices, company financials, earnings, "
        "dividends, and economic indicators from FRED."
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
                ],
            },
            "symbol": {
                "type": "string",
                "description": (
                    "Stock ticker (e.g., 'AAPL') or FRED indicator "
                    "(e.g., 'GDP', 'UNRATE', 'CPIAUCSL')"
                ),
            },
            "period": {
                "type": "string",
                "default": "1y",
                "description": (
                    "History period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, max"
                ),
            },
        },
        "required": ["action", "symbol"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        symbol = arguments.get("symbol", "")
        period = arguments.get("period", "1y")

        if not action or not symbol:
            return ToolResult(
                content="Error: both 'action' and 'symbol' are required",
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
