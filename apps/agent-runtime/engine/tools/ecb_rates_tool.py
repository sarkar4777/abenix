"""European Central Bank -- FX rates, inflation, and interest rates."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# Common currency ISO codes for the EUR cross-rate lookup
_CURRENCY_MAP: dict[str, str] = {
    "USD": "USD",
    "GBP": "GBP",
    "JPY": "JPY",
    "CHF": "CHF",
    "CAD": "CAD",
    "AUD": "AUD",
    "NZD": "NZD",
    "SEK": "SEK",
    "NOK": "NOK",
    "DKK": "DKK",
    "PLN": "PLN",
    "CZK": "CZK",
    "HUF": "HUF",
    "TRY": "TRY",
    "CNY": "CNY",
    "INR": "INR",
    "BRL": "BRL",
    "ZAR": "ZAR",
    "MXN": "MXN",
    "KRW": "KRW",
}


class ECBRatesTool(BaseTool):
    name = "ecb_rates"
    description = (
        "Fetch foreign exchange rates, inflation data, and interest rates "
        "from the European Central Bank Statistical Data Warehouse."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["fx_rate", "inflation", "interest_rate"],
                "description": "Type of data",
            },
            "currency_pair": {
                "type": "string",
                "description": "For fx_rate: EUR/USD, EUR/GBP, etc.",
                "default": "EUR/USD",
            },
            "date_from": {
                "type": "string",
                "description": "Start date (YYYY-MM-DD)",
            },
        },
        "required": ["data_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        data_type = arguments.get("data_type", "")
        currency_pair = arguments.get("currency_pair", "EUR/USD")
        date_from = arguments.get("date_from", "")

        if not data_type:
            return ToolResult(content="Error: data_type is required", is_error=True)

        handlers = {
            "fx_rate": self._fx_rate,
            "inflation": self._inflation,
            "interest_rate": self._interest_rate,
        }

        handler = handlers.get(data_type)
        if not handler:
            return ToolResult(
                content=f"Error: unknown data_type '{data_type}'. "
                f"Available: {list(handlers.keys())}",
                is_error=True,
            )

        try:
            return await handler(currency_pair=currency_pair, date_from=date_from)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"ECB API HTTP error {e.response.status_code}: {e.response.text[:500]}",
                is_error=True,
            )
        except httpx.RequestError as e:
            return ToolResult(
                content=f"ECB API request error: {e}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"ECB rates error: {e}",
                is_error=True,
            )

    async def _fx_rate(self, *, currency_pair: str, date_from: str) -> ToolResult:
        """Fetch EUR exchange rate from ECB."""
        # Parse currency pair (e.g., EUR/USD -> USD)
        parts = currency_pair.upper().replace(" ", "").split("/")
        if len(parts) == 2:
            target_currency = parts[1] if parts[0] == "EUR" else parts[0]
        else:
            target_currency = parts[0] if parts[0] != "EUR" else "USD"

        if target_currency not in _CURRENCY_MAP:
            return ToolResult(
                content=f"Error: unsupported currency '{target_currency}'. "
                f"Available: {list(_CURRENCY_MAP.keys())}",
                is_error=True,
            )

        # ECB SDMX key: EXR/D.{CCY}.EUR.SP00.A
        key = f"EXR/D.{target_currency}.EUR.SP00.A"

        params: dict[str, str] = {"format": "csvdata"}
        if date_from:
            params["startPeriod"] = date_from
        else:
            start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
            params["startPeriod"] = start

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_BASE_URL}/{key}",
                params=params,
                headers={"Accept": "text/csv"},
            )
            resp.raise_for_status()
            csv_text = resp.text

        return self._parse_csv_rates(csv_text, f"EUR/{target_currency}")

    async def _inflation(self, *, currency_pair: str, date_from: str) -> ToolResult:
        """Fetch Euro area HICP inflation rate."""
        # ICP key: ICP/M.U2.N.000000.4.ANR (monthly, Euro area, all items, annual rate)
        key = "ICP/M.U2.N.000000.4.ANR"

        params: dict[str, str] = {"format": "csvdata"}
        if date_from:
            params["startPeriod"] = date_from
        else:
            start = (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d")
            params["startPeriod"] = start

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_BASE_URL}/{key}",
                params=params,
                headers={"Accept": "text/csv"},
            )
            resp.raise_for_status()
            csv_text = resp.text

        return self._parse_csv_inflation(csv_text)

    async def _interest_rate(self, *, currency_pair: str, date_from: str) -> ToolResult:
        """Fetch ECB key interest rates (MRO, deposit facility, marginal lending)."""
        # FM key: FM/D.U2.EUR.4F.KR.MRR_FR.LEV (Main Refinancing Operations rate)
        key = "FM/D.U2.EUR.4F.KR.MRR_FR.LEV"

        params: dict[str, str] = {"format": "csvdata"}
        if date_from:
            params["startPeriod"] = date_from
        else:
            start = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")
            params["startPeriod"] = start

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_BASE_URL}/{key}",
                params=params,
                headers={"Accept": "text/csv"},
            )
            resp.raise_for_status()
            csv_text = resp.text

        return self._parse_csv_interest_rate(csv_text)

    @staticmethod
    def _parse_csv_rates(csv_text: str, pair: str) -> ToolResult:
        """Parse ECB CSV response for FX rates."""
        lines_raw = csv_text.strip().split("\n")
        if len(lines_raw) < 2:
            return ToolResult(content=f"No FX rate data returned for {pair}.")

        header = lines_raw[0].split(",")

        # Find TIME_PERIOD and OBS_VALUE column indices
        time_idx = next((i for i, h in enumerate(header) if "TIME_PERIOD" in h), -1)
        val_idx = next((i for i, h in enumerate(header) if "OBS_VALUE" in h), -1)

        if time_idx < 0 or val_idx < 0:
            return ToolResult(
                content=f"Unexpected CSV format from ECB. Headers: {header[:10]}",
                is_error=True,
            )

        data_points: list[tuple[str, float]] = []
        for row_line in lines_raw[1:]:
            cols = row_line.split(",")
            if len(cols) <= max(time_idx, val_idx):
                continue
            try:
                date = cols[time_idx].strip().strip('"')
                value = float(cols[val_idx].strip().strip('"'))
                data_points.append((date, value))
            except (ValueError, IndexError):
                continue

        if not data_points:
            return ToolResult(content=f"No data points parsed for {pair}.")

        data_points.sort(key=lambda x: x[0])
        latest = data_points[-1]
        first = data_points[0]
        change = ((latest[1] - first[1]) / first[1]) * 100

        output_lines = [
            f"ECB Exchange Rate: {pair}",
            f"Latest: {latest[1]:.4f} ({latest[0]})",
            f"Period start: {first[1]:.4f} ({first[0]})",
            f"Change: {change:+.2f}%",
            f"Data points: {len(data_points)}",
            "",
        ]

        # Show last 20 data points
        for date, val in data_points[-20:]:
            output_lines.append(f"  {date}: {val:.4f}")

        return ToolResult(
            content="\n".join(output_lines),
            metadata={
                "pair": pair,
                "latest_rate": round(latest[1], 4),
                "latest_date": latest[0],
                "period_change_pct": round(change, 2),
                "data_points": len(data_points),
            },
        )

    @staticmethod
    def _parse_csv_inflation(csv_text: str) -> ToolResult:
        """Parse ECB CSV response for inflation data."""
        lines_raw = csv_text.strip().split("\n")
        if len(lines_raw) < 2:
            return ToolResult(content="No inflation data returned from ECB.")

        header = lines_raw[0].split(",")
        time_idx = next((i for i, h in enumerate(header) if "TIME_PERIOD" in h), -1)
        val_idx = next((i for i, h in enumerate(header) if "OBS_VALUE" in h), -1)

        if time_idx < 0 or val_idx < 0:
            return ToolResult(
                content=f"Unexpected CSV format. Headers: {header[:10]}",
                is_error=True,
            )

        data_points: list[tuple[str, float]] = []
        for row_line in lines_raw[1:]:
            cols = row_line.split(",")
            if len(cols) <= max(time_idx, val_idx):
                continue
            try:
                date = cols[time_idx].strip().strip('"')
                value = float(cols[val_idx].strip().strip('"'))
                data_points.append((date, value))
            except (ValueError, IndexError):
                continue

        if not data_points:
            return ToolResult(content="No inflation data points parsed.")

        data_points.sort(key=lambda x: x[0])
        latest = data_points[-1]

        output_lines = [
            "ECB Euro Area Inflation (HICP, Annual Rate)",
            f"Latest: {latest[1]:.1f}% ({latest[0]})",
            f"Data points: {len(data_points)}",
            "",
        ]

        for date, val in data_points[-24:]:
            output_lines.append(f"  {date}: {val:.1f}%")

        return ToolResult(
            content="\n".join(output_lines),
            metadata={
                "data_type": "inflation",
                "latest_rate": round(latest[1], 1),
                "latest_period": latest[0],
                "data_points": len(data_points),
            },
        )

    @staticmethod
    def _parse_csv_interest_rate(csv_text: str) -> ToolResult:
        """Parse ECB CSV response for interest rates."""
        lines_raw = csv_text.strip().split("\n")
        if len(lines_raw) < 2:
            return ToolResult(content="No interest rate data returned from ECB.")

        header = lines_raw[0].split(",")
        time_idx = next((i for i, h in enumerate(header) if "TIME_PERIOD" in h), -1)
        val_idx = next((i for i, h in enumerate(header) if "OBS_VALUE" in h), -1)

        if time_idx < 0 or val_idx < 0:
            return ToolResult(
                content=f"Unexpected CSV format. Headers: {header[:10]}",
                is_error=True,
            )

        data_points: list[tuple[str, float]] = []
        for row_line in lines_raw[1:]:
            cols = row_line.split(",")
            if len(cols) <= max(time_idx, val_idx):
                continue
            try:
                date = cols[time_idx].strip().strip('"')
                value = float(cols[val_idx].strip().strip('"'))
                data_points.append((date, value))
            except (ValueError, IndexError):
                continue

        if not data_points:
            return ToolResult(content="No interest rate data points parsed.")

        data_points.sort(key=lambda x: x[0])
        latest = data_points[-1]

        output_lines = [
            "ECB Main Refinancing Operations Rate (MRO)",
            f"Current rate: {latest[1]:.2f}% ({latest[0]})",
            f"Data points: {len(data_points)}",
            "",
        ]

        # Show rate changes (only display when rate differs from previous)
        prev_val = None
        for date, val in data_points[-30:]:
            if prev_val is None or val != prev_val:
                output_lines.append(f"  {date}: {val:.2f}%")
            prev_val = val

        return ToolResult(
            content="\n".join(output_lines),
            metadata={
                "data_type": "interest_rate",
                "current_rate": round(latest[1], 2),
                "latest_date": latest[0],
                "data_points": len(data_points),
            },
        )
