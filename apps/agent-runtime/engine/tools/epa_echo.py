"""EPA ECHO REST tool for counterparty permit refresh.

EPA's Enforcement and Compliance History Online (ECHO) exposes a public
JSON REST API covering Title V air permits, NPDES water permits, RCRA
hazardous-waste handlers, and enforcement actions. Free, no key required.

Source: https://echo.epa.gov/tools/web-services
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)

ECHO_FACILITY_URL = "https://echodata.epa.gov/echo/echo_rest_services.get_facility_info"
ECHO_FACILITY_PAGE = "https://echo.epa.gov/facilities/facility-search/results"
USER_AGENT = "AgentForge counterparty-refresh contact@agentforge.local"
REQUEST_TIMEOUT = 30.0


class EpaEchoTool(BaseTool):
    name = "epa_echo"
    description = (
        "Look up a counterparty in EPA ECHO. Returns matching facilities "
        "with Title V air, NPDES water, and RCRA hazardous-waste permits, "
        "current enforcement actions, and violation history. Public free API. "
        "No mock data — returns no_matches if ECHO has no records."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "legal_name": {"type": "string"},
            "state": {
                "type": "string",
                "description": "Optional US state code (e.g. TX, CA)",
            },
            "max_results": {
                "type": "integer",
                "default": 20,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["legal_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        legal_name = (arguments.get("legal_name") or "").strip()
        state = (arguments.get("state") or "").strip()
        max_results = int(arguments.get("max_results") or 20)

        if not legal_name:
            return ToolResult(content="legal_name required", is_error=True)

        params: dict[str, Any] = {
            "output": "JSON",
            "p_fn": legal_name,
            "responseset": "1",
        }
        if state:
            params["p_st"] = state

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                r = await client.get(
                    ECHO_FACILITY_URL, params=params, headers={"User-Agent": USER_AGENT}
                )
                r.raise_for_status()
                payload = r.json()
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps({"status": "fetch_error", "reason": str(e)}),
                is_error=True,
                metadata={"status": "fetch_error"},
            )
        except json.JSONDecodeError:
            return ToolResult(
                content=json.dumps(
                    {"status": "fetch_error", "reason": "ECHO returned non-JSON"}
                ),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        results = (
            payload.get("Results", {}).get("Facilities")
            or payload.get("Results", {}).get("Results")
            or []
        )
        if isinstance(results, dict):
            results = [results]

        permits: list[dict[str, Any]] = []
        violations = 0
        for f in results[:max_results]:
            fac_name = (
                f.get("CWPName") or f.get("FacName") or f.get("FacilityName") or ""
            )
            registry_id = (
                f.get("RegistryID") or f.get("REGISTRY_ID") or f.get("FAC_REGISTRY_ID")
            )
            state_code = f.get("FacState") or f.get("CWPState")
            for kind, status_key, id_key, label in [
                ("CAA", "CAAQtrsWithViol", "AIRPermitID", "EPA_TITLE_V"),
                ("CWA", "CWAQtrsWithViol", "CWPNPDESID", "EPA_NPDES"),
                ("RCRA", "RCRAQtrsWithViol", "RCRAHandlerID", "EPA_RCRA"),
            ]:
                ident = f.get(id_key)
                if not ident:
                    continue
                qtrs_viol = f.get(status_key) or 0
                try:
                    qtrs_viol = int(qtrs_viol)
                except Exception:
                    qtrs_viol = 0
                status = "active"
                if qtrs_viol > 0:
                    violations += 1
                permits.append(
                    {
                        "license_type": label,
                        "issuer": "EPA",
                        "identifier": str(ident),
                        "status": status,
                        "valid_from": None,
                        "valid_to": None,
                        "source_url": (
                            f"{ECHO_FACILITY_PAGE}?registry_id={registry_id}"
                            if registry_id
                            else ECHO_FACILITY_PAGE
                        ),
                        "source_filing": f"EPA ECHO · {kind} · facility {fac_name} ({state_code}) · violations last 12 quarters: {qtrs_viol}",
                        "source_tool": "epa_echo",
                        "violations_last_3yr": qtrs_viol,
                    }
                )

        if not permits:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "no_matches",
                        "reason": "EPA ECHO has no facility records matching this name",
                        "legal_name": legal_name,
                        "state": state or None,
                    }
                ),
                is_error=False,
                metadata={"status": "no_matches"},
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "legal_name": legal_name,
                    "permits": permits,
                    "violations_facilities": violations,
                    "n_facilities_scanned": len(results),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            ),
            is_error=False,
            metadata={"status": "ok", "n_permits": len(permits)},
        )


__all__ = ["EpaEchoTool"]
