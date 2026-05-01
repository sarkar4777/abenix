"""World Bank Open Data — country-level macro indicators."""
from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://api.worldbank.org/v2"

# Friendly aliases for the most-asked indicators. Anything else can be passed
# verbatim as the indicator code.
_INDICATOR_ALIASES = {
    "gdp_usd": "NY.GDP.MKTP.CD",
    "gdp_per_capita": "NY.GDP.PCAP.CD",
    "population": "SP.POP.TOTL",
    "inflation": "FP.CPI.TOTL.ZG",
    "unemployment": "SL.UEM.TOTL.ZS",
    "co2_per_capita": "EN.ATM.CO2E.PC",
    "renewable_pct": "EG.FEC.RNEW.ZS",
    "internet_users_pct": "IT.NET.USER.ZS",
    "life_expectancy": "SP.DYN.LE00.IN",
}


class WorldBankTool(BaseTool):
    name = "world_bank"
    description = (
        "Country-level macro/development indicators from the World Bank "
        "(GDP, population, inflation, CO2, renewables share, etc.). "
        "Free, no API key. Use ISO3 country codes ('USA', 'DEU', 'IND')."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "country_code": {
                "type": "string",
                "description": "ISO3 country code, e.g. USA, DEU, IND, ZAF. Use 'WLD' for world total.",
            },
            "indicator": {
                "type": "string",
                "description": (
                    "Either a friendly alias (gdp_usd, gdp_per_capita, population, "
                    "inflation, unemployment, co2_per_capita, renewable_pct, "
                    "internet_users_pct, life_expectancy) or a raw World Bank "
                    "indicator code (e.g. 'EN.ATM.CO2E.KT')."
                ),
            },
            "start_year": {"type": "integer", "default": 2018},
            "end_year": {"type": "integer", "default": 2024},
        },
        "required": ["country_code", "indicator"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        country = (arguments.get("country_code") or "").upper().strip()
        indicator = (arguments.get("indicator") or "").strip()
        start = int(arguments.get("start_year", 2018))
        end = int(arguments.get("end_year", 2024))
        if not country or not indicator:
            return ToolResult(content="country_code and indicator are required", is_error=True)
        ind_code = _INDICATOR_ALIASES.get(indicator, indicator)

        url = f"{_BASE}/country/{country}/indicator/{ind_code}"
        params = {"format": "json", "date": f"{start}:{end}", "per_page": 200}

        # The World Bank API is free but occasionally slow — retry once on
        # timeouts/5xx so a transient hiccup doesn't fail the whole agent
        # step.
        last_exc: Exception | None = None
        payload = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(url, params=params)
                    r.raise_for_status()
                    payload = r.json()
                    break
            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    return ToolResult(
                        content=f"World Bank HTTP {e.response.status_code}: {e.response.text[:200]}",
                        is_error=True,
                    )
                last_exc = e
            except Exception as e:
                last_exc = e
        if payload is None:
            return ToolResult(
                content=f"World Bank fetch failed after retries: {type(last_exc).__name__}: {last_exc}",
                is_error=True,
            )

        # Response is a 2-element list: [meta, [records]]
        if not isinstance(payload, list) or len(payload) < 2:
            return ToolResult(content=f"Unexpected response shape: {str(payload)[:200]}", is_error=True)
        meta, records = payload[0], payload[1] or []
        if not records:
            return ToolResult(
                content=f"No data for {country}/{ind_code} in {start}-{end}.",
            )

        ind_label = (records[0].get("indicator") or {}).get("value", ind_code)
        country_label = (records[0].get("country") or {}).get("value", country)
        # Sort newest-first; World Bank returns reverse-chronological by default.
        records = sorted(records, key=lambda r: r.get("date") or "", reverse=True)

        lines = [
            f"World Bank — {country_label} · {ind_label}",
            f"Period: {start}-{end}",
            "",
        ]
        values: list[float] = []
        for r in records:
            v = r.get("value")
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            values.append(fv)
            lines.append(f"  {r.get('date')}: {fv:,.2f}")
        if values:
            lines.append("")
            lines.append(f"Latest: {values[0]:,.2f}  |  Series points: {len(values)}")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "country": country, "country_label": country_label,
                "indicator": ind_code, "indicator_label": ind_label,
                "values": [{"date": r.get("date"), "value": r.get("value")} for r in records],
            },
        )
