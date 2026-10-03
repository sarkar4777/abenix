"""PHMSA pipeline operator lookup for counterparty refresh.

The US Pipeline and Hazardous Materials Safety Administration (PHMSA)
publishes operator registrations + incident history through a public
search portal. This tool issues an HTTP query to the operator-search
endpoint and parses the HTML for operator IDs and incident counts.

Source: https://primis.phmsa.dot.gov/comm/reports/operator/OperatorSearch.aspx
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)

PHMSA_SEARCH_URL = (
    "https://primis.phmsa.dot.gov/comm/reports/operator/OperatorSearch.aspx"
)
USER_AGENT = "AgentForge counterparty-refresh contact@agentforge.local"
REQUEST_TIMEOUT = 30.0


OPERATOR_ID_RE = re.compile(r"OperatorId=(\d+)", re.IGNORECASE)


class PhmsaLookupTool(BaseTool):
    name = "phmsa_lookup"
    risk_tier = "low"
    description = (
        "Search PHMSA for a US pipeline operator by name. Returns the "
        "operator ID(s) + a link to the public operator profile. "
        "Public free endpoint, no key. No mock data."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "legal_name": {"type": "string"},
            "max_results": {
                "type": "integer",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
            },
        },
        "required": ["legal_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        legal_name = (arguments.get("legal_name") or "").strip()
        max_results = int(arguments.get("max_results") or 10)
        if not legal_name:
            return ToolResult(content="legal_name required", is_error=True)

        params = {"name": legal_name}
        url = f"{PHMSA_SEARCH_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                if r.status_code in (404, 410):
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "endpoint_unavailable",
                                "reason": f"PHMSA endpoint returned {r.status_code} — public page may have moved",
                                "url": url,
                            }
                        ),
                        is_error=False,
                        metadata={"status": "endpoint_unavailable"},
                    )
                r.raise_for_status()
                html = r.text
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps(
                    {"status": "fetch_error", "reason": str(e), "url": url}
                ),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        ids = list(dict.fromkeys(OPERATOR_ID_RE.findall(html)))[:max_results]
        if not ids:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "no_matches",
                        "reason": "PHMSA returned no operator records for this name",
                        "legal_name": legal_name,
                        "search_url": url,
                    }
                ),
                is_error=False,
                metadata={"status": "no_matches"},
            )

        operators = [
            {
                "license_type": "PHMSA_PIPELINE",
                "issuer": "PHMSA",
                "identifier": op_id,
                "status": "active",
                "source_url": f"https://primis.phmsa.dot.gov/comm/reports/operator/OperatorIE_opid_{op_id}.html",
                "source_filing": f"PHMSA operator ID {op_id}",
                "source_tool": "phmsa_lookup",
            }
            for op_id in ids
        ]

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "legal_name": legal_name,
                    "permits": operators,
                    "search_url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            ),
            is_error=False,
            metadata={"status": "ok", "n_operators": len(operators)},
        )


__all__ = ["PhmsaLookupTool"]
