"""Unit conversion for energy, currency, area, volume, and other measurements."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult

CONVERSIONS: dict[str, dict[str, float]] = {
    "energy": {
        "J": 1.0,
        "kJ": 1e3,
        "MJ": 1e6,
        "GJ": 1e9,
        "Wh": 3600.0,
        "kWh": 3.6e6,
        "MWh": 3.6e9,
        "GWh": 3.6e12,
        "TWh": 3.6e15,
        "BTU": 1055.06,
        "therm": 1.055e8,
        "cal": 4.184,
        "kcal": 4184.0,
        "toe": 4.187e10,  # tonne of oil equivalent
        "boe": 6.1178e9,  # barrel of oil equivalent
    },
    "power": {
        "W": 1.0,
        "kW": 1e3,
        "MW": 1e6,
        "GW": 1e9,
        "TW": 1e12,
        "hp": 745.7,
        "BTU/h": 0.29307,
    },
    "length": {
        "m": 1.0,
        "km": 1e3,
        "cm": 0.01,
        "mm": 0.001,
        "mi": 1609.344,
        "yd": 0.9144,
        "ft": 0.3048,
        "in": 0.0254,
        "nm": 1852.0,  # nautical mile
    },
    "area": {
        "m2": 1.0,
        "km2": 1e6,
        "ha": 1e4,
        "acre": 4046.86,
        "ft2": 0.0929,
        "mi2": 2.59e6,
    },
    "volume": {
        "L": 1.0,
        "mL": 0.001,
        "m3": 1000.0,
        "gal_us": 3.78541,
        "gal_uk": 4.54609,
        "bbl": 158.987,  # barrel (oil)
        "ft3": 28.3168,
        "cup": 0.236588,
    },
    "mass": {
        "kg": 1.0,
        "g": 0.001,
        "mg": 1e-6,
        "t": 1000.0,  # metric tonne
        "lb": 0.453592,
        "oz": 0.0283495,
        "ton_us": 907.185,
        "ton_uk": 1016.05,
    },
    "temperature": {},
    "pressure": {
        "Pa": 1.0,
        "kPa": 1e3,
        "MPa": 1e6,
        "bar": 1e5,
        "atm": 101325.0,
        "psi": 6894.76,
        "mmHg": 133.322,
        "inHg": 3386.39,
    },
    "speed": {
        "m/s": 1.0,
        "km/h": 0.277778,
        "mph": 0.44704,
        "knot": 0.514444,
        "ft/s": 0.3048,
    },
    "data": {
        "B": 1.0,
        "KB": 1024.0,
        "MB": 1048576.0,
        "GB": 1073741824.0,
        "TB": 1099511627776.0,
        "PB": 1.126e15,
    },
    "time": {
        "s": 1.0,
        "min": 60.0,
        "h": 3600.0,
        "day": 86400.0,
        "week": 604800.0,
        "month": 2592000.0,
        "year": 31536000.0,
    },
    "emission": {
        "tCO2": 1.0,
        "kgCO2": 0.001,
        "lbCO2": 0.000453592,
        "tCO2e": 1.0,
    },
}


class UnitConverterTool(BaseTool):
    name = "unit_converter"
    description = (
        "Convert between units across multiple categories: energy (kWh, MWh, GWh, BTU, "
        "toe, boe), power (W, kW, MW, GW, hp), length, area (ha, acre), volume (L, bbl, "
        "gal), mass (kg, t, lb), temperature (C, F, K), pressure, speed, data storage, "
        "time, and carbon emissions (tCO2, kgCO2). Particularly useful for energy industry "
        "calculations involving PPAs and renewable energy projects."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "value": {
                "type": "number",
                "description": "The numeric value to convert",
            },
            "from_unit": {
                "type": "string",
                "description": "Source unit (e.g. 'MWh', 'kg', 'acre')",
            },
            "to_unit": {
                "type": "string",
                "description": "Target unit (e.g. 'kWh', 'lb', 'ha')",
            },
            "category": {
                "type": "string",
                "description": "Unit category (auto-detected if omitted)",
            },
        },
        "required": ["value", "from_unit", "to_unit"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        value = arguments.get("value", 0)
        from_unit = arguments.get("from_unit", "")
        to_unit = arguments.get("to_unit", "")
        category = arguments.get("category", "")

        if not from_unit or not to_unit:
            return ToolResult(
                content="Error: from_unit and to_unit are required", is_error=True
            )

        if from_unit in ("C", "F", "K") or to_unit in ("C", "F", "K"):
            return self._convert_temperature(value, from_unit, to_unit)

        if category:
            cat = CONVERSIONS.get(category)
            if not cat:
                return ToolResult(
                    content=f"Unknown category: {category}. Available: {list(CONVERSIONS.keys())}",
                    is_error=True,
                )
            return self._convert(value, from_unit, to_unit, category, cat)

        for cat_name, units in CONVERSIONS.items():
            if cat_name == "temperature":
                continue
            if from_unit in units and to_unit in units:
                return self._convert(value, from_unit, to_unit, cat_name, units)

        return ToolResult(
            content=f"Cannot find conversion path from '{from_unit}' to '{to_unit}'. "
            f"Available categories: {list(CONVERSIONS.keys())}",
            is_error=True,
        )

    def _convert(
        self,
        value: float,
        from_unit: str,
        to_unit: str,
        category: str,
        units: dict[str, float],
    ) -> ToolResult:
        from_factor = units.get(from_unit)
        to_factor = units.get(to_unit)

        if from_factor is None:
            return ToolResult(
                content=f"Unknown unit '{from_unit}' in {category}. Available: {list(units.keys())}",
                is_error=True,
            )
        if to_factor is None:
            return ToolResult(
                content=f"Unknown unit '{to_unit}' in {category}. Available: {list(units.keys())}",
                is_error=True,
            )

        base_value = value * from_factor
        result = base_value / to_factor

        all_conversions = {}
        for unit, factor in units.items():
            if unit != from_unit:
                all_conversions[unit] = round(base_value / factor, 6)

        output = {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": round(result, 6),
            "category": category,
            "expression": f"{value} {from_unit} = {round(result, 6)} {to_unit}",
            "all_conversions": all_conversions,
        }

        return ToolResult(
            content=json.dumps(output, indent=2),
            metadata={"category": category},
        )

    def _convert_temperature(
        self, value: float, from_unit: str, to_unit: str
    ) -> ToolResult:
        if from_unit == to_unit:
            result = value
        elif from_unit == "C" and to_unit == "F":
            result = value * 9 / 5 + 32
        elif from_unit == "C" and to_unit == "K":
            result = value + 273.15
        elif from_unit == "F" and to_unit == "C":
            result = (value - 32) * 5 / 9
        elif from_unit == "F" and to_unit == "K":
            result = (value - 32) * 5 / 9 + 273.15
        elif from_unit == "K" and to_unit == "C":
            result = value - 273.15
        elif from_unit == "K" and to_unit == "F":
            result = (value - 273.15) * 9 / 5 + 32
        else:
            return ToolResult(
                content=f"Unknown temperature conversion: {from_unit} -> {to_unit}",
                is_error=True,
            )

        celsius = (
            value
            if from_unit == "C"
            else ((value - 32) * 5 / 9 if from_unit == "F" else value - 273.15)
        )

        output = {
            "value": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "result": round(result, 4),
            "category": "temperature",
            "expression": f"{value}°{from_unit} = {round(result, 4)}°{to_unit}",
            "all_conversions": {
                "C": round(celsius, 4),
                "F": round(celsius * 9 / 5 + 32, 4),
                "K": round(celsius + 273.15, 4),
            },
        }
        return ToolResult(
            content=json.dumps(output, indent=2), metadata={"category": "temperature"}
        )
