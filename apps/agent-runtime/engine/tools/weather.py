"""Weather data via Open-Meteo (free, no API key)."""
from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"


async def _resolve_coords(location: str) -> tuple[float, float, str] | None:
    """location may be 'lat,lon' or a place name. Returns (lat, lon, label)."""
    s = location.strip()
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        try:
            return float(parts[0]), float(parts[1]), s
        except ValueError:
            pass
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(_GEO_URL, params={"name": s, "count": 1})
        r.raise_for_status()
        results = r.json().get("results") or []
    if not results:
        return None
    top = results[0]
    label = ", ".join(filter(None, [top.get("name"), top.get("admin1"), top.get("country")]))
    return float(top["latitude"]), float(top["longitude"]), label


class WeatherTool(BaseTool):
    name = "weather"
    description = (
        "Current weather and forecast for any location worldwide. Free, no API key. "
        "Accepts city names ('Berlin'), 'City, Country' ('Tokyo, Japan'), or raw "
        "'lat,lon' coordinates. Returns temperature, wind, precipitation, and an "
        "N-day forecast with daily highs/lows."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name or 'lat,lon'"},
            "forecast_days": {
                "type": "integer", "default": 3, "minimum": 0, "maximum": 16,
                "description": "Number of forecast days (0 = current only).",
            },
            "units": {
                "type": "string", "enum": ["metric", "imperial"], "default": "metric",
                "description": "metric = Celsius/km/h, imperial = Fahrenheit/mph.",
            },
        },
        "required": ["location"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        location = arguments.get("location", "")
        days = int(arguments.get("forecast_days", 3))
        units = arguments.get("units", "metric")
        if not location:
            return ToolResult(content="Error: location is required", is_error=True)

        try:
            coords = await _resolve_coords(location)
        except Exception as e:
            return ToolResult(content=f"Geocoding failed: {e}", is_error=True)
        if not coords:
            return ToolResult(content=f"No location matched '{location}'", is_error=True)
        lat, lon, label = coords

        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation,weather_code",
            "timezone": "auto",
        }
        if units == "imperial":
            params["temperature_unit"] = "fahrenheit"
            params["wind_speed_unit"] = "mph"
            params["precipitation_unit"] = "inch"
        if days > 0:
            params["daily"] = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
            params["forecast_days"] = days

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(_FORECAST_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"Open-Meteo HTTP {e.response.status_code}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Weather fetch failed: {e}", is_error=True)

        cur = data.get("current") or {}
        unit_t = "F" if units == "imperial" else "C"
        unit_w = "mph" if units == "imperial" else "km/h"
        unit_p = "in" if units == "imperial" else "mm"
        lines = [
            f"Weather — {label} ({lat:.4f}, {lon:.4f})",
            f"Current: {cur.get('temperature_2m', '?')}°{unit_t}, "
            f"wind {cur.get('wind_speed_10m', '?')} {unit_w}, "
            f"humidity {cur.get('relative_humidity_2m', '?')}%, "
            f"precip {cur.get('precipitation', 0)} {unit_p}",
        ]
        daily = data.get("daily") or {}
        if daily.get("time"):
            lines.append("")
            lines.append(f"Forecast ({len(daily['time'])} days):")
            for i, day in enumerate(daily["time"]):
                hi = (daily.get("temperature_2m_max") or [])[i]
                lo = (daily.get("temperature_2m_min") or [])[i]
                pr = (daily.get("precipitation_sum") or [None])[i]
                wd = (daily.get("wind_speed_10m_max") or [None])[i]
                lines.append(
                    f"  {day}: hi {hi}°{unit_t}, lo {lo}°{unit_t}, "
                    f"precip {pr} {unit_p}, max wind {wd} {unit_w}"
                )

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "lat": lat, "lon": lon, "label": label,
                "current": cur, "daily": daily,
                "units": units,
            },
        )
