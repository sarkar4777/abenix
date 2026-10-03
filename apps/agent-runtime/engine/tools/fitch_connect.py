"""Fitch Connect API tool for issuer rating refresh.

Configurable shell. Hits Fitch Connect when $FITCH_CONNECT_API_KEY +
$FITCH_CONNECT_API_URL are set. If unset, returns
status=needs_configuration — never a mocked rating.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, ToolResult


REQUEST_TIMEOUT = 30.0
USER_AGENT = "AgentForge issuer-rating-refresh contact@agentforge.local"


class FitchConnectTool(BaseTool):
    name = "fitch_connect"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "FITCH_CONNECT_API_KEY",
            label="API key",
            kind="secret",
            required=True,
            group="Fitch Connect",
        ),
        ConfigField(
            "FITCH_CONNECT_API_URL",
            label="API URL",
            kind="url",
            required=True,
            group="Fitch Connect",
        ),
    )
    description = (
        "Fetch current issuer credit rating from Fitch Connect. Requires "
        "FITCH_CONNECT_API_KEY and FITCH_CONNECT_API_URL, set under Admin -> Tool Configuration. Without them "
        "returns needs_configuration; never mocked."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "legal_name": {"type": "string"},
            "ticker": {"type": "string"},
            "lei": {"type": "string"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        api_key = self.cfg("FITCH_CONNECT_API_KEY", required=True).strip()
        api_url = self.cfg("FITCH_CONNECT_API_URL", required=True).strip()
        legal_name = (arguments.get("legal_name") or "").strip()
        ticker = (arguments.get("ticker") or "").strip()
        lei = (arguments.get("lei") or "").strip()
        if not (legal_name or ticker or lei):
            return ToolResult(
                content="legal_name, ticker, or lei required", is_error=True
            )

        params: dict[str, Any] = {}
        if lei:
            params["lei"] = lei
        elif ticker:
            params["ticker"] = ticker
        else:
            params["name"] = legal_name

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                r = await client.get(
                    f"{api_url.rstrip('/')}/issuer-rating",
                    params=params,
                    headers=headers,
                )
                if r.status_code == 401:
                    return ToolResult(
                        content=json.dumps(
                            {"status": "auth_error", "reason": "Fitch returned 401"}
                        ),
                        is_error=True,
                        metadata={"status": "auth_error"},
                    )
                if r.status_code == 404:
                    return ToolResult(
                        content=json.dumps({"status": "not_found"}),
                        is_error=False,
                        metadata={"status": "not_found"},
                    )
                r.raise_for_status()
                payload = r.json()
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps({"status": "fetch_error", "reason": str(e)}),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "ratings": [
                        {
                            "agency": "Fitch",
                            "rating": payload.get("rating")
                            or payload.get("longTermIDR"),
                            "outlook": payload.get("outlook"),
                            "as_of": payload.get("ratingActionDate")
                            or payload.get("asOf"),
                            "issuer": payload.get("issuerName") or legal_name,
                            "source_url": payload.get("sourceUrl")
                            or "https://www.fitchratings.com/",
                        }
                    ],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            ),
            is_error=False,
            metadata={"status": "ok"},
        )


__all__ = ["FitchConnectTool"]
