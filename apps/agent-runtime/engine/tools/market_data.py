"""Fetch market data from public APIs - energy, commodities, stocks, forex."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode

from engine.tools.base import BaseTool, ToolResult

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
EIA_API_KEY = os.environ.get("EIA_API_KEY", "")


class MarketDataTool(BaseTool):
    name = "market_data"
    description = (
        "Fetch real-time and historical market data including stock prices, "
        "commodities (oil, gas, metals), energy market prices (electricity, "
        "renewable energy certificates), forex rates, and economic indicators. "
        "Uses Alpha Vantage and EIA APIs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "stock_quote",
                    "stock_history",
                    "forex",
                    "commodity",
                    "energy_price",
                    "economic_indicator",
                ],
                "description": "Type of market data to fetch",
            },
            "symbol": {
                "type": "string",
                "description": "Ticker/symbol (e.g. 'AAPL', 'EUR/USD', 'WTI')",
            },
            "period": {
                "type": "string",
                "enum": ["daily", "weekly", "monthly"],
                "description": "Time period for historical data",
                "default": "daily",
            },
            "series_id": {
                "type": "string",
                "description": "EIA series ID for energy data (e.g. 'ELEC.PRICE.US-ALL.M')",
            },
        },
        "required": ["data_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        data_type = arguments.get("data_type", "")
        symbol = arguments.get("symbol", "")

        handlers = {
            "stock_quote": self._stock_quote,
            "stock_history": self._stock_history,
            "forex": self._forex,
            "commodity": self._commodity,
            "energy_price": self._energy_price,
            "economic_indicator": self._economic_indicator,
        }

        fn = handlers.get(data_type)
        if not fn:
            return ToolResult(content=f"Unknown data_type: {data_type}", is_error=True)

        try:
            result = await fn(arguments)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(
                content=output, metadata={"data_type": data_type, "symbol": symbol}
            )
        except Exception as e:
            return ToolResult(content=f"Market data error: {e}", is_error=True)

    async def _fetch_url(self, url: str) -> dict[str, Any]:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}: {await resp.text()}")
                return await resp.json()

    async def _stock_quote(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol", "")
        if not symbol:
            return {"error": "symbol is required"}

        if not ALPHA_VANTAGE_KEY:
            return self._mock_stock_quote(symbol)

        params = {
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_KEY,
        }
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        data = await self._fetch_url(url)

        quote = data.get("Global Quote", {})
        if not quote:
            return {"error": f"No data found for symbol: {symbol}"}

        return {
            "symbol": quote.get("01. symbol", symbol),
            "price": float(quote.get("05. price", 0)),
            "change": float(quote.get("09. change", 0)),
            "change_pct": quote.get("10. change percent", "0%"),
            "volume": int(quote.get("06. volume", 0)),
            "previous_close": float(quote.get("08. previous close", 0)),
            "open": float(quote.get("02. open", 0)),
            "high": float(quote.get("03. high", 0)),
            "low": float(quote.get("04. low", 0)),
        }

    async def _stock_history(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol", "")
        period = args.get("period", "daily")
        if not symbol:
            return {"error": "symbol is required"}

        if not ALPHA_VANTAGE_KEY:
            return self._mock_stock_history(symbol, period)

        functions = {
            "daily": "TIME_SERIES_DAILY",
            "weekly": "TIME_SERIES_WEEKLY",
            "monthly": "TIME_SERIES_MONTHLY",
        }
        params = {
            "function": functions.get(period, "TIME_SERIES_DAILY"),
            "symbol": symbol,
            "apikey": ALPHA_VANTAGE_KEY,
            "outputsize": "compact",
        }
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        data = await self._fetch_url(url)

        ts_key = [k for k in data.keys() if "Time Series" in k]
        if not ts_key:
            return {"error": f"No time series data for {symbol}"}

        series = data[ts_key[0]]
        points = []
        for date, vals in sorted(series.items(), reverse=True)[:30]:
            points.append(
                {
                    "date": date,
                    "open": float(vals.get("1. open", 0)),
                    "high": float(vals.get("2. high", 0)),
                    "low": float(vals.get("3. low", 0)),
                    "close": float(vals.get("4. close", 0)),
                    "volume": int(vals.get("5. volume", 0)),
                }
            )

        return {"symbol": symbol, "period": period, "data_points": points}

    async def _forex(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol", "EUR/USD")
        parts = symbol.replace("/", " ").split()
        from_currency = parts[0] if parts else "EUR"
        to_currency = parts[1] if len(parts) > 1 else "USD"

        if not ALPHA_VANTAGE_KEY:
            return self._mock_forex(from_currency, to_currency)

        params = {
            "function": "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_currency,
            "to_currency": to_currency,
            "apikey": ALPHA_VANTAGE_KEY,
        }
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        data = await self._fetch_url(url)

        rate_data = data.get("Realtime Currency Exchange Rate", {})
        return {
            "from": from_currency,
            "to": to_currency,
            "exchange_rate": float(rate_data.get("5. Exchange Rate", 0)),
            "bid": float(rate_data.get("8. Bid Price", 0)),
            "ask": float(rate_data.get("9. Ask Price", 0)),
            "last_refreshed": rate_data.get("6. Last Refreshed", ""),
        }

    async def _commodity(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol", "WTI").upper()

        commodity_functions = {
            "WTI": "WTI",
            "BRENT": "BRENT",
            "NATURAL_GAS": "NATURAL_GAS",
            "COPPER": "COPPER",
            "ALUMINUM": "ALUMINUM",
            "WHEAT": "WHEAT",
            "CORN": "CORN",
            "COTTON": "COTTON",
            "SUGAR": "SUGAR",
            "COFFEE": "COFFEE",
        }

        if not ALPHA_VANTAGE_KEY:
            return self._mock_commodity(symbol)

        function = commodity_functions.get(symbol, symbol)
        params = {
            "function": function,
            "interval": "monthly",
            "apikey": ALPHA_VANTAGE_KEY,
        }
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        data = await self._fetch_url(url)

        data_points = data.get("data", [])[:12]
        return {
            "commodity": symbol,
            "unit": data.get("unit", ""),
            "data": [
                {"date": d.get("date", ""), "value": float(d.get("value", 0))}
                for d in data_points
                if d.get("value", ".") != "."
            ],
        }

    async def _energy_price(self, args: dict[str, Any]) -> dict[str, Any]:
        series_id = args.get("series_id", "ELEC.PRICE.US-ALL.M")

        if not EIA_API_KEY:
            return self._mock_energy_price(series_id)

        url = f"https://api.eia.gov/v2/electricity/retail-sales/data/?api_key={EIA_API_KEY}&frequency=monthly&data[0]=price&sort[0][column]=period&sort[0][direction]=desc&length=12"
        data = await self._fetch_url(url)

        response_data = data.get("response", {}).get("data", [])
        return {
            "series": series_id,
            "source": "EIA",
            "data": [
                {
                    "period": d.get("period", ""),
                    "price_cents_per_kwh": d.get("price"),
                    "sector": d.get("sectorName", ""),
                    "state": d.get("stateid", ""),
                }
                for d in response_data[:12]
            ],
        }

    async def _economic_indicator(self, args: dict[str, Any]) -> dict[str, Any]:
        symbol = args.get("symbol", "GDP").upper()

        if not ALPHA_VANTAGE_KEY:
            return self._mock_economic(symbol)

        indicator_map = {
            "GDP": "REAL_GDP",
            "INFLATION": "INFLATION",
            "CPI": "CPI",
            "UNEMPLOYMENT": "UNEMPLOYMENT",
            "INTEREST_RATE": "FEDERAL_FUNDS_RATE",
            "TREASURY_YIELD": "TREASURY_YIELD",
        }

        function = indicator_map.get(symbol, symbol)
        params = {"function": function, "apikey": ALPHA_VANTAGE_KEY}
        url = f"https://www.alphavantage.co/query?{urlencode(params)}"
        data = await self._fetch_url(url)

        data_points = data.get("data", [])[:12]
        return {
            "indicator": symbol,
            "data": [
                {"date": d.get("date", ""), "value": float(d.get("value", 0))}
                for d in data_points
                if d.get("value", ".") != "."
            ],
        }

    def _mock_stock_quote(self, symbol: str) -> dict[str, Any]:
        import hashlib

        h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        price = 50 + (h % 200)
        return {
            "symbol": symbol,
            "price": round(price + 0.42, 2),
            "change": round((h % 10) - 5 + 0.23, 2),
            "change_pct": f"{round((h % 10 - 5) * 0.5, 2)}%",
            "volume": 1_000_000 + (h % 9_000_000),
            "previous_close": round(price - 0.5, 2),
            "open": round(price + 0.1, 2),
            "high": round(price + 3.5, 2),
            "low": round(price - 2.1, 2),
            "mode": "mock",
        }

    def _mock_stock_history(self, symbol: str, period: str) -> dict[str, Any]:
        import hashlib
        from datetime import datetime, timedelta

        h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
        base = 100 + (h % 200)
        points = []
        today = datetime.now()
        for i in range(30):
            d = today - timedelta(days=i)
            drift = (i % 7 - 3) * 0.5
            points.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "open": round(base + drift, 2),
                    "high": round(base + drift + 2, 2),
                    "low": round(base + drift - 1.5, 2),
                    "close": round(base + drift + 0.5, 2),
                    "volume": 500_000 + (h + i * 1000) % 2_000_000,
                }
            )
        return {
            "symbol": symbol,
            "period": period,
            "data_points": points,
            "mode": "mock",
        }

    def _mock_forex(self, from_c: str, to_c: str) -> dict[str, Any]:
        rates = {"EUR": 1.08, "GBP": 1.27, "JPY": 0.0067, "AUD": 0.65, "CAD": 0.74}
        rate = rates.get(from_c, 1.0)
        return {
            "from": from_c,
            "to": to_c,
            "exchange_rate": round(rate, 4),
            "bid": round(rate - 0.001, 4),
            "ask": round(rate + 0.001, 4),
            "mode": "mock",
        }

    def _mock_commodity(self, symbol: str) -> dict[str, Any]:
        prices = {
            "WTI": 72.5,
            "BRENT": 77.8,
            "NATURAL_GAS": 2.85,
            "COPPER": 4.2,
            "GOLD": 2050.0,
        }
        base = prices.get(symbol, 50.0)
        from datetime import datetime, timedelta

        today = datetime.now()
        return {
            "commodity": symbol,
            "unit": "USD",
            "data": [
                {
                    "date": (today - timedelta(days=30 * i)).strftime("%Y-%m"),
                    "value": round(base + (i % 5 - 2) * 1.5, 2),
                }
                for i in range(12)
            ],
            "mode": "mock",
        }

    def _mock_energy_price(self, series_id: str) -> dict[str, Any]:
        from datetime import datetime, timedelta

        today = datetime.now()
        return {
            "series": series_id,
            "source": "EIA (mock)",
            "data": [
                {
                    "period": (today - timedelta(days=30 * i)).strftime("%Y-%m"),
                    "price_cents_per_kwh": round(12.5 + (i % 4 - 2) * 0.3, 1),
                    "sector": "All Sectors",
                    "state": "US",
                }
                for i in range(12)
            ],
            "mode": "mock",
        }

    def _mock_economic(self, symbol: str) -> dict[str, Any]:
        values = {"GDP": 25500, "INFLATION": 3.2, "CPI": 307.5, "UNEMPLOYMENT": 3.8}
        base = values.get(symbol, 100)
        from datetime import datetime, timedelta

        today = datetime.now()
        return {
            "indicator": symbol,
            "data": [
                {
                    "date": (today - timedelta(days=90 * i)).strftime("%Y-%m-%d"),
                    "value": round(base + (i % 3 - 1) * base * 0.01, 2),
                }
                for i in range(12)
            ],
            "mode": "mock",
        }
