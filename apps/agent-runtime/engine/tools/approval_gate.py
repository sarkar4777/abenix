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


async def _mark_waiting(execution_id: str | None, timeout: int) -> None:
    if not execution_id:
        return
    try:
        from engine.tools.human_approval import mark_waiting

        await mark_waiting(str(execution_id), timeout)
    except Exception:
        pass


async def _clear_waiting(execution_id: str | None) -> None:
    if not execution_id:
        return
    try:
        from engine.tools.human_approval import clear_waiting

        await clear_waiting(str(execution_id))
    except Exception:
        pass


def _api_base_url() -> str:
    explicit = (
        os.environ.get("INTERNAL_API_URL")
        or os.environ.get("ABENIX_INTERNAL_URL")
        or os.environ.get("API_BASE_URL")
        or os.environ.get("ABENIX_API_URL")
    )
    if explicit:
        return explicit
    # inside the cluster kubernetes injects the API service address
    host = os.environ.get("ABENIX_API_SERVICE_HOST")
    if host:
        return f"http://{host}:{os.environ.get('ABENIX_API_SERVICE_PORT', '8000')}"
    return "http://localhost:8000"


def auth_headers(auth_token: str) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        if auth_token.startswith("af_"):
            headers["X-API-Key"] = auth_token
        else:
            headers["Authorization"] = f"Bearer {auth_token}"
    return headers


def run_token(user_id: str, tenant_id: str, user_role: str = "") -> str:
    """A short-lived token for the user the run belongs to, or the internal one."""
    if user_id and tenant_id:
        try:
            from engine.tools.invoke_agent import mint_user_token

            token = mint_user_token(user_id, tenant_id, user_role)
            if token:
                return token
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("INTERNAL_API_TOKEN", "")


async def create_approval(
    body: dict[str, Any], headers: dict[str, str]
) -> tuple[dict[str, Any] | None, str]:
    """POST the approval. Returns (approval, "") or (None, why it failed)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            created = await client.post(
                f"{_api_base_url()}/api/approvals", headers=headers, json=body
            )
    except httpx.HTTPError as e:
        return None, f"approval create error: {e}"
    if created.status_code >= 300:
        return (
            None,
            f"failed to create approval: {created.status_code} {created.text[:300]}",
        )
    approval = (created.json() or {}).get("data") or {}
    if not approval.get("id"):
        return None, "API did not return an approval id"
    return approval, ""


async def wait_for_approval(
    approval_id: str,
    headers: dict[str, str],
    expires_seconds: int,
    execution_id: str | None = None,
    poll_interval: float = 2.0,
) -> dict[str, Any]:
    """Long-poll until the approval leaves pending. The execution is marked waiting meanwhile."""
    api = _api_base_url()
    deadline = time.monotonic() + expires_seconds + 5
    await _mark_waiting(execution_id, expires_seconds + 5)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(
                        f"{api}/api/approvals/{approval_id}", headers=headers
                    )
                    a = (r.json() or {}).get("data") or {}
                    if (a.get("status") or "pending") != "pending":
                        return a
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(poll_interval)
    finally:
        await _clear_waiting(execution_id)
    return {"id": approval_id, "status": "expired", "signoffs": [], "timed_out": True}


class ApprovalGateTool(BaseTool):
    name = "approval_gate"
    risk_tier = "low"
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
            "kind": {
                "type": "string",
                "description": "Optional discriminator (e.g. device.remote_reset, claim.adjudicate) so reviewer UIs and SDK consumers can dispatch handlers per gate type",
            },
            "agent_execution_id": {
                "type": "string",
                "description": "Execution UUID, filled from the running agent when left out",
            },
            "agent_id": {
                "type": "string",
                "description": "Agent UUID, filled from the running agent when left out",
            },
            "auth_token": {
                "type": "string",
                "description": "JWT or API key for the API call, by default a short-lived token for the user the run belongs to",
            },
        },
        "required": ["payload"],
    }

    POLL_INTERVAL_SECONDS = 2.0

    def __init__(
        self,
        execution_id: str = "",
        agent_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
        user_role: str = "",
    ) -> None:
        self._execution_id = execution_id
        self._agent_id = agent_id
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._user_role = user_role

    def _run_token(self) -> str:
        # the approval is created as the user the run belongs to
        if not (self._user_id and self._tenant_id):
            return ""
        try:
            from engine.tools.invoke_agent import mint_user_token

            return mint_user_token(self._user_id, self._tenant_id, self._user_role)
        except Exception:  # noqa: BLE001
            return ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        payload = arguments.get("payload") or {}
        title = arguments.get("title") or "Action requires approval"
        required = int(arguments.get("required_signoffs") or 1)
        expires_seconds = int(arguments.get("expires_seconds") or 1800)
        from engine import governance

        run = governance.current()
        agent_execution_id = (
            arguments.get("agent_execution_id")
            or self._execution_id
            or (run.execution_id if run else "")
            or None
        )
        agent_id = arguments.get("agent_id") or self._agent_id or None
        auth_token = (
            arguments.get("auth_token")
            or self._run_token()
            or os.environ.get("INTERNAL_API_TOKEN", "")
        )
        headers = auth_headers(auth_token)

        body: dict[str, Any] = {
            "title": title,
            "payload": payload,
            "required_signoffs": required,
            "expires_seconds": expires_seconds,
            "agent_execution_id": agent_execution_id,
            "agent_id": agent_id,
        }
        gate_kind = arguments.get("kind") or arguments.get("gate_kind")
        if gate_kind:
            body["gate_kind"] = gate_kind
        if run is not None and run.tier != "low":
            # the API raises the sign-off count to what the tenant requires at this tier
            body["risk_tier"] = run.tier
        approval, err = await create_approval(body, headers)
        if approval is None:
            return ToolResult(content=err, is_error=True)
        approval_id = approval["id"]

        a = await wait_for_approval(
            approval_id,
            headers,
            expires_seconds,
            agent_execution_id,
            self.POLL_INTERVAL_SECONDS,
        )
        status = a.get("status") or "expired"
        if a.get("timed_out"):
            return ToolResult(
                content=json.dumps(
                    {"status": "expired", "approval_id": approval_id, "signoffs": []}
                )
            )
        return ToolResult(
            content=json.dumps(
                {
                    "status": status,
                    "approval_id": approval_id,
                    "signoffs": a.get("signoffs") or [],
                    "decided_at": a.get("decided_at"),
                    "gate_kind": a.get("gate_kind"),
                }
            )
        )
