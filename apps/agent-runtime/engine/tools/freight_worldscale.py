"""freight_worldscale — Worldscale freight calculator for clean-products tankers.

Worldscale is the industry standard for quoting tanker freight on clean
and dirty products. The flat-rate per route (USD/MT) is published yearly
by Worldscale Association in WS100 nominal terms. A live quote of, say,
WS180 on Worldscale TC2 (Rotterdam -> NY Harbour, 37kt cargo) means the
broker is paying 180% of the published 2026 flat rate.

The standard formula every CPP desk uses:

    freight_usd_per_mt = ws_points / 100.0 * ws_flat_rate_usd_per_mt

If the cargo is sold in cubic metres (chartered MR2 = 55,000 cbm), we
convert via product density:

    cargo_mt = cargo_cbm * usable_fraction * density_kg_per_l

Voyage cost in dollars:

    total_voyage_usd = freight_usd_per_mt * cargo_mt

The Worldscale flat-rate table is updated by Worldscale Association on
1-Jan annually. We keep the WS2025 levels for the main TC routes here as
a reasonable approximation; production deployments should swap in the
official flat-rate API or a quarterly broker assessment.
"""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Worldscale 2025 flat rate ($/MT, WS100 nominal) for the major TC routes.
# Source: Worldscale Association 2025 schedule (representative levels;
# the exact values revise every Jan 1).
_WS_FLAT_RATE_USD_MT: dict[str, dict[str, Any]] = {
    "TC1": {
        "origin": "Ras Tanura",
        "destination": "Yokohama",
        "cargo_class": "LR2",
        "cargo_mt": 75_000,
        "flat_rate_usd_mt": 17.45,
        "product": "naphtha",
        "label": "MEG -> Japan naphtha (LR2)",
    },
    "TC2": {
        "origin": "Rotterdam",
        "destination": "New York",
        "cargo_class": "MR2",
        "cargo_mt": 37_000,
        "flat_rate_usd_mt": 18.65,
        "product": "gasoline",
        "label": "Cont -> US Atlantic gasoline (MR2)",
    },
    "TC5": {
        "origin": "Ras Tanura",
        "destination": "Yokohama",
        "cargo_class": "LR1",
        "cargo_mt": 55_000,
        "flat_rate_usd_mt": 18.00,
        "product": "naphtha",
        "label": "MEG -> Japan naphtha (LR1)",
    },
    "TC6": {
        "origin": "Skikda",
        "destination": "Lavera",
        "cargo_class": "MR2",
        "cargo_mt": 30_000,
        "flat_rate_usd_mt": 8.40,
        "product": "gasoline",
        "label": "Algeria -> France gasoline (MR2)",
    },
    "TC7": {
        "origin": "Singapore",
        "destination": "Sydney",
        "cargo_class": "MR2",
        "cargo_mt": 30_000,
        "flat_rate_usd_mt": 22.15,
        "product": "gasoline",
        "label": "SG -> East Australia gasoline (MR2)",
    },
    "TC14": {
        "origin": "New York",
        "destination": "Rotterdam",
        "cargo_class": "MR2",
        "cargo_mt": 38_000,
        "flat_rate_usd_mt": 17.10,
        "product": "gasoline",
        "label": "US Atlantic -> Cont gasoline (MR2)",
    },
    "TC17": {
        "origin": "Jubail",
        "destination": "Dar es Salaam",
        "cargo_class": "MR2",
        "cargo_mt": 35_000,
        "flat_rate_usd_mt": 25.40,
        "product": "diesel",
        "label": "MEG -> East Africa diesel (MR2)",
    },
}


class FreightWorldscaleTool(BaseTool):
    name = "freight_worldscale"
    risk_tier = "low"
    description = (
        "Worldscale freight calculator for clean-products (CPP) tankers. "
        "Computes voyage freight in $/MT using the industry-standard "
        "formula ws_points / 100 * flat_rate. Knows the 2025 flat-rate "
        "schedule for the main TC routes (TC1 MEG->Japan naphtha, TC2 "
        "Cont->USAC gasoline, TC5 MEG->Japan naphtha LR1, TC6 Algeria->"
        "France, TC7 SG->Sydney, TC14 USAC->Cont, TC17 MEG->East Africa). "
        "Three actions: route (look up flat rate + freight given WS "
        "points), voyage_cost (full $-amount given cargo size), list "
        "(enumerate every TC route)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["route", "voyage_cost", "list"],
            },
            "route_code": {
                "type": "string",
                "description": "TC1 / TC2 / TC5 / TC6 / TC7 / TC14 / TC17",
            },
            "ws_points": {
                "type": "number",
                "description": "Worldscale points quoted by broker (e.g. 180 means WS180).",
            },
            "cargo_mt": {
                "type": "number",
                "description": "Override cargo size in MT (default uses route's standard).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        if action == "route":
            return self._route(arguments)
        if action == "voyage_cost":
            return self._voyage_cost(arguments)
        if action == "list":
            return self._list()
        return ToolResult(content=f"Unknown action '{action}'", is_error=True)

    @staticmethod
    def _resolve(code: str) -> dict[str, Any] | None:
        if not code:
            return None
        return _WS_FLAT_RATE_USD_MT.get(code.upper())

    def _route(self, args: dict[str, Any]) -> ToolResult:
        row = self._resolve(args.get("route_code") or "")
        if not row:
            return ToolResult(
                content=(
                    f"Unknown route. Supported: {', '.join(_WS_FLAT_RATE_USD_MT.keys())}"
                ),
                is_error=True,
            )
        try:
            ws = float(args.get("ws_points") or 100)
        except (TypeError, ValueError):
            return ToolResult(
                content="Error: ws_points must be a number", is_error=True
            )
        freight = ws / 100.0 * row["flat_rate_usd_mt"]
        return ToolResult(
            content=(
                f"Worldscale route {args.get('route_code', '').upper()} ({row['label']})\n"
                f"  Standard cargo : {row['cargo_class']} carrying {row['cargo_mt']:,} MT {row['product']}\n"
                f"  Flat rate      : ${row['flat_rate_usd_mt']:.2f}/MT (WS100 nominal, 2025)\n"
                f"  Quote          : WS{ws:.0f}\n"
                f"  Freight        : ${freight:.2f}/MT\n"
            ),
            metadata={
                "route_code": (args.get("route_code") or "").upper(),
                **row,
                "ws_points": ws,
                "freight_usd_per_mt": round(freight, 4),
            },
        )

    def _voyage_cost(self, args: dict[str, Any]) -> ToolResult:
        row = self._resolve(args.get("route_code") or "")
        if not row:
            return ToolResult(
                content="Unknown route",
                is_error=True,
            )
        try:
            ws = float(args.get("ws_points") or 100)
        except (TypeError, ValueError):
            return ToolResult(
                content="Error: ws_points must be a number", is_error=True
            )
        cargo_mt = float(args.get("cargo_mt") or row["cargo_mt"])
        freight = ws / 100.0 * row["flat_rate_usd_mt"]
        total = freight * cargo_mt
        return ToolResult(
            content=(
                f"Voyage cost {args.get('route_code', '').upper()}: ${total:,.0f}\n"
                f"  Cargo  : {cargo_mt:,.0f} MT {row['product']}\n"
                f"  Freight: ${freight:.2f}/MT (WS{ws:.0f} x ${row['flat_rate_usd_mt']:.2f} flat)\n"
                f"  Origin -> Destination: {row['origin']} -> {row['destination']}\n"
            ),
            metadata={
                "route_code": (args.get("route_code") or "").upper(),
                "cargo_mt": cargo_mt,
                "ws_points": ws,
                "flat_rate_usd_mt": row["flat_rate_usd_mt"],
                "freight_usd_per_mt": round(freight, 4),
                "total_voyage_usd": round(total, 0),
            },
        )

    def _list(self) -> ToolResult:
        lines = ["Supported Worldscale routes (2025 flat-rate schedule):"]
        for code, row in _WS_FLAT_RATE_USD_MT.items():
            lines.append(
                f"  {code:<5}  {row['label']:<40}  cargo {row['cargo_mt']:>6,} MT  flat ${row['flat_rate_usd_mt']:>5.2f}/MT"
            )
        return ToolResult(
            content="\n".join(lines),
            metadata={"routes": list(_WS_FLAT_RATE_USD_MT.keys())},
        )


__all__ = ["FreightWorldscaleTool"]
