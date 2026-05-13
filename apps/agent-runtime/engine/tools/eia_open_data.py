"""eia_open_data — fetch energy market series from the US EIA Open Data API.

The US Energy Information Administration publishes weekly/daily/monthly time
series for every commodity an energy trader looks at — propane (Mont Belvieu),
crude (WTI/Brent landed), natural gas (Henry Hub), distillates, jet, gasoline,
inventories, exports, refinery utilisation. The v2 API is fully free; an API
key is technically required but new keys are issued instantly at
https://www.eia.gov/opendata/register.php and there's no rate cap that bites
at demo scale.

Common series_id shortcuts (used in the Wingman demo):
  PROPANE_USGC_MB     Mont Belvieu Propane spot (USGC), weekly
  PROPANE_USA         US average wholesale propane, weekly
  WTI_SPOT            WTI Cushing spot, daily
  BRENT_SPOT          Brent Europe spot, daily
  HH_NATGAS           Henry Hub natural gas spot, daily
  US_LPG_EXPORTS      Weekly US LPG exports kbbl/d
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE_URL = "https://api.eia.gov/v2"

_SHORTCUTS: dict[str, dict[str, Any]] = {
    # NOTE: filter by `series` (the EIA series id) rather than
    # product+duoarea — the duoarea codes the previous version used were
    # wrong (Y35NY = New York, RCUS = US-wide, RBRTE = aggregated index)
    # which silently returned 0 rows. Anchoring on the series id matches
    # what the EIA browser uses and is the canonical way to address a
    # spot price series. Verified live against api.eia.gov.
    "PROPANE_USGC_MB": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "EER_EPLLPA_PF4_Y44MB_DPG",
        },
        "unit": "$/gal",
        "label": "Mont Belvieu propane spot (daily)",
    },
    "PROPANE_USA": {
        "path": "petroleum/pri/wfr/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EMM_EPLLPA_PWG_NUS_DPG",
        },
        "unit": "$/gal",
        "label": "US wholesale propane (national avg) weekly",
    },
    "WTI_SPOT": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RWTC",
        },
        "unit": "$/bbl",
        "label": "WTI Cushing daily spot",
    },
    "BRENT_SPOT": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": "RBRTE",
        },
        "unit": "$/bbl",
        "label": "Brent Europe daily spot",
    },
    "HH_NATGAS": {
        "path": "natural-gas/pri/sum/data/",
        "params": {
            "frequency": "daily",
            "data[0]": "value",
            "facets[duoarea][]": "RGC",
            "facets[process][]": "PG1",
        },
        "unit": "$/MMBtu",
        "label": "Henry Hub natural gas daily spot",
    },
    "US_LPG_EXPORTS": {
        "path": "petroleum/move/expc/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[product][]": "EPLLPA",
        },
        "unit": "kbbl/d",
        "label": "US LPG exports weekly",
    },
    "GASOLINE_USGC": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EER_EPMRR_PF4_Y44MB_DPG",
        },
        "unit": "$/gal",
        "label": "USGC gasoline (RBOB) weekly spot",
    },
    "ULSD_USGC": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EER_EPD2DXL0_PF4_Y44MB_DPG",
        },
        "unit": "$/gal",
        "label": "USGC ultra-low-sulphur diesel weekly spot",
    },
    "JET_USGC": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EER_EPJK_PF4_Y44MB_DPG",
        },
        "unit": "$/gal",
        "label": "USGC kerosene-type jet fuel weekly spot",
    },
    "HEATING_OIL_NYH": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EER_EPD2F_PF4_Y35NY_DPG",
        },
        "unit": "$/gal",
        "label": "NY Harbor No.2 heating oil weekly spot",
    },
    "GASOLINE_NYH": {
        "path": "petroleum/pri/spt/data/",
        "params": {
            "frequency": "weekly",
            "data[0]": "value",
            "facets[series][]": "EER_EPMRR_PF4_Y35NY_DPG",
        },
        "unit": "$/gal",
        "label": "NY Harbor conventional gasoline weekly spot",
    },
}


class EiaOpenDataTool(BaseTool):
    name = "eia_open_data"
    description = (
        "Fetch energy market time series from the US Energy Information "
        "Administration (EIA) Open Data API v2. Use one of the shortcut "
        "ids (PROPANE_USGC_MB, WTI_SPOT, BRENT_SPOT, HH_NATGAS, "
        "US_LPG_EXPORTS, PROPANE_USA) for the common cases, or pass a raw "
        "EIA series path. Returns the most recent N data points with their "
        "dates, plus min/max/mean and unit metadata. Real, citable, "
        "regulator-published numbers — every value comes with the EIA "
        "series id for audit."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "series_id": {
                "type": "string",
                "description": (
                    "One of the shortcut ids (PROPANE_USGC_MB, WTI_SPOT, "
                    "BRENT_SPOT, HH_NATGAS, US_LPG_EXPORTS, PROPANE_USA) or a raw "
                    "EIA v2 path like 'petroleum/pri/spt/data/'."
                ),
            },
            "start": {
                "type": "string",
                "description": "Optional ISO date (YYYY-MM-DD) — defaults to 'last 52 weeks'.",
            },
            "end": {
                "type": "string",
                "description": "Optional ISO date (YYYY-MM-DD) — defaults to today.",
            },
            "limit": {
                "type": "integer",
                "default": 52,
                "description": "Max number of data points to return (newest first).",
            },
        },
        "required": ["series_id"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        series_id = (arguments.get("series_id") or "").strip()
        if not series_id:
            return ToolResult(content="Error: series_id is required", is_error=True)

        api_key = os.environ.get("EIA_API_KEY", "").strip()

        shortcut = _SHORTCUTS.get(series_id)
        if shortcut:
            path = shortcut["path"]
            params: dict[str, Any] = dict(shortcut["params"])
            unit = shortcut["unit"]
            label = shortcut["label"]
        else:
            path = series_id.lstrip("/")
            params = {"frequency": "monthly", "data[0]": "value"}
            unit = "unknown"
            label = series_id

        params["sort[0][column]"] = "period"
        params["sort[0][direction]"] = "desc"
        params["length"] = int(arguments.get("limit", 52))
        if arguments.get("start"):
            params["start"] = arguments["start"]
        if arguments.get("end"):
            params["end"] = arguments["end"]
        if api_key:
            params["api_key"] = api_key

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(f"{_BASE_URL}/{path}", params=params)
                if r.status_code == 403 and not api_key:
                    return ToolResult(
                        content=(
                            "EIA API rejected anonymous request (HTTP 403). Set "
                            "EIA_API_KEY — register a free key at "
                            "https://www.eia.gov/opendata/register.php and pass "
                            "it as an env var on the agent-runtime pod."
                        ),
                        is_error=True,
                    )
                if r.status_code >= 400:
                    return ToolResult(
                        content=f"EIA HTTP {r.status_code}: {r.text[:300]}",
                        is_error=True,
                    )
                data = r.json()
        except httpx.HTTPError as e:
            return ToolResult(content=f"EIA request failed: {e}", is_error=True)

        rows = (data.get("response") or {}).get("data") or []
        if not rows:
            return ToolResult(
                content=f"EIA returned no data points for series '{series_id}'. "
                f"Check the series id or widen the date range.",
            )

        values: list[float] = []
        lines = [f"EIA series: {label}", f"Series id: {series_id}", f"Unit: {unit}", ""]
        for row in rows[: int(arguments.get("limit", 52))]:
            period = row.get("period") or "?"
            raw = row.get("value")
            if raw is None or raw == "":
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            values.append(v)
            lines.append(f"  {period}: {v:.4f}")

        if not values:
            return ToolResult(
                content=f"EIA returned rows for '{series_id}' but none had numeric values.",
            )

        avg = sum(values) / len(values)
        latest = values[0]
        first = values[-1]
        change_pct = ((latest - first) / first) * 100 if first else 0.0

        lines.insert(
            4,
            f"Latest: {latest:.4f} {unit}  ·  Period mean: {avg:.4f}  ·  Period change: {change_pct:+.2f}%",
        )

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "series_id": series_id,
                "label": label,
                "unit": unit,
                "latest": round(latest, 6),
                "min": round(min(values), 6),
                "max": round(max(values), 6),
                "mean": round(avg, 6),
                "data_points": len(values),
                "period_change_pct": round(change_pct, 4),
                "source": "https://api.eia.gov/v2",
            },
        )
