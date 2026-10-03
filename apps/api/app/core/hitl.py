"""HITL gate helpers shared by the executions and approvals routers.

The runtime's human_approval tool parks on Redis: a pending entry in the
tenant set, a decision key the tool polls, and a waiting marker the stale
sweeper honours. Key shapes must match engine/tools/human_approval.py.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

APPROVER_ROLES = ("admin", "creator")

HITL_ID_PREFIX = "hitl:"
DECISION_TTL_SECONDS = 7200

_redis: aioredis.Redis | None = None


def approval_key(execution_id: str, gate_id: str) -> str:
    return f"hitl:approval:{execution_id}:{gate_id}"


def pending_key(tenant_id: str) -> str:
    return f"hitl:pending:{tenant_id}"


def waiting_key(execution_id: str) -> str:
    return f"hitl:waiting:{execution_id}"


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def hitl_row_id(execution_id: str, gate_id: str) -> str:
    return f"{HITL_ID_PREFIX}{execution_id}:{gate_id}"


def parse_hitl_id(approval_id: str) -> tuple[str, str] | None:
    """Split "hitl:{execution_id}:{gate_id}" or return None for plain ids."""
    if not approval_id.startswith(HITL_ID_PREFIX):
        return None
    rest = approval_id[len(HITL_ID_PREFIX) :]
    execution_id, sep, gate_id = rest.partition(":")
    if not sep or not execution_id or not gate_id:
        return None
    return execution_id, gate_id


async def list_pending_hitl(tenant_id: str) -> list[dict[str, Any]]:
    """Undecided, unexpired gates for a tenant. Expired entries are pruned."""
    r = await get_redis()
    key = pending_key(str(tenant_id))
    members = await r.smembers(key)
    now = time.time()
    out: list[dict[str, Any]] = []
    for member in members:
        try:
            data = json.loads(member)
        except (TypeError, ValueError):
            await r.srem(key, member)
            continue
        expires_at = data.get("expires_at")
        if expires_at and float(expires_at) < now:
            await r.srem(key, member)
            continue
        decided = await r.get(
            approval_key(str(data.get("execution_id")), str(data.get("gate_id")))
        )
        if decided:
            continue
        out.append(data)
    out.sort(key=lambda d: d.get("requested_at") or 0, reverse=True)
    return out


async def get_pending_hitl(
    tenant_id: str, execution_id: str, gate_id: str
) -> dict[str, Any] | None:
    for entry in await list_pending_hitl(tenant_id):
        if (
            str(entry.get("execution_id")) == execution_id
            and entry.get("gate_id") == gate_id
        ):
            return entry
    return None


async def write_hitl_decision(
    *,
    execution_id: str,
    gate_id: str,
    decision: str,
    reviewer: str,
    reviewer_id: str,
    tenant_id: str,
    comment: str = "",
) -> bool:
    """Record a decision once. Returns False when the gate was already decided."""
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    r = await get_redis()
    payload = json.dumps(
        {
            "decision": decision,
            "reviewer": reviewer,
            "reviewer_id": reviewer_id,
            "tenant_id": str(tenant_id),
            "comment": comment or "",
            "decided_at": time.time(),
        }
    )
    ok = await r.set(
        approval_key(execution_id, gate_id), payload, ex=DECISION_TTL_SECONDS, nx=True
    )
    return bool(ok)


async def waiting_execution_ids(execution_ids: list[str]) -> set[str]:
    """Subset of execution ids that currently sit on a HITL gate."""
    if not execution_ids:
        return set()
    r = await get_redis()
    pipe = r.pipeline()
    for ex_id in execution_ids:
        pipe.exists(waiting_key(str(ex_id)))
    flags = await pipe.execute()
    return {str(ex_id) for ex_id, flag in zip(execution_ids, flags) if flag}


def hitl_to_approval_row(entry: dict[str, Any]) -> dict[str, Any]:
    """Shape a Redis gate entry like a serialized Approval row."""
    execution_id = str(entry.get("execution_id") or "")
    gate_id = str(entry.get("gate_id") or "")
    requested_at = entry.get("requested_at")
    expires_at = entry.get("expires_at")

    def _iso(ts: Any) -> str | None:
        if not ts:
            return None
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()

    return {
        "id": hitl_row_id(execution_id, gate_id),
        "agent_id": None,
        "agent_execution_id": execution_id or None,
        "title": entry.get("action") or "Approval requested",
        "payload": {
            "details": entry.get("details") or "",
            "risk_level": entry.get("risk_level") or "medium",
            "agent_name": entry.get("agent_name") or "",
        },
        "required_signoffs": 1,
        "signoffs": [],
        "status": "pending",
        "requested_by": entry.get("requested_by"),
        "expires_at": _iso(expires_at),
        "decided_at": None,
        "created_at": _iso(requested_at),
        "gate_kind": "human_approval",
        "client_token": None,
    }


def _role_of(user: Any) -> str:
    role = getattr(user, "role", "")
    return str(getattr(role, "value", role)).lower()


def can_approve(user: Any) -> bool:
    return _role_of(user) in APPROVER_ROLES


async def approver_denial(
    db: AsyncSession,
    user: Any,
    requester_id: uuid.UUID | str | None,
    policy: dict[str, Any] | None = None,
    gate_kind: str | None = None,
) -> str | None:
    """Reason the caller may not sign off, or None when allowed.

    Without a policy, admins and creators sign off and a requester approving
    their own request is recorded as self_approved. A policy, set from the
    risk tier, adds separation of duties: a signing capability and, when
    asked, no approving your own change. Publishing a decision also needs
    decisions.review.
    """
    if gate_kind == "decision_publish":
        from app.core.capabilities import has_capability

        if not await has_capability(db, user, "decisions.review"):
            return "Approving a decision for publication needs the decisions.review capability. An admin can grant it under Admin, Permissions."
    if policy:
        from app.core.capabilities import has_capability

        cap = str(policy.get("capability") or "approvals.sign")
        if not await has_capability(db, user, cap):
            return f"This approval needs the {cap} capability. An admin can grant it under Admin, Permissions."
        if policy.get("exclude_requester") and is_self_approval(user, requester_id):
            return "You requested this change, so someone else has to approve it."
        return None
    if not can_approve(user):
        return "Only admins and creators can sign off on approvals"
    return None


def is_self_approval(user: Any, requester_id: uuid.UUID | str | None) -> bool:
    return requester_id is not None and str(requester_id) == str(user.id)
