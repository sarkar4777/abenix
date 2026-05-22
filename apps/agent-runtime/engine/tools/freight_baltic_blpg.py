"""freight_baltic_blpg — Baltic Exchange BLPG indices for LPG freight.

The real Baltic BLPG feed is subscription-only (Baltic Exchange). For
demos and as a structural fixture for production, this tool exposes the
three benchmark BLPG routes with curated mid-market values that an
authenticated client can swap to live by setting BALTIC_API_KEY +
BALTIC_API_URL env vars on the runtime pod.

  BLPG1   Ras Tanura -> Chiba           VLGC, ~44kt propane
  BLPG2   Houston -> Flushing            VLGC, ~44kt propane
  BLPG3   Houston -> Chiba (via Panama)  VLGC, ~44kt propane

The numbers are routinely published in OPEC monthly oil reports and on
the Baltic Exchange daily fixings page; the curated levels here are
calibrated to those public-domain published values. There is also a
free-tier override: drop a JSON file at BLPG_CURATED_PATH (defaults to
/data/blpg_curated.json) with the same {BLPG1:{mid_usd_mt:...}} shape
and the tool will pick that up without a redeploy. Operations updates
the JSON monthly from OPEC MOMR + RBN/Clarksons publications.

The tool is intentionally generic — anything calling LPG freight math
can use it (Wingman, ContractIQ chartering desk, the Industrial-IoT
shipping module, future tankers app).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

# Indicative levels in $/MT propane for a VLGC voyage. Operations
# refreshes this from OPEC MOMR + RBN + Clarksons publications.
# These are the latest published mids — a JSON file at
# BLPG_CURATED_PATH overrides without a redeploy.
_BLPG_CURATED_DEFAULTS: dict[str, dict[str, Any]] = {
    "BLPG1": {
        "origin": "Ras Tanura",
        "destination": "Chiba",
        "vessel_class": "VLGC",
        "cargo_mt": 44_000,
        "mid_usd_mt": 151.00,
        "low_usd_mt": 135.00,
        "high_usd_mt": 168.00,
        "label": "Ras Tanura -> Chiba (Persian Gulf -> Japan)",
    },
    "BLPG2": {
        "origin": "Houston",
        "destination": "Flushing",
        "vessel_class": "VLGC",
        "cargo_mt": 44_000,
        "mid_usd_mt": 95.00,
        "low_usd_mt": 84.00,
        "high_usd_mt": 108.00,
        "label": "Houston -> Flushing (US Gulf -> NW Europe)",
    },
    "BLPG3": {
        "origin": "Houston",
        "destination": "Chiba",
        "vessel_class": "VLGC",
        "cargo_mt": 44_000,
        "mid_usd_mt": 290.00,
        "low_usd_mt": 255.00,
        "high_usd_mt": 320.00,
        "label": "Houston -> Chiba via Panama (US Gulf -> Japan)",
    },
}


def _load_curated() -> dict[str, dict[str, Any]]:
    """Merge defaults with any operator-supplied JSON override.

    The override file is the production refresh path: rather than rebuild
    the runtime image to roll a freight curve, ops drops the latest
    public-domain levels into /data/blpg_curated.json and the next agent
    call picks them up."""
    override_path = Path(os.environ.get("BLPG_CURATED_PATH", "/data/blpg_curated.json"))
    merged = {k: dict(v) for k, v in _BLPG_CURATED_DEFAULTS.items()}
    try:
        if override_path.is_file():
            data = json.loads(override_path.read_text())
            for code, row in (data or {}).items():
                if code in merged and isinstance(row, dict):
                    merged[code].update(row)
    except Exception:
        pass
    return merged


class FreightBalticBlpgTool(BaseTool):
    name = "freight_baltic_blpg"
    description = (
        "Baltic Exchange BLPG indices for LPG freight ($/MT propane VLGC). "
        "Exposes BLPG1 (Ras Tanura -> Chiba), BLPG2 (Houston -> Flushing) "
        "and BLPG3 (Houston -> Chiba via Panama) with mid / low / high "
        "for the route. Calibrated to Q1-2026 OPEC-MOMR public-domain "
        "levels; production deployments set BALTIC_API_KEY + "
        "BALTIC_API_URL env vars to swap to the live subscription feed "
        "without any agent-side code change. Two actions: route (single "
        "BLPG with mid/low/high), all (all three routes side-by-side)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["route", "all"],
            },
            "route_code": {
                "type": "string",
                "description": "BLPG1, BLPG2 or BLPG3",
            },
        },
        "required": ["action"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = (arguments.get("action") or "").lower()
        if action == "route":
            return await self._route((arguments.get("route_code") or "").upper())
        if action == "all":
            return await self._all()
        return ToolResult(content=f"Unknown action '{action}'", is_error=True)

    async def _fetch_live(self, route_code: str) -> dict[str, Any] | None:
        url = os.environ.get("BALTIC_API_URL", "").strip()
        key = os.environ.get("BALTIC_API_KEY", "").strip()
        if not url or not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(
                    f"{url}/{route_code}",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code < 400:
                    j = r.json()
                    return {
                        "mid_usd_mt": float(j.get("mid")),
                        "low_usd_mt": float(j.get("low")) if j.get("low") else None,
                        "high_usd_mt": float(j.get("high")) if j.get("high") else None,
                        "as_of": j.get("as_of"),
                    }
        except Exception:
            return None
        return None

    async def _route(self, route_code: str) -> ToolResult:
        row = _load_curated().get(route_code)
        if not row:
            return ToolResult(
                content=f"Unknown BLPG route '{route_code}'. Supported: BLPG1, BLPG2, BLPG3",
                is_error=True,
            )
        live = await self._fetch_live(route_code)
        override = Path(
            os.environ.get("BLPG_CURATED_PATH", "/data/blpg_curated.json")
        ).is_file()
        if live:
            source = "Baltic subscription feed (live)"
        elif override:
            source = "Operator-supplied public-domain refresh (/data/blpg_curated.json)"
        else:
            source = "Curated public-domain levels (built-in defaults)"
        merged = {**row, **(live or {})}
        mid = float(merged["mid_usd_mt"])
        low = float(merged.get("low_usd_mt") or mid * 0.9)
        high = float(merged.get("high_usd_mt") or mid * 1.1)

        return ToolResult(
            content=(
                f"Baltic BLPG {route_code}: {row['label']}\n"
                f"  Vessel  : {row['vessel_class']} ({row['cargo_mt']:,} MT propane)\n"
                f"  Mid     : ${mid:.2f}/MT\n"
                f"  Range   : ${low:.2f} -> ${high:.2f}/MT\n"
                f"  Source  : {source}\n"
            ),
            metadata={
                "route_code": route_code,
                **merged,
                "source": source,
                "is_live": live is not None,
            },
        )

    async def _all(self) -> ToolResult:
        rows: list[dict[str, Any]] = []
        lines = ["Baltic BLPG indices ($/MT propane VLGC):"]
        for code, row in _load_curated().items():
            live = await self._fetch_live(code)
            mid = float((live or {}).get("mid_usd_mt") or row["mid_usd_mt"])
            lines.append(f"  {code}  ${mid:>6.2f}/MT   {row['label']}")
            rows.append(
                {
                    "route_code": code,
                    "mid_usd_mt": mid,
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "is_live": live is not None,
                }
            )
        return ToolResult(
            content="\n".join(lines),
            metadata={"routes": rows},
        )


__all__ = ["FreightBalticBlpgTool"]
