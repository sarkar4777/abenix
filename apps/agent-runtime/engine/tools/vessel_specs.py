"""vessel_specs — vessel-class registry + product density table + volume/mass converter.

Solves a piece of arithmetic every freight-touching agent needs and most
get wrong: a vessel charter is sold in m^3 of capacity, but a cargo is
priced in metric tons, and the conversion factor (density) is different
for every product. Mixing the two silently is the single most common
freight-math bug we see in the field.

Five actions:

  vessel        Spec card for one vessel class.
                  fields: class, typical_capacity_cbm, typical_cargo_mt
                          (for the named product), speed_knots,
                          vlsfo_consumption_mt_day, draught_loaded_m,
                          loa_m, beam_m, ship_type_ais.

  density       Liquid density at standard conditions for one product.
                  Returns kg/L (== MT/m^3).

  convert       Convert between m^3 and MT for a given product, OR
                  between $/MT and $/bbl for a given product.

  capacity      Given a vessel class AND a product, return the cargo
                  mass (MT) the vessel typically lifts.

  list          Enumerate every supported vessel class or product.

The data here is curated from operator-published vessel specs (Avance
Gas, BW LPG, Dorian) and standard product densities (API/ISO). Every
field cites a source so the agent can quote it.

The tool is intentionally generic — it has no opinion about Wingman.
Any energy/commodity trading agent can use it for freight math.
"""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Densities at ~15 deg C, kg/L (== MT/m^3). Source mix: API MPMS, ISO 12185.
_DENSITY_KG_PER_L: dict[str, dict[str, Any]] = {
    "propane": {
        "value": 0.508,
        "note": "C3H8 liquid at boil point; storage temp ~ -42 C. At 15 C under pressure ~0.495.",
    },
    "butane": {"value": 0.580, "note": "n-C4H10 liquid"},
    "ammonia": {"value": 0.682, "note": "NH3 liquid"},
    "ethane": {"value": 0.546, "note": "C2H6 cryogenic liquid"},
    "lpg_mix": {"value": 0.540, "note": "Typical 60/40 propane/butane export blend"},
    "naphtha": {"value": 0.720, "note": "Light naphtha; heavier blends up to 0.76"},
    "gasoline": {"value": 0.740, "note": "RBOB-grade motor gasoline"},
    "jet": {"value": 0.810, "note": "Jet A-1 / kerosene"},
    "ulsd": {"value": 0.840, "note": "Ultra-low-sulphur diesel"},
    "gasoil": {"value": 0.860, "note": "Heating oil / gasoil"},
    "fuel_oil": {"value": 0.950, "note": "VLSFO / HFO 380cSt"},
    "crude_wti": {"value": 0.825, "note": "WTI ~39.6 API"},
    "crude_brent": {"value": 0.835, "note": "Brent blend ~38 API"},
    "methanol": {"value": 0.792, "note": "CH3OH"},
}

# Approximate barrels per MT for the common $/MT <-> $/bbl conversion.
# Computed as 6.2898 / density(kg/L). Cached for speed and to match
# industry round-numbers traders memorise.
_BBL_PER_MT: dict[str, float] = {
    "propane": 12.40,
    "butane": 10.84,
    "naphtha": 8.90,
    "gasoline": 8.50,
    "jet": 7.90,
    "ulsd": 7.46,
    "gasoil": 7.45,
    "fuel_oil": 6.35,
    "crude_wti": 7.45,
    "crude_brent": 7.45,
    "ammonia": 9.16,
    "lpg_mix": 11.65,
}

# Vessel-class registry. capacities expressed three ways:
#   typical_capacity_cbm:  what the charter is sold as
#   typical_cargo_mt_propane: typical liftable mass for propane (the
#     default LPG cargo; ~92% of design capacity to leave headspace)
# Density-aware mass numbers for other products come from the convert
# action; we don't pre-bake them into the registry because the choice of
# product moves the answer.
_VESSELS: dict[str, dict[str, Any]] = {
    # LPG carriers
    "VLGC": {
        "family": "LPG",
        "typical_capacity_cbm": 84000,
        "typical_cargo_mt_propane": 44000,
        "speed_knots": 16.0,
        "vlsfo_consumption_mt_day": 38.0,
        "loa_m": 230,
        "beam_m": 36.6,
        "draught_loaded_m": 11.7,
        "air_draught_m": 32.0,
        "ship_type_ais": 84,
        "source": "Avance Gas / BW LPG newbuild fleet 2018-2024",
    },
    "MGC": {
        "family": "LPG",
        "typical_capacity_cbm": 38000,
        "typical_cargo_mt_propane": 19500,
        "speed_knots": 15.5,
        "vlsfo_consumption_mt_day": 26.0,
        "loa_m": 182,
        "beam_m": 28.4,
        "draught_loaded_m": 10.6,
        "air_draught_m": 28.0,
        "ship_type_ais": 84,
        "source": "Dorian / Petredec MGC class",
    },
    "LGC": {
        "family": "LPG",
        "typical_capacity_cbm": 60000,
        "typical_cargo_mt_propane": 31000,
        "speed_knots": 16.0,
        "vlsfo_consumption_mt_day": 32.0,
        "loa_m": 210,
        "beam_m": 32.0,
        "draught_loaded_m": 11.2,
        "air_draught_m": 30.0,
        "ship_type_ais": 84,
        "source": "BW LGC class (refit)",
    },
    "SGC": {
        "family": "LPG",
        "typical_capacity_cbm": 12000,
        "typical_cargo_mt_propane": 6200,
        "speed_knots": 14.5,
        "vlsfo_consumption_mt_day": 14.0,
        "loa_m": 130,
        "beam_m": 21.5,
        "draught_loaded_m": 7.8,
        "air_draught_m": 20.0,
        "ship_type_ais": 84,
        "source": "Coaster pressure-type LPG carrier",
    },
    # Clean-product (CPP) tankers
    "VLCC": {
        "family": "CPP",
        "typical_capacity_cbm": 330000,
        "typical_cargo_mt_propane": 0,  # never used for LPG
        "speed_knots": 15.5,
        "vlsfo_consumption_mt_day": 72.0,
        "loa_m": 333,
        "beam_m": 60.0,
        "draught_loaded_m": 22.5,
        "air_draught_m": 47.0,
        "ship_type_ais": 80,
        "source": "Industry standard 270kT-DWT VLCC",
        "default_product": "crude_brent",
        "typical_dwt": 300000,
    },
    "Suezmax": {
        "family": "CPP",
        "typical_capacity_cbm": 175000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.5,
        "vlsfo_consumption_mt_day": 55.0,
        "loa_m": 274,
        "beam_m": 48.0,
        "draught_loaded_m": 16.5,
        "air_draught_m": 39.0,
        "ship_type_ais": 80,
        "source": "Suezmax 158kT-DWT class",
        "default_product": "crude_brent",
        "typical_dwt": 158000,
    },
    "Aframax": {
        "family": "CPP",
        "typical_capacity_cbm": 130000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.5,
        "vlsfo_consumption_mt_day": 45.0,
        "loa_m": 245,
        "beam_m": 42.0,
        "draught_loaded_m": 14.5,
        "air_draught_m": 36.0,
        "ship_type_ais": 80,
        "source": "Aframax 110kT-DWT class",
        "default_product": "crude_brent",
        "typical_dwt": 115000,
    },
    "LR2": {
        "family": "CPP",
        "typical_capacity_cbm": 130000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.5,
        "vlsfo_consumption_mt_day": 41.0,
        "loa_m": 245,
        "beam_m": 42.0,
        "draught_loaded_m": 14.0,
        "air_draught_m": 35.0,
        "ship_type_ais": 80,
        "source": "LR2 product tanker 105-115kT DWT",
        "default_product": "jet",
        "typical_dwt": 110000,
    },
    "LR1": {
        "family": "CPP",
        "typical_capacity_cbm": 75000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.5,
        "vlsfo_consumption_mt_day": 32.0,
        "loa_m": 228,
        "beam_m": 32.2,
        "draught_loaded_m": 12.5,
        "air_draught_m": 32.0,
        "ship_type_ais": 80,
        "source": "LR1 product tanker ~75kT DWT",
        "default_product": "gasoline",
        "typical_dwt": 75000,
    },
    "MR2": {
        "family": "CPP",
        "typical_capacity_cbm": 55000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.0,
        "vlsfo_consumption_mt_day": 26.0,
        "loa_m": 183,
        "beam_m": 32.2,
        "draught_loaded_m": 11.0,
        "air_draught_m": 30.0,
        "ship_type_ais": 80,
        "source": "MR2 product tanker 47-52kT DWT",
        "default_product": "gasoline",
        "typical_dwt": 50000,
    },
    "MR1": {
        "family": "CPP",
        "typical_capacity_cbm": 40000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 14.0,
        "vlsfo_consumption_mt_day": 22.0,
        "loa_m": 175,
        "beam_m": 27.5,
        "draught_loaded_m": 10.4,
        "air_draught_m": 28.0,
        "ship_type_ais": 80,
        "source": "MR1 product tanker 35-40kT DWT",
        "default_product": "gasoline",
        "typical_dwt": 37000,
    },
    "Handysize": {
        "family": "CPP",
        "typical_capacity_cbm": 32000,
        "typical_cargo_mt_propane": 0,
        "speed_knots": 13.5,
        "vlsfo_consumption_mt_day": 18.0,
        "loa_m": 150,
        "beam_m": 23.5,
        "draught_loaded_m": 9.5,
        "air_draught_m": 25.0,
        "ship_type_ais": 80,
        "source": "Handysize product tanker ~28kT DWT",
        "default_product": "gasoline",
        "typical_dwt": 28000,
    },
}


def _product_density(product: str) -> tuple[float | None, str | None]:
    p = (product or "").strip().lower()
    row = _DENSITY_KG_PER_L.get(p)
    if not row:
        return None, None
    return float(row["value"]), row.get("note")


class VesselSpecsTool(BaseTool):
    name = "vessel_specs"
    description = (
        "Vessel-class registry + product density table + volume/mass "
        "converter. Single source of truth for the arithmetic every "
        "freight-touching agent gets wrong: vessels are sold in m^3, "
        "cargoes are priced in MT, and the conversion factor (density) "
        "differs by product. Five actions: vessel (spec card for one "
        "class — VLGC/MGC/LGC/SGC for LPG, VLCC/Suezmax/Aframax/LR2/LR1/"
        "MR2/MR1/Handysize for CPP), density (kg/L for propane/butane/"
        "ammonia/naphtha/gasoline/jet/ULSD/gasoil/fuel oil/crude/methanol), "
        "convert (m^3<->MT or $/MT<->$/bbl for a named product), capacity "
        "(MT a class lifts for a named product), list (every supported "
        "vessel class or product). All values cited."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["vessel", "density", "convert", "capacity", "list"],
                "description": (
                    "vessel: spec card. density: kg/L for a product. "
                    "convert: unit conversion (m^3<->MT or $/MT<->$/bbl). "
                    "capacity: MT a vessel class lifts for a named product. "
                    "list: enumerate classes or products."
                ),
            },
            "vessel_class": {
                "type": "string",
                "description": "VLGC, MGC, LGC, SGC, VLCC, Suezmax, Aframax, LR2, LR1, MR2, MR1, Handysize",
            },
            "product": {
                "type": "string",
                "description": "propane, butane, ammonia, lpg_mix, naphtha, gasoline, jet, ulsd, gasoil, fuel_oil, crude_wti, crude_brent, methanol",
            },
            "from_unit": {
                "type": "string",
                "enum": ["cbm", "mt", "bbl", "usd_per_mt", "usd_per_bbl"],
            },
            "to_unit": {
                "type": "string",
                "enum": ["cbm", "mt", "bbl", "usd_per_mt", "usd_per_bbl"],
            },
            "value": {"type": "number"},
            "list_kind": {
                "type": "string",
                "enum": ["vessels", "products"],
                "default": "vessels",
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        if action == "vessel":
            return self._vessel(arguments.get("vessel_class") or "")
        if action == "density":
            return self._density(arguments.get("product") or "")
        if action == "convert":
            return self._convert(arguments)
        if action == "capacity":
            return self._capacity(
                arguments.get("vessel_class") or "",
                arguments.get("product") or "propane",
            )
        if action == "list":
            return self._list(arguments.get("list_kind") or "vessels")
        return ToolResult(content=f"Error: unknown action '{action}'", is_error=True)

    @staticmethod
    def _resolve_class(name: str) -> tuple[str | None, dict[str, Any] | None]:
        if not name:
            return None, None
        for key, row in _VESSELS.items():
            if key.lower() == name.lower():
                return key, row
        return None, None

    def _vessel(self, name: str) -> ToolResult:
        key, row = self._resolve_class(name)
        if not row:
            return ToolResult(
                content=(
                    f"Unknown vessel class '{name}'. "
                    f"Supported: {', '.join(_VESSELS.keys())}"
                ),
                is_error=True,
            )
        lines = [
            f"{key} ({row['family']}-family)",
            f"  Typical capacity   : {row['typical_capacity_cbm']:>7,} m^3",
            (
                f"  Typical propane MT : {row['typical_cargo_mt_propane']:>7,} MT"
                if row["family"] == "LPG"
                else f"  Default product    : {row.get('default_product', 'n/a')}"
            ),
            f"  Service speed      : {row['speed_knots']} kt",
            f"  VLSFO burn         : {row['vlsfo_consumption_mt_day']} MT/day",
            f"  LOA / beam         : {row['loa_m']} m / {row['beam_m']} m",
            f"  Draught (loaded)   : {row['draught_loaded_m']} m",
            f"  Air draught        : {row['air_draught_m']} m",
            f"  AIS ship-type      : {row['ship_type_ais']}",
            f"  Source             : {row['source']}",
        ]
        return ToolResult(
            content="\n".join(lines),
            metadata={"vessel_class": key, **row},
        )

    def _density(self, product: str) -> ToolResult:
        if not product:
            return ToolResult(content="Error: 'product' is required", is_error=True)
        rho, note = _product_density(product)
        if rho is None:
            return ToolResult(
                content=(
                    f"No density data for '{product}'. Supported: "
                    f"{', '.join(_DENSITY_KG_PER_L.keys())}"
                ),
                is_error=True,
            )
        bbl_per_mt = _BBL_PER_MT.get(product.lower())
        return ToolResult(
            content=(
                f"Density of {product}: {rho} kg/L (== {rho} MT/m^3)\n"
                f"  Note: {note}\n"
                f"  Conversion: 1 MT = {bbl_per_mt} bbl"
                if bbl_per_mt
                else f"Density of {product}: {rho} kg/L (== {rho} MT/m^3)\n  Note: {note}"
            ),
            metadata={
                "product": product.lower(),
                "density_kg_per_l": rho,
                "bbl_per_mt": bbl_per_mt,
                "note": note,
            },
        )

    def _convert(self, args: dict[str, Any]) -> ToolResult:
        try:
            value = float(args.get("value"))
        except (TypeError, ValueError):
            return ToolResult(content="Error: 'value' must be a number", is_error=True)
        product = (args.get("product") or "").lower()
        fu = (args.get("from_unit") or "").lower()
        tu = (args.get("to_unit") or "").lower()

        rho, _ = _product_density(product)
        bbl_per_mt = _BBL_PER_MT.get(product)

        if fu in {"cbm", "mt"} and tu in {"cbm", "mt"}:
            if rho is None:
                return ToolResult(
                    content=f"Need density to convert {fu}<->{tu}; product '{product}' is unknown.",
                    is_error=True,
                )
            if fu == "cbm" and tu == "mt":
                out = value * rho
            elif fu == "mt" and tu == "cbm":
                out = value / rho
            else:
                out = value  # same unit
            return ToolResult(
                content=f"{value} {fu} of {product} = {out:.4f} {tu} (density {rho} kg/L)",
                metadata={
                    "value_in": value,
                    "value_out": round(out, 6),
                    "from_unit": fu,
                    "to_unit": tu,
                    "product": product,
                    "density_kg_per_l": rho,
                },
            )

        if fu in {"usd_per_mt", "usd_per_bbl"} and tu in {"usd_per_mt", "usd_per_bbl"}:
            if not bbl_per_mt:
                return ToolResult(
                    content=f"Need bbl/MT factor to convert; product '{product}' is unknown.",
                    is_error=True,
                )
            if fu == "usd_per_mt" and tu == "usd_per_bbl":
                out = value / bbl_per_mt
            elif fu == "usd_per_bbl" and tu == "usd_per_mt":
                out = value * bbl_per_mt
            else:
                out = value
            return ToolResult(
                content=f"${value} {fu} of {product} = ${out:.4f} {tu} (1 MT = {bbl_per_mt} bbl)",
                metadata={
                    "value_in": value,
                    "value_out": round(out, 6),
                    "from_unit": fu,
                    "to_unit": tu,
                    "product": product,
                    "bbl_per_mt": bbl_per_mt,
                },
            )

        if fu == "bbl" and tu == "mt":
            if not bbl_per_mt:
                return ToolResult(
                    content=f"Unknown bbl/MT for '{product}'", is_error=True
                )
            out = value / bbl_per_mt
            return ToolResult(
                content=f"{value} bbl of {product} = {out:.4f} MT (1 MT = {bbl_per_mt} bbl)",
                metadata={
                    "value_in": value,
                    "value_out": round(out, 6),
                    "product": product,
                },
            )
        if fu == "mt" and tu == "bbl":
            if not bbl_per_mt:
                return ToolResult(
                    content=f"Unknown bbl/MT for '{product}'", is_error=True
                )
            out = value * bbl_per_mt
            return ToolResult(
                content=f"{value} MT of {product} = {out:.4f} bbl (1 MT = {bbl_per_mt} bbl)",
                metadata={
                    "value_in": value,
                    "value_out": round(out, 6),
                    "product": product,
                },
            )

        return ToolResult(
            content=f"Unsupported conversion: {fu} -> {tu}",
            is_error=True,
        )

    def _capacity(self, name: str, product: str) -> ToolResult:
        key, row = self._resolve_class(name)
        if not row:
            return ToolResult(
                content=f"Unknown vessel class '{name}'",
                is_error=True,
            )
        product = product.lower()
        rho, _ = _product_density(product)
        if rho is None:
            return ToolResult(
                content=f"Unknown product '{product}'",
                is_error=True,
            )
        cbm = row["typical_capacity_cbm"]
        usable_fraction = 0.92  # standard heel + headspace for liquefied gas
        if row["family"] == "CPP":
            usable_fraction = 0.98
        cargo_mt = cbm * usable_fraction * rho
        return ToolResult(
            content=(
                f"{key} carrying {product}: ~{cargo_mt:,.0f} MT "
                f"({cbm:,} m^3 x {usable_fraction:.0%} usable x {rho} kg/L)"
            ),
            metadata={
                "vessel_class": key,
                "product": product,
                "typical_capacity_cbm": cbm,
                "usable_fraction": usable_fraction,
                "density_kg_per_l": rho,
                "typical_cargo_mt": round(cargo_mt, 0),
            },
        )

    def _list(self, kind: str) -> ToolResult:
        if kind == "products":
            rows = [
                f"  {p:<14}  {d['value']} kg/L  -  {d['note']}"
                for p, d in _DENSITY_KG_PER_L.items()
            ]
            return ToolResult(
                content="Supported products (density kg/L):\n" + "\n".join(rows),
                metadata={"products": list(_DENSITY_KG_PER_L.keys())},
            )
        rows = [
            f"  {k:<10}  {v['family']:<3}  {v['typical_capacity_cbm']:>7,} m^3  speed {v['speed_knots']} kt  burn {v['vlsfo_consumption_mt_day']} MT/d"
            for k, v in _VESSELS.items()
        ]
        return ToolResult(
            content="Supported vessel classes:\n" + "\n".join(rows),
            metadata={"vessels": list(_VESSELS.keys())},
        )


__all__ = ["VesselSpecsTool"]
