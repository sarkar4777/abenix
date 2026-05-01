"""US macro indicators via FRED (St. Louis Fed)."""
from __future__ import annotations

import csv
import io
import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://api.stlouisfed.org/fred"
_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

# Friendly aliases for FRED series ids.
_SERIES_ALIASES = {
    "fed_funds_rate":     "FEDFUNDS",
    "ten_year_treasury":  "DGS10",
    "two_year_treasury":  "DGS2",
    "cpi":                "CPIAUCSL",
    "core_cpi":           "CPILFESL",
    "unemployment":       "UNRATE",
    "gdp":                "GDP",
    "real_gdp":           "GDPC1",
    "wti_oil":            "DCOILWTICO",
    "natural_gas":        "DHHNGSP",
    "gold":               "GOLDAMGBD228NLBM",
    "us_dollar_index":    "DTWEXBGS",
    "consumer_sentiment": "UMCSENT",
}


class FredEconomicTool(BaseTool):
    name = "fred_economic"
    description = (
        "US macroeconomic time-series from FRED (St. Louis Fed) — "
        "interest rates, CPI, unemployment, GDP, oil/gas/gold prices. "
        "Set FRED_API_KEY for full access; falls back to public CSV for "
        "popular series without a key."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "series_id": {
                "type": "string",
                "description": (
                    "Either a friendly alias (fed_funds_rate, ten_year_treasury, "
                    "cpi, unemployment, gdp, wti_oil, natural_gas, gold, ...) "
                    "or a raw FRED series id (e.g. 'DGS30')."
                ),
            },
            "start_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Default: 12 months back.",
            },
            "end_date": {
                "type": "string",
                "description": "ISO date YYYY-MM-DD. Default: today.",
            },
            "limit": {
                "type": "integer", "default": 50, "minimum": 1, "maximum": 1000,
                "description": "Most recent N observations to return.",
            },
        },
        "required": ["series_id"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        sid_raw = (arguments.get("series_id") or "").strip()
        if not sid_raw:
            return ToolResult(content="series_id is required", is_error=True)
        series = _SERIES_ALIASES.get(sid_raw, sid_raw).upper()
        start = arguments.get("start_date")
        end = arguments.get("end_date")
        limit = int(arguments.get("limit", 50))

        api_key = os.environ.get("FRED_API_KEY", "").strip()
        try:
            if api_key:
                params: dict[str, Any] = {
                    "series_id": series, "api_key": api_key, "file_type": "json",
                    "sort_order": "desc", "limit": limit,
                }
                if start: params["observation_start"] = start
                if end: params["observation_end"] = end
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(f"{_BASE}/series/observations", params=params)
                    r.raise_for_status()
                    data = r.json()
                obs = [
                    {"date": o.get("date"), "value": o.get("value")}
                    for o in (data.get("observations") or [])
                    if o.get("value") not in (None, ".", "")
                ]
                source = "fred-json"
            else:
                # Public CSV fallback — works for most popular series.
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(_CSV_BASE, params={"id": series})
                    r.raise_for_status()
                    text = r.text
                rows = list(csv.DictReader(io.StringIO(text)))
                if not rows:
                    return ToolResult(
                        content=f"No data for {series}. Set FRED_API_KEY for non-popular series.",
                        is_error=True,
                    )
                # CSV header is "DATE", "<SERIES>"
                value_col = next((c for c in rows[0] if c != "DATE"), None)
                obs = [{"date": r["DATE"], "value": r[value_col]} for r in rows if r.get(value_col) not in (None, ".", "")]
                obs = list(reversed(obs))[:limit]  # newest first, capped
                source = "fred-csv-public"
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"FRED HTTP {e.response.status_code}: {e.response.text[:200]}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"FRED fetch failed: {e}", is_error=True)

        if not obs:
            return ToolResult(content=f"No observations for {series}.")

        try:
            values = [float(o["value"]) for o in obs]
        except ValueError:
            values = []
        lines = [
            f"FRED — {series} (source: {source})",
            f"Observations: {len(obs)}",
            "",
        ]
        for o in obs[:30]:
            lines.append(f"  {o['date']}: {o['value']}")
        if values:
            lines.append("")
            lines.append(f"Latest: {values[0]}  |  Min: {min(values)}  |  Max: {max(values)}")

        return ToolResult(
            content="\n".join(lines),
            metadata={"series_id": series, "source": source, "observations": obs},
        )
