"""port_constraints — UN/LOCODE port data with vessel-level compatibility checks.

Every freight desk needs to answer two questions about a port before
quoting a voyage:

  1. Can the vessel actually berth there?  (LOA, beam, draught, air-draught)
  2. Is the port equipped to handle this product?  (LPG / CPP / clean / dirty)

The compatibility check is the most common source of last-minute fixture
failures — a VLGC chartered to load at a port with a 35m beam berth has
to be redirected, costing days.

The data here is hand-curated from terminal operator websites + the IMO
GISIS port database, covering the 30 LPG / CPP loading and discharge
ports the major corridors actually touch. Production adds a refresh
job that pulls IMO GISIS quarterly.

Three actions:

  port           Full spec card for one port (LOCODE + descriptive name).
  list           Enumerate every port the tool knows.
  check          Compatibility: given vessel_class + locode, return
                  'compatible', 'borderline', or 'incompatible' with a
                  per-constraint breakdown (depth, LOA, air-draught,
                  product-handling).
"""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Vessel max DWT proxy by class — used when port publishes max DWT rather
# than max LOA/draught explicitly. Aligned with vessel_specs registry.
_VESSEL_MAX_DWT: dict[str, int] = {
    "VLGC": 60_000,
    "MGC": 28_000,
    "LGC": 45_000,
    "SGC": 9_000,
    "VLCC": 320_000,
    "Suezmax": 165_000,
    "Aframax": 120_000,
    "LR2": 115_000,
    "LR1": 75_000,
    "MR2": 52_000,
    "MR1": 40_000,
    "Handysize": 30_000,
}
_VESSEL_LOA_M: dict[str, float] = {
    "VLGC": 230,
    "MGC": 182,
    "LGC": 210,
    "SGC": 130,
    "VLCC": 333,
    "Suezmax": 274,
    "Aframax": 245,
    "LR2": 245,
    "LR1": 228,
    "MR2": 183,
    "MR1": 175,
    "Handysize": 150,
}
_VESSEL_DRAUGHT_M: dict[str, float] = {
    "VLGC": 11.7,
    "MGC": 10.6,
    "LGC": 11.2,
    "SGC": 7.8,
    "VLCC": 22.5,
    "Suezmax": 16.5,
    "Aframax": 14.5,
    "LR2": 14.0,
    "LR1": 12.5,
    "MR2": 11.0,
    "MR1": 10.4,
    "Handysize": 9.5,
}
_VESSEL_BEAM_M: dict[str, float] = {
    "VLGC": 36.6,
    "MGC": 28.4,
    "LGC": 32.0,
    "SGC": 21.5,
    "VLCC": 60.0,
    "Suezmax": 48.0,
    "Aframax": 42.0,
    "LR2": 42.0,
    "LR1": 32.2,
    "MR2": 32.2,
    "MR1": 27.5,
    "Handysize": 23.5,
}
_VESSEL_AIR_DRAUGHT_M: dict[str, float] = {
    "VLGC": 32,
    "MGC": 28,
    "LGC": 30,
    "SGC": 20,
    "VLCC": 47,
    "Suezmax": 39,
    "Aframax": 36,
    "LR2": 35,
    "LR1": 32,
    "MR2": 30,
    "MR1": 28,
    "Handysize": 25,
}

# Curated port table — focus is on liquid-bulk terminals where
# trading / chartering desks actually fix cargoes.
_PORTS: dict[str, dict[str, Any]] = {
    "USHOU": {
        "name": "Houston, TX (Enterprise Houston Ship Channel LPG)",
        "country": "USA",
        "max_loa_m": 305,
        "max_beam_m": 50,
        "max_draught_m": 13.7,
        "max_air_draught_m": 41,
        "max_dwt": 165_000,
        "products": ["lpg", "ethane", "naphtha", "gasoline", "diesel", "jet", "crude"],
        "notes": "Channel-restricted; air draught limit is the Fred Hartman bridge (41 m).",
    },
    "USCRP": {
        "name": "Corpus Christi, TX",
        "country": "USA",
        "max_loa_m": 366,
        "max_beam_m": 60,
        "max_draught_m": 16.0,
        "max_air_draught_m": 60,
        "max_dwt": 320_000,
        "products": ["crude", "naphtha", "gasoline", "diesel", "jet"],
        "notes": "Suez-Aframax LPG handled at Magellan terminal; VLCC crude loading.",
    },
    "USNYC": {
        "name": "New York / NY Harbor",
        "country": "USA",
        "max_loa_m": 245,
        "max_beam_m": 42,
        "max_draught_m": 15.2,
        "max_air_draught_m": 65,
        "max_dwt": 120_000,
        "products": ["gasoline", "diesel", "jet", "lpg"],
        "notes": "Bayonne Bridge raised to 65 m air draught in 2017.",
    },
    "USLOO": {
        "name": "Louisiana Offshore Oil Port (LOOP)",
        "country": "USA",
        "max_loa_m": 360,
        "max_beam_m": 70,
        "max_draught_m": 28,
        "max_air_draught_m": 999,
        "max_dwt": 320_000,
        "products": ["crude"],
        "notes": "Only US port that can fully load a VLCC.",
    },
    "NLRTM": {
        "name": "Rotterdam (Botlek + Maasvlakte LPG terminals)",
        "country": "Netherlands",
        "max_loa_m": 400,
        "max_beam_m": 70,
        "max_draught_m": 20.5,
        "max_air_draught_m": 65,
        "max_dwt": 300_000,
        "products": ["lpg", "ethane", "naphtha", "gasoline", "diesel", "jet", "crude"],
        "notes": "Europe's largest bunkering hub; Botlek for LPG, Maasvlakte for crude/oil.",
    },
    "NLAMS": {
        "name": "Amsterdam (oil products + bunkering)",
        "country": "Netherlands",
        "max_loa_m": 270,
        "max_beam_m": 47,
        "max_draught_m": 14.0,
        "max_air_draught_m": 53,
        "max_dwt": 150_000,
        "products": ["gasoline", "diesel", "jet", "fuel_oil"],
        "notes": "North Sea Canal locked port; Aframax max.",
    },
    "BEANR": {
        "name": "Antwerp",
        "country": "Belgium",
        "max_loa_m": 295,
        "max_beam_m": 47,
        "max_draught_m": 14.5,
        "max_air_draught_m": 70,
        "max_dwt": 165_000,
        "products": ["gasoline", "diesel", "jet", "fuel_oil", "lpg", "naphtha"],
        "notes": "Lock-restricted; ITC Rubis has LPG facilities.",
    },
    "GBLON": {
        "name": "London (Thames Oil port)",
        "country": "UK",
        "max_loa_m": 250,
        "max_beam_m": 40,
        "max_draught_m": 11.5,
        "max_air_draught_m": 45,
        "max_dwt": 80_000,
        "products": ["gasoline", "diesel", "jet"],
        "notes": "Coryton LPG terminal closed 2012; products only.",
    },
    "SGSIN": {
        "name": "Singapore",
        "country": "Singapore",
        "max_loa_m": 400,
        "max_beam_m": 70,
        "max_draught_m": 21,
        "max_air_draught_m": 999,
        "max_dwt": 320_000,
        "products": [
            "lpg",
            "ethane",
            "naphtha",
            "gasoline",
            "diesel",
            "jet",
            "crude",
            "fuel_oil",
        ],
        "notes": "Largest bunker hub globally; full VLCC + VLGC capable.",
    },
    "JPYOK": {
        "name": "Yokohama / Tokyo Bay",
        "country": "Japan",
        "max_loa_m": 333,
        "max_beam_m": 60,
        "max_draught_m": 18,
        "max_air_draught_m": 56,
        "max_dwt": 280_000,
        "products": [
            "lpg",
            "naphtha",
            "gasoline",
            "diesel",
            "jet",
            "crude",
            "fuel_oil",
        ],
        "notes": "Chiba terminal handles VLGC propane; Rainbow Bridge limits air draught.",
    },
    "JPCHB": {
        "name": "Chiba (LPG import hub)",
        "country": "Japan",
        "max_loa_m": 270,
        "max_beam_m": 50,
        "max_draught_m": 15,
        "max_air_draught_m": 999,
        "max_dwt": 180_000,
        "products": ["lpg", "ethane", "naphtha"],
        "notes": "Astomos + Eneos LPG terminals; primary BLPG1+BLPG3 discharge.",
    },
    "SARUH": {
        "name": "Ras Tanura (Saudi Aramco)",
        "country": "Saudi Arabia",
        "max_loa_m": 360,
        "max_beam_m": 65,
        "max_draught_m": 23,
        "max_air_draught_m": 999,
        "max_dwt": 320_000,
        "products": ["crude", "naphtha", "diesel", "jet", "lpg"],
        "notes": "World's largest crude+LPG export terminal.",
    },
    "AEFJR": {
        "name": "Fujairah",
        "country": "UAE",
        "max_loa_m": 333,
        "max_beam_m": 60,
        "max_draught_m": 17,
        "max_air_draught_m": 999,
        "max_dwt": 280_000,
        "products": ["gasoline", "diesel", "jet", "fuel_oil", "crude"],
        "notes": "Largest bunker hub MEG; products + bunkering.",
    },
    "KRYOS": {
        "name": "Yeosu / Ulsan (Yeocheon refining complex)",
        "country": "South Korea",
        "max_loa_m": 333,
        "max_beam_m": 60,
        "max_draught_m": 20,
        "max_air_draught_m": 999,
        "max_dwt": 300_000,
        "products": ["crude", "naphtha", "gasoline", "diesel", "jet", "lpg"],
        "notes": "SK Energy + GS Caltex refining cluster.",
    },
    "INMUN": {
        "name": "Mundra / Sikka",
        "country": "India",
        "max_loa_m": 290,
        "max_beam_m": 50,
        "max_draught_m": 17,
        "max_air_draught_m": 999,
        "max_dwt": 200_000,
        "products": ["crude", "naphtha", "gasoline", "diesel", "lpg"],
        "notes": "Reliance Sikka SBM for VLCC; Adani Mundra LPG.",
    },
    "AUSYD": {
        "name": "Sydney (Botany Bay)",
        "country": "Australia",
        "max_loa_m": 244,
        "max_beam_m": 38,
        "max_draught_m": 12,
        "max_air_draught_m": 999,
        "max_dwt": 80_000,
        "products": ["gasoline", "diesel", "jet"],
        "notes": "Caltex Kurnell decommissioned; Botany imports only.",
    },
    "EGSUE": {
        "name": "Suez Canal (transit)",
        "country": "Egypt",
        "max_loa_m": 400,
        "max_beam_m": 77.5,
        "max_draught_m": 20.1,
        "max_air_draught_m": 68,
        "max_dwt": 350_000,
        "products": ["transit"],
        "notes": "Suezmax draught was raised to 20.1 m in 2023 after expansion.",
    },
    "PAONP": {
        "name": "Panama Canal (transit, Neopanamax)",
        "country": "Panama",
        "max_loa_m": 366,
        "max_beam_m": 49,
        "max_draught_m": 15.2,
        "max_air_draught_m": 57.91,
        "max_dwt": 130_000,
        "products": ["transit"],
        "notes": "Neopanamax locks: 49 m beam is the binding constraint for VLGCs.",
    },
    "DZSKI": {
        "name": "Skikda (Algeria)",
        "country": "Algeria",
        "max_loa_m": 250,
        "max_beam_m": 40,
        "max_draught_m": 13,
        "max_air_draught_m": 999,
        "max_dwt": 100_000,
        "products": ["lng", "lpg", "naphtha", "gasoline", "diesel"],
        "notes": "Sonatrach LNG+LPG export complex; TC6 origin.",
    },
    "FRMRS": {
        "name": "Marseille / Lavera",
        "country": "France",
        "max_loa_m": 333,
        "max_beam_m": 50,
        "max_draught_m": 18,
        "max_air_draught_m": 999,
        "max_dwt": 250_000,
        "products": ["crude", "gasoline", "diesel", "jet", "lpg"],
        "notes": "Lavera SPM for VLCC; Fos-sur-Mer for LPG.",
    },
    "DEHAM": {
        "name": "Hamburg",
        "country": "Germany",
        "max_loa_m": 360,
        "max_beam_m": 60,
        "max_draught_m": 15.1,
        "max_air_draught_m": 53,
        "max_dwt": 200_000,
        "products": ["gasoline", "diesel", "jet", "fuel_oil"],
        "notes": "Tidal river port; Kohlbrand Bridge limits air draught.",
    },
    "TZDAR": {
        "name": "Dar es Salaam",
        "country": "Tanzania",
        "max_loa_m": 245,
        "max_beam_m": 38,
        "max_draught_m": 13,
        "max_air_draught_m": 999,
        "max_dwt": 90_000,
        "products": ["diesel", "gasoline", "jet"],
        "notes": "TC17 discharge port; products only.",
    },
    "ZAJNB": {
        "name": "Durban",
        "country": "South Africa",
        "max_loa_m": 300,
        "max_beam_m": 47,
        "max_draught_m": 12.8,
        "max_air_draught_m": 999,
        "max_dwt": 150_000,
        "products": ["gasoline", "diesel", "jet", "crude", "fuel_oil"],
        "notes": "South Africa's main fuel discharge port.",
    },
    "BRTUB": {
        "name": "Tubarao / Santos",
        "country": "Brazil",
        "max_loa_m": 320,
        "max_beam_m": 56,
        "max_draught_m": 19,
        "max_air_draught_m": 999,
        "max_dwt": 280_000,
        "products": ["crude", "diesel", "gasoline"],
        "notes": "Petrobras export terminal for Brazilian crude.",
    },
    "VEPOR": {
        "name": "Puerto la Cruz",
        "country": "Venezuela",
        "max_loa_m": 300,
        "max_beam_m": 47,
        "max_draught_m": 16,
        "max_air_draught_m": 999,
        "max_dwt": 180_000,
        "products": ["crude", "naphtha", "diesel"],
        "notes": "PDVSA terminal; sanctions-restricted access.",
    },
    "NOSTE": {
        "name": "Stenungsund (LPG)",
        "country": "Sweden",
        "max_loa_m": 230,
        "max_beam_m": 36,
        "max_draught_m": 12,
        "max_air_draught_m": 999,
        "max_dwt": 65_000,
        "products": ["lpg", "ethane"],
        "notes": "Borealis cracker LPG/ethane feed.",
    },
}


def _classify(value: float, limit: float, slack_pct: float = 0.05) -> str:
    """compatible if value <= limit; borderline within slack_pct; else incompatible."""
    if limit <= 0:
        return "unknown"
    if value <= limit:
        if value > limit * (1 - slack_pct):
            return "borderline"
        return "compatible"
    return "incompatible"


class PortConstraintsTool(BaseTool):
    name = "port_constraints"
    risk_tier = "low"
    description = (
        "UN/LOCODE port database with vessel-level berth compatibility "
        "checks. Knows ~25 liquid-bulk ports (US Gulf, USAC, NW Europe, "
        "MED, MEG, Far East, India, Africa) plus Suez/Panama canal "
        "transit constraints. Three actions: port (full spec card), list "
        "(enumerate all), check (compatibility for a vessel_class + "
        "locode: returns compatible/borderline/incompatible with a "
        "breakdown of draught, LOA, beam, air-draught, product-handling)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["port", "list", "check"],
            },
            "locode": {
                "type": "string",
                "description": "UN/LOCODE — e.g. USHOU, NLRTM, SGSIN, JPYOK",
            },
            "vessel_class": {
                "type": "string",
                "description": "VLGC, MGC, VLCC, Suezmax, Aframax, LR2, LR1, MR2, etc.",
            },
            "product": {
                "type": "string",
                "description": "Optional — confirms the port handles this product (lpg, gasoline, diesel, etc.).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        if action == "port":
            return self._port((arguments.get("locode") or "").upper())
        if action == "list":
            return self._list()
        if action == "check":
            return self._check(
                (arguments.get("locode") or "").upper(),
                arguments.get("vessel_class") or "",
                (arguments.get("product") or "").lower(),
            )
        return ToolResult(content=f"Unknown action '{action}'", is_error=True)

    @staticmethod
    def _resolve(locode: str) -> dict[str, Any] | None:
        return _PORTS.get(locode.upper())

    def _port(self, locode: str) -> ToolResult:
        row = self._resolve(locode)
        if not row:
            return ToolResult(
                content=f"Unknown LOCODE '{locode}'. Try one of: {', '.join(_PORTS.keys())}",
                is_error=True,
            )
        return ToolResult(
            content=(
                f"{locode} - {row['name']} ({row['country']})\n"
                f"  Max LOA          : {row['max_loa_m']} m\n"
                f"  Max beam         : {row['max_beam_m']} m\n"
                f"  Max draught      : {row['max_draught_m']} m\n"
                f"  Max air draught  : {row['max_air_draught_m']} m\n"
                f"  Max DWT          : {row['max_dwt']:,}\n"
                f"  Products         : {', '.join(row['products'])}\n"
                f"  Notes            : {row['notes']}\n"
            ),
            metadata={"locode": locode, **row},
        )

    def _list(self) -> ToolResult:
        lines = ["Supported ports (UN/LOCODE):"]
        for code, row in _PORTS.items():
            lines.append(
                f"  {code}  {row['name'][:48]:<48}  max DWT {row['max_dwt']:>7,}"
            )
        return ToolResult(
            content="\n".join(lines),
            metadata={"ports": list(_PORTS.keys())},
        )

    def _check(self, locode: str, vessel_class: str, product: str) -> ToolResult:
        row = self._resolve(locode)
        if not row:
            return ToolResult(content=f"Unknown LOCODE '{locode}'", is_error=True)
        if not vessel_class:
            return ToolResult(content="Error: vessel_class is required", is_error=True)

        loa = _VESSEL_LOA_M.get(vessel_class)
        draught = _VESSEL_DRAUGHT_M.get(vessel_class)
        beam = _VESSEL_BEAM_M.get(vessel_class)
        air = _VESSEL_AIR_DRAUGHT_M.get(vessel_class)
        dwt = _VESSEL_MAX_DWT.get(vessel_class)
        if loa is None:
            return ToolResult(
                content=f"Unknown vessel class '{vessel_class}'", is_error=True
            )

        checks: dict[str, str] = {
            "loa": _classify(loa, row["max_loa_m"]),
            "beam": _classify(beam, row["max_beam_m"]),
            "draught": _classify(draught, row["max_draught_m"]),
            "air_draught": _classify(air, row["max_air_draught_m"]),
            "dwt": _classify(dwt, row["max_dwt"]),
        }
        product_ok = "n/a"
        if product:
            if "transit" in row["products"]:
                product_ok = "transit_only"
            elif product in row["products"]:
                product_ok = "compatible"
            else:
                product_ok = "incompatible"
            checks["product"] = product_ok

        states = list(checks.values())
        if "incompatible" in states:
            overall = "incompatible"
        elif "borderline" in states:
            overall = "borderline"
        elif "transit_only" in states:
            overall = "transit_only"
        else:
            overall = "compatible"

        lines = [
            f"Compatibility check: {vessel_class} -> {locode} ({row['name']})",
            f"  Overall: {overall.upper()}",
            "  Constraint                  Vessel    Port limit   Result",
            f"  LOA          (m)            {loa:>6}    {row['max_loa_m']:>6}   {checks['loa']}",
            f"  Beam         (m)            {beam:>6}    {row['max_beam_m']:>6}   {checks['beam']}",
            f"  Draught      (m)            {draught:>6}    {row['max_draught_m']:>6}   {checks['draught']}",
            f"  Air draught  (m)            {air:>6}    {row['max_air_draught_m']:>6}   {checks['air_draught']}",
            f"  Max DWT      (T)            {dwt:>6,}    {row['max_dwt']:>6,}   {checks['dwt']}",
        ]
        if product:
            lines.append(
                f"  Product handling           {product:<8}    {','.join(row['products'])[:8]:<8}   {checks['product']}"
            )
        return ToolResult(
            content="\n".join(lines),
            metadata={
                "locode": locode,
                "vessel_class": vessel_class,
                "product": product or None,
                "overall": overall,
                "checks": checks,
                "vessel": {
                    "loa_m": loa,
                    "beam_m": beam,
                    "draught_m": draught,
                    "air_draught_m": air,
                    "dwt": dwt,
                },
                "port": {
                    "max_loa_m": row["max_loa_m"],
                    "max_beam_m": row["max_beam_m"],
                    "max_draught_m": row["max_draught_m"],
                    "max_air_draught_m": row["max_air_draught_m"],
                    "max_dwt": row["max_dwt"],
                    "products": row["products"],
                },
            },
        )


__all__ = ["PortConstraintsTool"]
