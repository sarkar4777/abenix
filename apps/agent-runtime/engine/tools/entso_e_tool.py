"""ENTSO-E Transparency Platform -- European electricity market data."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE_URL = "https://web-api.tp.entsoe.eu/api"

# ENTSO-E area/bidding zone EIC codes
_AREA_CODES: dict[str, str] = {
    "DE_LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C",
    "ES": "10YES-REE------0",
    "IT": "10YIT-GRTN-----B",
    "NL": "10YNL----------L",
    "GB": "10YGB----------A",
    "BE": "10YBE----------2",
    "AT": "10YAT-APG------L",
    "PL": "10YPL-AREA-----S",
    "PT": "10YPT-REN------W",
    "DK": "10Y1001A1001A65H",
    "NO": "10YNO-0--------C",
    "SE": "10YSE-1--------K",
    "FI": "10YFI-1--------U",
    "CH": "10YCH-SWISSGRIDZ",
    "CZ": "10YCZ-CEPS-----N",
    "GR": "10YGR-HTSO-----Y",
    "RO": "10YRO-TEL------P",
    "HU": "10YHU-MAVIR----U",
    "IE": "10YIE-1001A00010",
}

# documentType mapping per data_type
_DOC_TYPES: dict[str, str] = {
    "day_ahead_price": "A44",
    "generation": "A75",
    "load_forecast": "A65",
    "installed_capacity": "A68",
}


class EntsoETool(BaseTool):
    name = "entso_e"
    description = (
        "Fetch European electricity market data from ENTSO-E Transparency Platform. "
        "Day-ahead prices, wind/solar generation, load forecasts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["day_ahead_price", "generation", "load_forecast", "installed_capacity"],
                "description": "Type of data to fetch",
            },
            "area": {
                "type": "string",
                "description": "Country/bidding zone code (e.g., DE_LU, FR, ES, IT, NL, GB)",
                "default": "DE_LU",
            },
            "date_from": {
                "type": "string",
                "description": "Start date (YYYY-MM-DD)",
            },
            "date_to": {
                "type": "string",
                "description": "End date (YYYY-MM-DD)",
            },
        },
        "required": ["data_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        api_key = os.environ.get("ENTSOE_API_KEY", "")
        if not api_key:
            return ToolResult(
                content=(
                    "Error: ENTSOE_API_KEY environment variable is not set. "
                    "Register at https://transparency.entsoe.eu/ to obtain an API token, "
                    "then set it with: export ENTSOE_API_KEY=your_token"
                ),
                is_error=True,
            )

        data_type = arguments.get("data_type", "")
        area = arguments.get("area", "DE_LU").upper()
        date_from = arguments.get("date_from", "")
        date_to = arguments.get("date_to", "")

        if not data_type:
            return ToolResult(content="Error: data_type is required", is_error=True)

        doc_type = _DOC_TYPES.get(data_type)
        if not doc_type:
            return ToolResult(
                content=f"Error: unknown data_type '{data_type}'. "
                        f"Available: {list(_DOC_TYPES.keys())}",
                is_error=True,
            )

        # Resolve area to EIC code
        eic = _AREA_CODES.get(area, area)
        if len(eic) < 10:
            return ToolResult(
                content=f"Error: unknown area '{area}'. "
                        f"Available: {list(_AREA_CODES.keys())}",
                is_error=True,
            )

        # Default date range: last 7 days
        if not date_from:
            date_from = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not date_to:
            date_to = datetime.utcnow().strftime("%Y-%m-%d")

        # ENTSO-E expects YYYYMMDDHHmm format
        period_start = date_from.replace("-", "") + "0000"
        period_end = date_to.replace("-", "") + "2300"

        params: dict[str, str] = {
            "securityToken": api_key,
            "documentType": doc_type,
            "in_Domain": eic,
            "out_Domain": eic,
            "periodStart": period_start,
            "periodEnd": period_end,
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(_BASE_URL, params=params)
                resp.raise_for_status()
                xml_text = resp.text
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"ENTSO-E API HTTP error {e.response.status_code}: {e.response.text[:500]}",
                is_error=True,
            )
        except httpx.RequestError as e:
            return ToolResult(
                content=f"ENTSO-E API request error: {e}",
                is_error=True,
            )

        try:
            return self._parse_xml(xml_text, data_type, area, date_from, date_to)
        except Exception as e:
            return ToolResult(
                content=f"Error parsing ENTSO-E XML response: {e}",
                is_error=True,
            )

    @staticmethod
    def _parse_xml(
        xml_text: str,
        data_type: str,
        area: str,
        date_from: str,
        date_to: str,
    ) -> ToolResult:
        """Parse ENTSO-E XML response and extract TimeSeries data."""
        root = ET.fromstring(xml_text)

        # Handle XML namespaces — ENTSO-E uses a default namespace
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        time_series_list = root.findall(f"{ns}TimeSeries")
        if not time_series_list:
            return ToolResult(
                content=f"No TimeSeries data found for {data_type} in {area} "
                        f"({date_from} to {date_to}). The area or date range may have no data.",
            )

        all_points: list[dict[str, Any]] = []
        unit = ""

        for ts in time_series_list:
            # Extract currency/unit
            currency_el = ts.find(f"{ns}currency_Unit.name")
            measure_el = ts.find(f"{ns}quantity_Measure_Unit.name")
            if currency_el is not None and currency_el.text:
                unit = currency_el.text + "/MWh"
            elif measure_el is not None and measure_el.text:
                unit = measure_el.text

            for period in ts.findall(f"{ns}Period"):
                start_el = period.find(f"{ns}timeInterval/{ns}start")
                resolution_el = period.find(f"{ns}resolution")
                start_str = start_el.text if start_el is not None else ""
                resolution = resolution_el.text if resolution_el is not None else "PT60M"

                # Parse start time
                try:
                    start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    start_dt = None

                # Determine resolution in minutes
                res_minutes = 60
                if "PT15M" in resolution:
                    res_minutes = 15
                elif "PT30M" in resolution:
                    res_minutes = 30
                elif "PT60M" in resolution or "P1H" in resolution:
                    res_minutes = 60

                for point in period.findall(f"{ns}Point"):
                    pos_el = point.find(f"{ns}position")
                    val_el = point.find(f"{ns}price.amount") or point.find(f"{ns}quantity")
                    if pos_el is None or val_el is None:
                        continue

                    position = int(pos_el.text or "0")
                    value = float(val_el.text or "0")

                    timestamp = ""
                    if start_dt:
                        ts_dt = start_dt + timedelta(minutes=res_minutes * (position - 1))
                        timestamp = ts_dt.strftime("%Y-%m-%d %H:%M")

                    all_points.append({
                        "timestamp": timestamp,
                        "position": position,
                        "value": round(value, 2),
                    })

        if not all_points:
            return ToolResult(
                content=f"No data points found in TimeSeries for {data_type} in {area}.",
            )

        # Sort by timestamp
        all_points.sort(key=lambda p: p["timestamp"])

        # Compute summary statistics
        values = [p["value"] for p in all_points]
        avg_val = sum(values) / len(values)
        min_val = min(values)
        max_val = max(values)
        min_point = next(p for p in all_points if p["value"] == min_val)
        max_point = next(p for p in all_points if p["value"] == max_val)

        label = "Price" if data_type == "day_ahead_price" else "Value"

        lines = [
            f"ENTSO-E {data_type.replace('_', ' ').title()} -- {area}",
            f"Period: {date_from} to {date_to}",
            f"Unit: {unit or 'N/A'}",
            f"Data points: {len(all_points)}",
            "",
            f"Average {label}: {avg_val:.2f}",
            f"Min {label}: {min_val:.2f} ({min_point['timestamp']})",
            f"Max {label}: {max_val:.2f} ({max_point['timestamp']})",
            "",
        ]

        # Show a sample of data points (first 24 and last 24)
        sample_size = 24
        if len(all_points) <= sample_size * 2:
            sample = all_points
        else:
            sample = all_points[:sample_size] + [{"timestamp": "...", "value": 0}] + all_points[-sample_size:]

        lines.append("Sample data points:")
        for p in sample:
            if p["timestamp"] == "...":
                lines.append("  ...")
            else:
                lines.append(f"  {p['timestamp']}: {p['value']:.2f}")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "data_type": data_type,
                "area": area,
                "point_count": len(all_points),
                "average": round(avg_val, 2),
                "min": round(min_val, 2),
                "max": round(max_val, 2),
                "unit": unit,
            },
        )
