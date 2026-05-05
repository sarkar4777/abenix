"""approval_gate — synchronous gate that blocks until a backend Approval row resolves.

The agent calls this tool with a payload, required_signoffs, and an
expires_seconds budget. We POST to /api/approvals to create the row, then
long-poll GET /api/approvals/{id} every 2s until status leaves ``pending``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


def _api_base_url() -> str:
    return (
        os.environ.get("INTERNAL_API_URL")
        or os.environ.get("API_BASE_URL")
        or os.environ.get("ABENIX_API_URL")
        or "http://localhost:8000"
    )


class ApprovalGateTool(BaseTool):
    name = "approval_gate"
    description = (
        "Pause the agent until a human (or N humans) sign off on a payload. "
        "Returns {status: approved|denied|expired, signoffs: [...]}. The "
        "agent should branch on status — denied/expired means do not proceed."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, human-readable label for the approval card",
            },
            "payload": {
                "type": "object",
                "description": "What the human needs to approve (action, params, context)",
            },
            "required_signoffs": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "How many distinct approvers must approve",
            },
            "expires_seconds": {
                "type": "integer",
                "default": 1800,
                "description": "Seconds until the approval auto-expires (max 7 days)",
            },
            "agent_execution_id": {
                "type": "string",
                "description": "Execution UUID — wired automatically when the runtime supplies it",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent UUID — wired automatically when the runtime supplies it",
            },
            "auth_token": {
                "type": "string",
                "description": "JWT/API key for the API call; runtime fills this from execution context",
            },
        },
        "required": ["payload"],
    }

    POLL_INTERVAL_SECONDS = 2.0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        payload = arguments.get("payload") or {}
        title = arguments.get("title") or "Action requires approval"
        required = int(arguments.get("required_signoffs") or 1)
        expires_seconds = int(arguments.get("expires_seconds") or 1800)
        agent_execution_id = arguments.get("agent_execution_id")
        agent_id = arguments.get("agent_id")
        auth_token = arguments.get("auth_token") or os.environ.get(
            "INTERNAL_API_TOKEN", ""
        )

        api = _api_base_url()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if auth_token:
            if auth_token.startswith("af_"):
                headers["X-API-Key"] = auth_token
            else:
                headers["Authorization"] = f"Bearer {auth_token}"

        body = {
            "title": title,
            "payload": payload,
            "required_signoffs": required,
            "expires_seconds": expires_seconds,
            "agent_execution_id": agent_execution_id,
            "agent_id": agent_id,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                created = await client.post(
                    f"{api}/api/approvals", headers=headers, json=body
                )
                if created.status_code >= 300:
                    return ToolResult(
                        content=f"failed to create approval: {created.status_code} {created.text[:300]}",
                        is_error=True,
                    )
                approval = (created.json() or {}).get("data") or {}
                approval_id = approval.get("id")
                if not approval_id:
                    return ToolResult(
                        content="API did not return an approval id", is_error=True
                    )
        except httpx.HTTPError as e:
            return ToolResult(content=f"approval create error: {e}", is_error=True)

        deadline = time.monotonic() + expires_seconds + 5
        async with httpx.AsyncClient(timeout=10.0) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(
                        f"{api}/api/approvals/{approval_id}", headers=headers
                    )
                    a = (r.json() or {}).get("data") or {}
                    status = a.get("status") or "pending"
                    if status != "pending":
                        return ToolResult(
                            content=json.dumps(
                                {
                                    "status": status,
                                    "approval_id": approval_id,
                                    "signoffs": a.get("signoffs") or [],
                                    "decided_at": a.get("decided_at"),
                                }
                            )
                        )
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)

        return ToolResult(
            content=json.dumps(
                {"status": "expired", "approval_id": approval_id, "signoffs": []}
            )
        )
