"""Moody's Orbis lookup tool — honest stub.

TODO: real Orbis Universal Data API uses OAuth2 + a per-tenant
subscription URL. The previous placeholder X-Api-Key + naive HTTP
GET path was never going to work against the actual product. Wire up
proper OAuth2 client-credentials + per-tenant base URL when budget
allows; until then this tool returns a clear "unavailable" envelope so
the KYC agent falls back to GLEIF / Companies House / Bundesanzeiger /
tavily_search via ubo_discovery + legal_existence_verifier and never
fabricates Orbis citations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class MoodysOrbisLookupTool(BaseTool):
    name = "moodys_orbis_lookup"
    description = (
        "Look up a counterparty in Moody's Orbis (BvD). This environment is "
        "not provisioned for Orbis; the tool always returns "
        "{status:'unavailable', honest_banner:true}. Caller agents must fall "
        "back to GLEIF, Companies House, Bundesanzeiger, EDGAR, and "
        "tavily_search via ubo_discovery + legal_existence_verifier, and "
        "must NOT cite Moody's, BvD, Orbis, or D&B as a source."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Counterparty legal name."},
            "country_iso2": {
                "type": "string",
                "description": "ISO-2 country code (optional but recommended).",
            },
            "lei": {"type": "string", "description": "LEI code (optional)."},
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("name") or "").strip()
        country = (arguments.get("country_iso2") or "").strip().upper()
        lei = (arguments.get("lei") or "").strip().upper()
        if not name and not lei:
            return ToolResult(
                content="Error: 'name' or 'lei' is required.", is_error=True
            )

        payload = {
            "status": "unavailable",
            "honest_banner": True,
            "reason": (
                "Moody's Orbis not configured in this environment. Refer to "
                "Moody's report for ownership structure when available; "
                "otherwise rely on GLEIF / Companies House / Bundesanzeiger / "
                "tavily_search via ubo_discovery + legal_existence_verifier."
            ),
            "name": name,
            "country_iso2": country,
            "lei": lei,
            "source_citation": None,
            "references": [],
        }
        return ToolResult(
            content=json.dumps(payload, indent=2),
            metadata={"status": "unavailable"},
        )
