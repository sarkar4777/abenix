"""Ember Climate / Ember Energy — power-sector data.

Notes on what this actually provides (as of April 2026):
  • Base URL is now ``https://api.ember-energy.org/v1`` — the old
    ``ember-data-api-scg3n.ondigitalocean.app/v1`` host is decommissioned
    and returns 404 on every path.
  • Authentication is a ``?api_key=KEY`` query parameter. No Bearer token,
    no X-API-Key header — they are rejected silently (you get 200 on `/`
    but every data endpoint 404s without the query param).
  • Ember's public API does NOT expose EU ETS or UK ETS carbon PRICES.
    The closest public-API metric is carbon INTENSITY (gCO2/kWh) of
    electricity. The docs are explicit about this; ETS price data lives
    only in Ember's web tool, not the API. If the caller asks for a
    carbon price we return the intensity and flag the caveat so the LLM
    doesn't hallucinate a number.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE_URL = "https://api.ember-energy.org/v1"


def _get_api_key() -> str:
    return os.environ.get("EMBER_API_KEY", "").strip()


async def _get(path: str, params: dict[str, Any], api_key: str) -> dict[str, Any]:
    """GET a JSON endpoint with api_key as a query param (the only auth mode)."""
    full_params = {**params, "api_key": api_key}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{_BASE_URL}{path}", params=full_params)
        resp.raise_for_status()
        return resp.json()


class EmberClimateTool(BaseTool):
    name = "ember_climate"
    description = (
        "Fetch power-sector data from Ember's API (api.ember-energy.org): "
        "electricity generation mix by source, carbon intensity (gCO2/kWh), "
        "electricity demand. Note: Ember's public API does NOT serve EU/UK "
        "ETS carbon PRICES — only carbon intensity. Use a market-data feed "
        "for actual ETS prices."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["carbon_price", "carbon_intensity", "electricity_generation", "power_price", "electricity_demand"],
                "description": (
                    "Type of data. 'carbon_price' is a compatibility alias that "
                    "returns carbon INTENSITY (gCO2/kWh) — Ember doesn't serve "
                    "ETS prices. 'power_price' returns electricity demand (Ember "
                    "doesn't serve wholesale prices either)."
                ),
            },
            "country": {
                "type": "string",
                "default": "GBR",
                "description": "ISO 3-letter country code (entity_code)",
            },
            "year": {
                "type": "integer",
                "description": "Year for data (e.g., 2024). If omitted, defaults to last 12 months.",
            },
            "temporal_resolution": {
                "type": "string",
                "enum": ["monthly", "yearly"],
                "default": "monthly",
                "description": "Granularity of returned records.",
            },
        },
        "required": ["data_type"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        data_type = arguments.get("data_type", "")
        country = (arguments.get("country") or "GBR").upper()
        year = arguments.get("year")
        resolution = arguments.get("temporal_resolution", "monthly")
        if resolution not in ("monthly", "yearly"):
            resolution = "monthly"

        api_key = _get_api_key()
        if not api_key:
            return ToolResult(
                content=(
                    "Error: EMBER_API_KEY environment variable is not set. "
                    "Register for a free key at https://ember-energy.org/data/api/ "
                    "and export EMBER_API_KEY=<your-key>."
                ),
                is_error=True,
            )

        if not data_type:
            return ToolResult(content="Error: data_type is required", is_error=True)

        handlers = {
            "carbon_price": self._carbon_intensity,           # back-compat alias
            "carbon_intensity": self._carbon_intensity,
            "electricity_generation": self._electricity_generation,
            "power_price": self._electricity_demand,          # back-compat alias
            "electricity_demand": self._electricity_demand,
        }
        handler = handlers.get(data_type)
        if not handler:
            return ToolResult(
                content=(
                    f"Error: unknown data_type '{data_type}'. "
                    f"Available: {sorted(set(handlers.keys()))}"
                ),
                is_error=True,
            )

        try:
            return await handler(country, year, resolution, api_key)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            return ToolResult(
                content=(
                    f"Ember API HTTP {e.response.status_code} on "
                    f"{e.request.url.path}: {body}"
                ),
                is_error=True,
            )
        except httpx.RequestError as e:
            return ToolResult(content=f"Ember API request error: {e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Ember Climate error: {e}", is_error=True)

    @staticmethod
    def _date_range(year: int | None, resolution: str) -> tuple[str | None, str | None]:
        """Ember expects YYYY for yearly and YYYY-MM for monthly."""
        if year is None:
            return None, None
        if resolution == "yearly":
            return str(year), str(year)
        return f"{year}-01", f"{year}-12"

    async def _carbon_intensity(
        self, country: str, year: int | None, resolution: str, api_key: str,
    ) -> ToolResult:
        params: dict[str, Any] = {"entity_code": country}
        start, end = self._date_range(year, resolution)
        if start:
            params["start_date"] = start
            params["end_date"] = end
        data = await _get(f"/carbon-intensity/{resolution}", params, api_key)
        records = data.get("data") or []

        preface = (
            "NOTE: Ember's API does not expose EU ETS / UK ETS prices. "
            "This is carbon INTENSITY of the electricity grid (gCO2/kWh), "
            "not a price.\n"
        )

        if not records:
            return ToolResult(
                content=preface + f"No carbon-intensity {resolution} data for {country}"
                + (f" in {year}" if year else "") + ".",
            )

        lines = [
            preface,
            f"Ember Carbon Intensity ({resolution}) — {country}",
            f"Records: {len(records)}",
            "",
        ]
        intensities: list[float] = []
        for r in records[:24]:
            v = r.get("emissions_intensity_gco2_per_kwh")
            if v is None:
                continue
            intensities.append(float(v))
            lines.append(f"  {r.get('date', '?')}: {v:.1f} gCO2/kWh")

        if intensities:
            lines.append("")
            lines.append(f"Average: {sum(intensities) / len(intensities):.1f} gCO2/kWh")
            lines.append(f"Min / Max: {min(intensities):.1f} / {max(intensities):.1f} gCO2/kWh")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "data_type": "carbon_intensity",
                "country": country,
                "resolution": resolution,
                "records": len(records),
            },
        )

    async def _electricity_generation(
        self, country: str, year: int | None, resolution: str, api_key: str,
    ) -> ToolResult:
        params: dict[str, Any] = {"entity_code": country}
        start, end = self._date_range(year, resolution)
        if start:
            params["start_date"] = start
            params["end_date"] = end
        data = await _get(f"/electricity-generation/{resolution}", params, api_key)
        records = data.get("data") or []
        if not records:
            return ToolResult(
                content=f"No electricity-generation {resolution} data for {country}"
                + (f" in {year}" if year else "") + ".",
            )

        # Group by generation source. `series` is the source (Bioenergy, Coal, ...)
        # and records are non-aggregate rows.
        by_source: dict[str, float] = {}
        total_twh = 0.0
        for r in records:
            if r.get("is_aggregate_series"):
                continue
            source = r.get("series", "Unknown")
            twh = float(r.get("generation_twh") or 0.0)
            by_source[source] = by_source.get(source, 0.0) + twh
            total_twh += twh

        lines = [
            f"Ember Electricity Generation ({resolution}) — {country}",
            f"Records: {len(records)}",
            "",
            "Generation by source (TWh):",
        ]
        for source, twh in sorted(by_source.items(), key=lambda x: -x[1]):
            share = (twh / total_twh * 100) if total_twh else 0.0
            lines.append(f"  {source}: {twh:.2f} TWh ({share:.1f}%)")
        lines.append("")
        lines.append(f"Total: {total_twh:.2f} TWh across {len(by_source)} sources")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "data_type": "electricity_generation",
                "country": country,
                "resolution": resolution,
                "total_twh": round(total_twh, 2),
                "sources": len(by_source),
            },
        )

    async def _electricity_demand(
        self, country: str, year: int | None, resolution: str, api_key: str,
    ) -> ToolResult:
        params: dict[str, Any] = {"entity_code": country}
        start, end = self._date_range(year, resolution)
        if start:
            params["start_date"] = start
            params["end_date"] = end
        data = await _get(f"/electricity-demand/{resolution}", params, api_key)
        records = data.get("data") or []

        preface = (
            "NOTE: Ember's API does not expose wholesale electricity prices. "
            "Returning demand (TWh) as the closest available proxy.\n"
        )

        if not records:
            return ToolResult(
                content=preface + f"No electricity-demand {resolution} data for {country}"
                + (f" in {year}" if year else "") + ".",
            )

        lines = [
            preface,
            f"Ember Electricity Demand ({resolution}) — {country}",
            f"Records: {len(records)}",
            "",
        ]
        values: list[float] = []
        for r in records[:24]:
            v = r.get("demand_twh")
            if v is None:
                continue
            values.append(float(v))
            lines.append(f"  {r.get('date', '?')}: {v:.2f} TWh")

        if values:
            lines.append("")
            lines.append(f"Average: {sum(values) / len(values):.2f} TWh")
            lines.append(f"Total: {sum(values):.2f} TWh")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "data_type": "electricity_demand",
                "country": country,
                "resolution": resolution,
                "records": len(records),
            },
        )
