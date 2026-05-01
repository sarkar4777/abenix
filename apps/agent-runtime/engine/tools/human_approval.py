"""Human-in-the-Loop approval gate tool."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import redis.asyncio as aioredis

from engine.tools.base import BaseTool, ToolResult

# Default Redis URL — reads from env, can also be overridden at registration time
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_redis_pool: aioredis.Redis | None = None


def configure_redis(url: str) -> None:
    """Set the Redis URL for the approval queue."""
    global _REDIS_URL, _redis_pool
    _REDIS_URL = url
    _redis_pool = None


async def _get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_pool


def _approval_key(execution_id: str, gate_id: str) -> str:
    return f"hitl:approval:{execution_id}:{gate_id}"


def _pending_key(tenant_id: str) -> str:
    return f"hitl:pending:{tenant_id}"


async def submit_approval(
    execution_id: str,
    gate_id: str,
    decision: str,
    reviewer: str = "",
    comment: str = "",
) -> bool:
    """Submit an approval or rejection for a pending gate."""
    r = await _get_redis()
    key = _approval_key(execution_id, gate_id)
    result = json.dumps(
        {
            "decision": decision,  # "approved" or "rejected"
            "reviewer": reviewer,
            "comment": comment,
            "decided_at": time.time(),
        }
    )
    await r.set(key, result, ex=7200)  # 2 hour TTL
    return True


async def list_pending_approvals(tenant_id: str) -> list[dict[str, Any]]:
    """List all pending approval requests for a tenant."""
    r = await _get_redis()
    key = _pending_key(tenant_id)
    members = await r.smembers(key)
    results = []
    for member in members:
        data = json.loads(member)
        # Check if already decided
        approval = await r.get(_approval_key(data["execution_id"], data["gate_id"]))
        if approval:
            continue  # Already decided, skip
        results.append(data)
    return results


class HumanApprovalTool(BaseTool):
    name = "human_approval"
    description = (
        "Pauses execution and requests human approval before proceeding. "
        "Use this for high-risk operations like production deployments, "
        "data deletions, or financial transactions. The execution will "
        "wait until a human approves or rejects, or until timeout."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Short description of the action requiring approval",
            },
            "details": {
                "type": "string",
                "description": "Detailed context about what will happen if approved",
            },
            "risk_level": {
                "type": "string",
                "enum": ["low", "medium", "high", "critical"],
                "description": "Risk level of the action",
                "default": "medium",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Max seconds to wait for approval (default 3600 = 1 hour)",
                "default": 3600,
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        execution_id: str = "",
        tenant_id: str = "",
        agent_name: str = "",
    ):
        self._execution_id = execution_id
        self._tenant_id = tenant_id
        self._agent_name = agent_name
        self._gate_counter = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments["action"]
        details = arguments.get("details", "")
        risk_level = arguments.get("risk_level", "medium")
        timeout = min(arguments.get("timeout_seconds", 3600), 7200)  # Cap at 2 hours

        self._gate_counter += 1
        gate_id = f"gate-{self._gate_counter}"

        r = await _get_redis()

        # Register the pending approval
        pending_data = json.dumps(
            {
                "execution_id": self._execution_id,
                "gate_id": gate_id,
                "tenant_id": self._tenant_id,
                "agent_name": self._agent_name,
                "action": action,
                "details": details,
                "risk_level": risk_level,
                "requested_at": time.time(),
            }
        )
        await r.sadd(_pending_key(self._tenant_id), pending_data)

        # Poll for approval
        approval_key = _approval_key(self._execution_id, gate_id)
        start = time.time()
        poll_interval = 2  # seconds

        while (time.time() - start) < timeout:
            result = await r.get(approval_key)
            if result:
                decision = json.loads(result)
                # Clean up pending
                await r.srem(_pending_key(self._tenant_id), pending_data)

                if decision["decision"] == "approved":
                    reviewer = decision.get("reviewer", "unknown")
                    comment = decision.get("comment", "")
                    msg = f"Approved by {reviewer}."
                    if comment:
                        msg += f" Comment: {comment}"
                    return ToolResult(
                        content=msg,
                        metadata={
                            "gate_id": gate_id,
                            "decision": "approved",
                            "reviewer": reviewer,
                        },
                    )
                else:
                    reviewer = decision.get("reviewer", "unknown")
                    comment = decision.get("comment", "No reason given")
                    return ToolResult(
                        content=f"Rejected by {reviewer}. Reason: {comment}",
                        is_error=True,
                        metadata={
                            "gate_id": gate_id,
                            "decision": "rejected",
                            "reviewer": reviewer,
                        },
                    )

            await asyncio.sleep(poll_interval)

        # Timeout — clean up and fail
        await r.srem(_pending_key(self._tenant_id), pending_data)
        return ToolResult(
            content=f"Approval timed out after {timeout}s. Action '{action}' was not approved.",
            is_error=True,
            metadata={"gate_id": gate_id, "decision": "timeout"},
        )
