"""open_meteo — free weather + marine forecast for shipping & operations.

Open-Meteo (api.open-meteo.com) is fully free, no API key, and serves both
generic forecasts and a dedicated marine endpoint with wave height, wind,
swell — exactly what an Operations Sentinel needs to flag vessels at risk
of port closures or ETA slippage.

Shortcut location ids are pre-mapped to the major energy-trading hubs.
Pass a raw lat/lon for anywhere else.
"""

from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

_HUBS: dict[str, tuple[float, float, str]] = {
    "USGC_HOUSTON": (29.7604, -95.3698, "Houston Ship Channel (USGC)"),
    "USGC_MONT_BELVIEU": (29.8447, -94.8919, "Mont Belvieu, TX (USGC hub)"),
    "USEC_NEW_YORK": (40.6892, -74.0445, "New York Harbor (USEC)"),
    "NWE_ROTTERDAM": (51.9225, 4.4792, "Rotterdam (NWE)"),
    "NWE_ANTWERP": (51.2194, 4.4025, "Antwerp (NWE)"),
    "NWE_TEESPORT": (54.6037, -1.1389, "Teesport (NWE)"),
    "FE_CHIBA": (35.6074, 140.1065, "Chiba (Far East — Japan)"),
    "FE_SINGAPORE": (1.2655, 103.8195, "Singapore (Far East)"),
    "FE_DAESAN": (37.0117, 126.4128, "Daesan (Far East — South Korea)"),
    "ME_RAS_TANURA": (26.6444, 50.1583, "Ras Tanura (Middle East)"),
}


class OpenMeteoTool(BaseTool):
    name = "open_meteo"
    risk_tier = "low"
    description = (
        "Fetch free weather and marine forecasts from Open-Meteo. Use one of "
        "the shortcut location ids (USGC_HOUSTON, USGC_MONT_BELVIEU, "
        "NWE_ROTTERDAM, NWE_ANTWERP, FE_CHIBA, FE_SINGAPORE, ME_RAS_TANURA, "
        "etc.) for the common energy-trading hubs, or pass lat/lon for any "
        "point on earth. Set mode='marine' for wave height + swell + sea "
        "surface temp; default mode='atmosphere' for wind + temp + "
        "precipitation. Useful for: port-closure risk, hurricane funnel "
        "windows, vessel-routing impact, terminal slot disruption forecasts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": (
                    "Shortcut id (USGC_HOUSTON, NWE_ROTTERDAM, FE_CHIBA, "
                    "ME_RAS_TANURA, etc.) or empty if you pass lat/lon."
                ),
            },
            "lat": {
                "type": "number",
                "description": "Latitude (omit if location set).",
            },
            "lon": {
                "type": "number",
                "description": "Longitude (omit if location set).",
            },
            "mode": {
                "type": "string",
                "enum": ["atmosphere", "marine"],
                "default": "atmosphere",
                "description": (
                    "'atmosphere' returns wind, temperature, precipitation, "
                    "pressure (the default). 'marine' returns wave height, "
                    "wave period, swell, sea-surface temperature."
                ),
            },
            "horizon_days": {
                "type": "integer",
                "default": 7,
                "minimum": 1,
                "maximum": 16,
                "description": "Forecast horizon in days (1–16).",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        loc = (arguments.get("location") or "").strip()
        lat = arguments.get("lat")
        lon = arguments.get("lon")
        label = ""
        if loc:
            hub = _HUBS.get(loc)
            if not hub:
                return ToolResult(
                    content=(
                        f"Unknown location shortcut '{loc}'. Known: "
                        f"{', '.join(_HUBS.keys())}. Or pass lat+lon."
                    ),
                    is_error=True,
                )
            lat, lon, label = hub
        if lat is None or lon is None:
            return ToolResult(
                content="Either location (shortcut) or lat+lon must be provided.",
                is_error=True,
            )

        mode = (arguments.get("mode") or "atmosphere").lower()
        horizon = int(arguments.get("horizon_days") or 7)

        try:
            if mode == "marine":
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": "wave_height,wave_period,wind_wave_height,sea_surface_temperature",
                    "forecast_days": horizon,
                    "timezone": "UTC",
                }
                url = _MARINE_URL
            else:
                params = {
                    "latitude": lat,
                    "longitude": lon,
                    "daily": (
                        "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                        "wind_speed_10m_max,wind_gusts_10m_max,weather_code"
                    ),
                    "forecast_days": horizon,
                    "timezone": "UTC",
                }
                url = _FORECAST_URL

            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(url, params=params)
                if r.status_code >= 400:
                    return ToolResult(
                        content=f"Open-Meteo HTTP {r.status_code}: {r.text[:300]}",
                        is_error=True,
                    )
                data = r.json()
        except httpx.HTTPError as e:
            return ToolResult(content=f"Open-Meteo request failed: {e}", is_error=True)

        location_label = label or f"({lat:.4f}, {lon:.4f})"
        lines = [f"Open-Meteo {mode} forecast — {location_label}", ""]

        if mode == "marine":
            hourly = data.get("hourly") or {}
            times = hourly.get("time") or []
            wave = hourly.get("wave_height") or []
            swell = hourly.get("wind_wave_height") or []
            sst = hourly.get("sea_surface_temperature") or []

            window = list(zip(times, wave, swell, sst))[
                :: max(1, len(times) // 24) or 1
            ][:24]
            max_wave = max((v for v in wave if v is not None), default=0.0)
            mean_wave = (
                sum(v for v in wave if v is not None)
                / max(1, len([v for v in wave if v is not None]))
                if wave
                else 0.0
            )
            lines.append(f"Peak wave height (next {horizon}d): {max_wave:.2f} m")
            lines.append(f"Mean wave height: {mean_wave:.2f} m")
            lines.append("")
            lines.append("Hourly sample (t · wave · swell · SST):")
            for t, w, s, ss in window[:12]:
                lines.append(
                    f"  {t}: wave {w if w is not None else '—'}m  "
                    f"swell {s if s is not None else '—'}m  "
                    f"SST {ss if ss is not None else '—'}°C"
                )
            metadata = {
                "mode": "marine",
                "location": location_label,
                "lat": lat,
                "lon": lon,
                "horizon_days": horizon,
                "max_wave_m": round(max_wave, 2),
                "mean_wave_m": round(mean_wave, 2),
                "source": "https://marine-api.open-meteo.com",
            }
        else:
            daily = data.get("daily") or {}
            times = daily.get("time") or []
            tmax = daily.get("temperature_2m_max") or []
            tmin = daily.get("temperature_2m_min") or []
            wmax = daily.get("wind_speed_10m_max") or []
            gust = daily.get("wind_gusts_10m_max") or []
            precip = daily.get("precipitation_sum") or []

            max_gust = max((v for v in gust if v is not None), default=0.0)
            total_precip = sum(v for v in precip if v is not None)
            lines.append(f"Peak wind gust (next {horizon}d): {max_gust:.1f} km/h")
            lines.append(
                f"Total precipitation (next {horizon}d): {total_precip:.1f} mm"
            )
            lines.append("")
            lines.append("Daily forecast (t · max/min °C · max wind · gust · precip):")
            for i, t in enumerate(times[:horizon]):
                hi = tmax[i] if i < len(tmax) else None
                lo = tmin[i] if i < len(tmin) else None
                wm = wmax[i] if i < len(wmax) else None
                gu = gust[i] if i < len(gust) else None
                pr = precip[i] if i < len(precip) else None
                lines.append(
                    f"  {t}: {hi}/{lo}°C  wind {wm} km/h  gust {gu} km/h  precip {pr} mm"
                )
            metadata = {
                "mode": "atmosphere",
                "location": location_label,
                "lat": lat,
                "lon": lon,
                "horizon_days": horizon,
                "max_gust_kmh": round(max_gust, 1),
                "total_precip_mm": round(total_precip, 1),
                "source": "https://api.open-meteo.com",
            }

        return ToolResult(content="\n".join(lines), metadata=metadata)
