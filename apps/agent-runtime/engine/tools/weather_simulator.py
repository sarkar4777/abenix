"""Weather impact simulation for any industry: agriculture, logistics, insurance, energy, events."""

from __future__ import annotations

import json
import math
import random
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class WeatherSimulatorTool(BaseTool):
    name = "weather_simulator"
    description = (
        "Simulate weather scenarios and their impact on operations. Generates "
        "solar irradiance, wind speed, temperature, precipitation, and extreme "
        "event probabilities for any location and time period. Use for energy "
        "yield, crop yield, logistics planning, insurance risk, or construction "
        "scheduling."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": (
                    "City/region name or lat/lon pair (e.g. 'Berlin', '52.52,13.405')"
                ),
            },
            "period_months": {
                "type": "integer",
                "description": "Simulation horizon in months (default 12)",
                "default": 12,
            },
            "scenarios": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Which scenarios to simulate. "
                    "Options: base, optimistic, pessimistic, extreme (default: all four)"
                ),
            },
            "parameters": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Weather parameters to include. Options: solar_irradiance, "
                    "wind_speed, temperature, precipitation (default: all four)"
                ),
            },
            "seed": {
                "type": "integer",
                "description": "Random seed for reproducibility (optional)",
            },
        },
        "required": ["location"],
    }

    # Latitude lookup — simple heuristic for well-known locations,
    # otherwise parse "lat,lon" strings.  Falls back to 45N (mid-latitude).
    _LOCATION_LATITUDES: dict[str, float] = {
        "berlin": 52.5,
        "london": 51.5,
        "new york": 40.7,
        "los angeles": 34.1,
        "sydney": -33.9,
        "tokyo": 35.7,
        "mumbai": 19.1,
        "cape town": -33.9,
        "sao paulo": -23.5,
        "dubai": 25.3,
        "singapore": 1.3,
        "paris": 48.9,
        "madrid": 40.4,
        "rome": 41.9,
        "nairobi": -1.3,
        "cairo": 30.0,
        "beijing": 39.9,
        "chicago": 41.9,
        "houston": 29.8,
        "phoenix": 33.4,
        "denver": 39.7,
        "amsterdam": 52.4,
        "stockholm": 59.3,
        "oslo": 59.9,
        "helsinki": 60.2,
        "istanbul": 41.0,
        "buenos aires": -34.6,
        "mexico city": 19.4,
        "toronto": 43.7,
        "vancouver": 49.3,
    }

    # Scenario multipliers applied to weather parameters
    _SCENARIO_MODS: dict[str, dict[str, float]] = {
        "base": {
            "solar_scale": 1.0,
            "wind_scale": 1.0,
            "temp_offset": 0.0,
            "precip_scale": 1.0,
            "extreme_scale": 1.0,
        },
        "optimistic": {
            "solar_scale": 1.12,
            "wind_scale": 1.10,
            "temp_offset": -0.5,
            "precip_scale": 0.90,
            "extreme_scale": 0.6,
        },
        "pessimistic": {
            "solar_scale": 0.88,
            "wind_scale": 0.85,
            "temp_offset": 1.5,
            "precip_scale": 1.25,
            "extreme_scale": 1.5,
        },
        "extreme": {
            "solar_scale": 0.72,
            "wind_scale": 0.65,
            "temp_offset": 3.0,
            "precip_scale": 1.80,
            "extreme_scale": 3.0,
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        location = arguments.get("location", "").strip()
        if not location:
            return ToolResult(content="Error: location is required", is_error=True)

        period_months = max(1, min(arguments.get("period_months", 12), 120))
        scenarios = arguments.get("scenarios") or [
            "base",
            "optimistic",
            "pessimistic",
            "extreme",
        ]
        params = arguments.get("parameters") or [
            "solar_irradiance",
            "wind_speed",
            "temperature",
            "precipitation",
        ]
        seed = arguments.get("seed")

        # Validate scenario names
        valid_scenarios = set(self._SCENARIO_MODS.keys())
        bad = [s for s in scenarios if s not in valid_scenarios]
        if bad:
            return ToolResult(
                content=f"Unknown scenarios: {bad}. Valid: {sorted(valid_scenarios)}",
                is_error=True,
            )

        valid_params = {
            "solar_irradiance",
            "wind_speed",
            "temperature",
            "precipitation",
        }
        bad_p = [p for p in params if p not in valid_params]
        if bad_p:
            return ToolResult(
                content=f"Unknown parameters: {bad_p}. Valid: {sorted(valid_params)}",
                is_error=True,
            )

        if seed is not None:
            random.seed(seed)

        lat = self._resolve_latitude(location)
        hemisphere = "north" if lat >= 0 else "south"

        try:
            result_scenarios = []
            for scenario_name in scenarios:
                mods = self._SCENARIO_MODS[scenario_name]
                scenario_data: dict[str, Any] = {
                    "name": scenario_name,
                    "parameters": {},
                }

                if "solar_irradiance" in params:
                    scenario_data["parameters"]["solar_irradiance"] = self._sim_solar(
                        lat,
                        hemisphere,
                        period_months,
                        mods["solar_scale"],
                    )
                if "wind_speed" in params:
                    scenario_data["parameters"]["wind_speed"] = self._sim_wind(
                        lat,
                        period_months,
                        mods["wind_scale"],
                    )
                if "temperature" in params:
                    scenario_data["parameters"]["temperature"] = self._sim_temperature(
                        lat,
                        hemisphere,
                        period_months,
                        mods["temp_offset"],
                    )
                if "precipitation" in params:
                    scenario_data["parameters"]["precipitation"] = (
                        self._sim_precipitation(
                            lat,
                            period_months,
                            mods["precip_scale"],
                        )
                    )

                scenario_data["extreme_events"] = self._sim_extreme_events(
                    lat,
                    period_months,
                    mods["extreme_scale"],
                )

                result_scenarios.append(scenario_data)

            output = {
                "location": location,
                "latitude": round(lat, 2),
                "hemisphere": hemisphere,
                "period_months": period_months,
                "scenarios": result_scenarios,
            }
            return ToolResult(
                content=json.dumps(output, indent=2),
                metadata={"location": location, "scenarios": scenarios},
            )
        except Exception as e:
            return ToolResult(content=f"Simulation error: {e}", is_error=True)

    # Location resolution
    def _resolve_latitude(self, location: str) -> float:
        low = location.lower().strip()
        if low in self._LOCATION_LATITUDES:
            return self._LOCATION_LATITUDES[low]

        # Try parsing "lat,lon"
        parts = location.replace(" ", "").split(",")
        if len(parts) == 2:
            try:
                return float(parts[0])
            except ValueError:
                pass

        # Fuzzy substring match
        for city, lat in self._LOCATION_LATITUDES.items():
            if city in low or low in city:
                return lat

        return 45.0  # default mid-latitude

    # Solar irradiance simulation (kWh/m^2/day)
    # Seasonal sine wave modulated by latitude + gaussian noise
    def _sim_solar(
        self,
        lat: float,
        hemisphere: str,
        months: int,
        scale: float,
    ) -> dict[str, Any]:
        abs_lat = abs(lat)
        # Peak summer irradiance decreases with latitude
        peak = 7.0 - (abs_lat / 90.0) * 3.5  # ~7 at equator, ~3.5 at poles
        amplitude = (abs_lat / 90.0) * 2.5  # more seasonal swing at high latitudes
        base = peak - amplitude

        monthly: list[float] = []
        for m in range(months):
            month_of_year = m % 12
            # Northern hemisphere peaks in June (month 5), southern in December (month 11)
            if hemisphere == "north":
                phase = (month_of_year - 5) / 12.0 * 2 * math.pi
            else:
                phase = (month_of_year - 11) / 12.0 * 2 * math.pi

            seasonal = base + amplitude * (1 + math.cos(phase)) / 2.0
            noise = random.gauss(0, 0.3)
            value = max(0.5, (seasonal + noise) * scale)
            monthly.append(round(value, 2))

        mean = sum(monthly) / len(monthly)
        sorted_vals = sorted(monthly)
        p10_idx = max(0, int(len(sorted_vals) * 0.1))
        p90_idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.9))

        return {
            "unit": "kWh/m2/day",
            "mean": round(mean, 2),
            "p10": round(sorted_vals[p10_idx], 2),
            "p90": round(sorted_vals[p90_idx], 2),
            "monthly": monthly,
        }

    # Wind speed simulation (m/s) — Weibull distribution
    def _sim_wind(
        self,
        lat: float,
        months: int,
        scale: float,
    ) -> dict[str, Any]:
        abs_lat = abs(lat)
        # Mid-latitudes (~40-60) are windiest
        base_shape = 2.0  # Weibull shape parameter (k)
        base_scale_param = 5.0 + 3.0 * math.exp(-((abs_lat - 50) ** 2) / 800.0)

        monthly: list[float] = []
        for m in range(months):
            month_of_year = m % 12
            # Wind tends to be stronger in winter in most locations
            winter_boost = 1.0 + 0.2 * math.cos(
                (month_of_year - 0) / 12.0 * 2 * math.pi
            )
            effective_scale = base_scale_param * winter_boost * scale

            # Sample from Weibull: use inverse transform
            # Weibull CDF inverse: scale * (-ln(1-U))^(1/k)
            samples = []
            for _ in range(30):
                u = random.random()
                if u >= 1.0:
                    u = 0.999
                w = effective_scale * ((-math.log(1 - u)) ** (1.0 / base_shape))
                samples.append(w)
            avg = sum(samples) / len(samples)
            monthly.append(round(max(0.5, avg), 2))

        mean = sum(monthly) / len(monthly)
        sorted_vals = sorted(monthly)
        p10_idx = max(0, int(len(sorted_vals) * 0.1))
        p90_idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.9))

        return {
            "unit": "m/s",
            "mean": round(mean, 2),
            "p10": round(sorted_vals[p10_idx], 2),
            "p90": round(sorted_vals[p90_idx], 2),
            "weibull_k": base_shape,
            "weibull_scale": round(base_scale_param * scale, 2),
            "monthly": monthly,
        }

    # Temperature simulation (degrees C) — seasonal baseline + noise
    def _sim_temperature(
        self,
        lat: float,
        hemisphere: str,
        months: int,
        temp_offset: float,
    ) -> dict[str, Any]:
        abs_lat = abs(lat)
        # Annual mean temperature decreases with latitude
        annual_mean = 30.0 - (abs_lat / 90.0) * 45.0  # ~30C equator, ~-15C pole
        # Seasonal amplitude increases with latitude
        amplitude = (abs_lat / 90.0) * 20.0

        monthly: list[float] = []
        for m in range(months):
            month_of_year = m % 12
            if hemisphere == "north":
                phase = (month_of_year - 6) / 12.0 * 2 * math.pi  # peak July
            else:
                phase = (month_of_year - 0) / 12.0 * 2 * math.pi  # peak Jan

            seasonal = annual_mean + amplitude * math.cos(phase)
            noise = random.gauss(0, 1.5)
            value = seasonal + noise + temp_offset
            monthly.append(round(value, 1))

        mean = sum(monthly) / len(monthly)
        sorted_vals = sorted(monthly)
        p10_idx = max(0, int(len(sorted_vals) * 0.1))
        p90_idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.9))

        return {
            "unit": "celsius",
            "mean": round(mean, 1),
            "p10": round(sorted_vals[p10_idx], 1),
            "p90": round(sorted_vals[p90_idx], 1),
            "monthly": monthly,
        }

    # Precipitation simulation (mm/month) — gamma distribution
    def _sim_precipitation(
        self,
        lat: float,
        months: int,
        precip_scale: float,
    ) -> dict[str, Any]:
        abs_lat = abs(lat)
        # Tropical regions are wettest; mid-latitude moderate; polar dry
        if abs_lat < 20:
            base_mm = 180.0
        elif abs_lat < 40:
            base_mm = 80.0
        elif abs_lat < 60:
            base_mm = 65.0
        else:
            base_mm = 35.0

        # Gamma distribution parameters: shape (alpha) and rate (beta)
        alpha = 3.0
        beta = alpha / base_mm  # so that mean = alpha / beta = base_mm

        monthly: list[float] = []
        for m in range(months):
            month_of_year = m % 12
            # Mild seasonal variation
            seasonal_factor = 1.0 + 0.3 * math.sin(
                (month_of_year - 3) / 12.0 * 2 * math.pi
            )
            effective_beta = beta / (seasonal_factor * precip_scale)

            # Gamma sampling via Marsaglia-Tsang (simplified: use sum of exponentials
            # for integer shape, then scale for non-integer)
            val = sum(-math.log(max(random.random(), 1e-12)) for _ in range(int(alpha)))
            val /= effective_beta
            monthly.append(round(max(0.0, val), 1))

        mean = sum(monthly) / len(monthly)
        sorted_vals = sorted(monthly)
        p10_idx = max(0, int(len(sorted_vals) * 0.1))
        p90_idx = min(len(sorted_vals) - 1, int(len(sorted_vals) * 0.9))

        return {
            "unit": "mm/month",
            "mean": round(mean, 1),
            "p10": round(sorted_vals[p10_idx], 1),
            "p90": round(sorted_vals[p90_idx], 1),
            "monthly": monthly,
        }

    # Extreme events — Poisson process for storms, heatwaves, frost
    def _sim_extreme_events(
        self,
        lat: float,
        months: int,
        extreme_scale: float,
    ) -> list[dict[str, Any]]:
        abs_lat = abs(lat)
        years = months / 12.0

        events = []

        # Storms — more likely in tropical/coastal latitudes
        storm_annual_rate = 2.0 if abs_lat < 30 else 1.0 if abs_lat < 50 else 0.5
        storm_rate = storm_annual_rate * years * extreme_scale
        storm_count = self._poisson_sample(storm_rate)
        storm_prob = 1 - math.exp(-storm_rate)
        events.append(
            {
                "type": "severe_storm",
                "expected_count": round(storm_count, 1),
                "probability": round(min(storm_prob, 1.0), 3),
                "impact_severity": "high" if abs_lat < 30 else "medium",
                "description": (
                    f"Severe storms (hail, high wind, heavy rain): "
                    f"~{storm_count:.0f} events expected over {months} months"
                ),
            }
        )

        # Heatwaves — higher at low latitude and mid-latitude
        heat_annual_rate = 3.0 if abs_lat < 35 else 1.5 if abs_lat < 50 else 0.5
        heat_rate = heat_annual_rate * years * extreme_scale
        heat_count = self._poisson_sample(heat_rate)
        heat_prob = 1 - math.exp(-heat_rate)
        events.append(
            {
                "type": "heatwave",
                "expected_count": round(heat_count, 1),
                "probability": round(min(heat_prob, 1.0), 3),
                "impact_severity": "high" if abs_lat < 35 else "medium",
                "description": (
                    f"Extended periods of extreme heat (>35C): "
                    f"~{heat_count:.0f} events expected over {months} months"
                ),
            }
        )

        # Frost / cold snaps — higher at high latitude
        frost_annual_rate = 0.2 if abs_lat < 25 else 2.0 if abs_lat < 50 else 5.0
        frost_rate = frost_annual_rate * years * extreme_scale
        frost_count = self._poisson_sample(frost_rate)
        frost_prob = 1 - math.exp(-frost_rate)
        events.append(
            {
                "type": "frost_cold_snap",
                "expected_count": round(frost_count, 1),
                "probability": round(min(frost_prob, 1.0), 3),
                "impact_severity": (
                    "low" if abs_lat < 25 else "medium" if abs_lat < 50 else "high"
                ),
                "description": (
                    f"Frost or cold snap events (<-5C): "
                    f"~{frost_count:.0f} events expected over {months} months"
                ),
            }
        )

        # Drought — moderate everywhere, worse in arid zones
        drought_annual_rate = 0.8 if abs_lat < 35 else 0.4
        drought_rate = drought_annual_rate * years * extreme_scale
        drought_count = self._poisson_sample(drought_rate)
        drought_prob = 1 - math.exp(-drought_rate)
        events.append(
            {
                "type": "drought",
                "expected_count": round(drought_count, 1),
                "probability": round(min(drought_prob, 1.0), 3),
                "impact_severity": (
                    "high" if abs_lat > 20 and abs_lat < 40 else "medium"
                ),
                "description": (
                    f"Prolonged dry spells (>30 days below 10% normal precipitation): "
                    f"~{drought_count:.0f} events expected over {months} months"
                ),
            }
        )

        # Flooding — tropical and coastal
        flood_annual_rate = 1.5 if abs_lat < 25 else 0.7
        flood_rate = flood_annual_rate * years * extreme_scale
        flood_count = self._poisson_sample(flood_rate)
        flood_prob = 1 - math.exp(-flood_rate)
        events.append(
            {
                "type": "flooding",
                "expected_count": round(flood_count, 1),
                "probability": round(min(flood_prob, 1.0), 3),
                "impact_severity": "high" if abs_lat < 25 else "medium",
                "description": (
                    f"Significant flooding events: "
                    f"~{flood_count:.0f} events expected over {months} months"
                ),
            }
        )

        return events

    @staticmethod
    def _poisson_sample(lam: float) -> int:
        """Sample from Poisson distribution using Knuth's algorithm."""
        if lam <= 0:
            return 0
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p <= L:
                return k - 1
