"""Fine-grained capabilities: role defaults plus tenant permission sets."""

from __future__ import annotations

import asyncio

import time
import uuid
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.governance import PermissionAssignment, PermissionSet
from models.user import User


@dataclass(frozen=True)
class Capability:
    key: str
    label: str
    group: str
    description: str


CATALOG: tuple[Capability, ...] = (
    Capability(
        "decisions.view",
        "View decisions",
        "Decisions",
        "See decision models, versions and their history.",
    ),
    Capability(
        "decisions.evaluate",
        "Evaluate decisions",
        "Decisions",
        "Run a published decision from the API, an agent or a pipeline.",
    ),
    Capability(
        "decisions.author",
        "Author decisions",
        "Decisions",
        "Create drafts, edit rules and run tests.",
    ),
    Capability(
        "decisions.review",
        "Review decisions",
        "Decisions",
        "Sign off, or reject, a decision version proposed for publication.",
    ),
    Capability(
        "decisions.publish",
        "Publish decisions",
        "Decisions",
        "Make an approved version effective.",
    ),
    Capability(
        "approvals.sign",
        "Sign approvals",
        "Approvals",
        "Sign approval gates. Add a suffix such as approvals.sign:legal to limit it to gates that ask for that group.",
    ),
    Capability(
        "risk.view",
        "View risk policies",
        "Risk",
        "See tier policies and why a run reached its tier.",
    ),
    Capability(
        "risk.manage",
        "Manage risk policies",
        "Risk",
        "Change what each risk tier requires.",
    ),
    Capability(
        "killswitch.manage",
        "Use kill switches",
        "Risk",
        "Stop and resume agents, pipelines, tools, triggers or models.",
    ),
    Capability(
        "audit.view", "View audit log", "Audit", "Read the tenant's activity log."
    ),
    Capability(
        "audit.verify",
        "Verify audit chain",
        "Audit",
        "Run the tamper check on the activity log.",
    ),
    Capability(
        "sources.manage",
        "Manage watched sources",
        "Sources",
        "Add and change monitored sources and their schedules.",
    ),
    Capability(
        "evals.manage",
        "Manage evaluation suites",
        "Evaluations",
        "Create suites, cases and release gates.",
    ),
    Capability(
        "evals.run",
        "Run evaluations",
        "Evaluations",
        "Run a suite against an agent, pipeline or decision.",
    ),
    Capability(
        "events.manage",
        "Manage event subscriptions",
        "Events",
        "Subscribe endpoints and triggers to platform events.",
    ),
    Capability(
        "permissions.manage",
        "Manage permission sets",
        "Administration",
        "Create permission sets and assign them to people.",
    ),
    Capability(
        "autonomy.view",
        "View autonomy",
        "Autonomy",
        "See what each agent may do on its own, its track record and the action ledger.",
    ),
    Capability(
        "autonomy.manage",
        "Manage autonomy",
        "Autonomy",
        "Enrol agents' actions, set how success is judged, demote or turn actions off.",
    ),
    Capability(
        "autonomy.grant",
        "Approve promotions",
        "Autonomy",
        "Approve an agent moving up a level. Never for an agent you built.",
    ),
    Capability(
        "actions.review",
        "Review agent actions",
        "Autonomy",
        "Answer watching reviews, record outcomes and flag harm.",
    ),
    Capability(
        "moderation.review",
        "Review held content",
        "Moderation",
        "Release, redact or reject messages and replies a moderation policy held for review.",
    ),
    Capability(
        "improvements.view",
        "View improvements",
        "Improvements",
        "See lessons, proposed fixes, their proof and releases in their watch period.",
    ),
    Capability(
        "improvements.propose",
        "Propose improvements",
        "Improvements",
        "Ask for a fix to a group of lessons, rerun a proof and roll a release back.",
    ),
    Capability(
        "improvements.approve",
        "Approve improvements",
        "Improvements",
        "Approve a proven fix so it is released. Never for an agent you built.",
    ),
    Capability(
        "feedback.give",
        "Give feedback",
        "Improvements",
        "Thumbs up or down and a correction on any agent answer.",
    ),
    Capability(
        "runs.replay",
        "Replay runs",
        "Runs",
        "Re-run an execution against its recorded inputs and versions.",
    ),
)
KEYS = frozenset(c.key for c in CATALOG)

ROLE_DEFAULTS: dict[str, frozenset[str]] = {
    "user": frozenset(
        {
            "decisions.view",
            "decisions.evaluate",
            "risk.view",
            "evals.run",
            "runs.replay",
            "autonomy.view",
            "actions.review",
            "feedback.give",
        }
    ),
    "creator": frozenset(
        {
            "decisions.view",
            "decisions.evaluate",
            "decisions.author",
            "risk.view",
            "evals.run",
            "evals.manage",
            "sources.manage",
            "events.manage",
            "runs.replay",
            "autonomy.view",
            "autonomy.manage",
            "actions.review",
            "improvements.view",
            "improvements.propose",
            "feedback.give",
        }
    ),
    "admin": frozenset({"*"}),
}

_TTL = 10.0
_cache: dict[uuid.UUID, tuple[float, frozenset[str]]] = {}
_loading: dict[uuid.UUID, asyncio.Lock] = {}


def valid_capability(cap: str) -> bool:
    base = cap.split(":", 1)[0]
    if base.endswith(".*"):
        return any(k.startswith(base[:-1]) for k in KEYS)
    return base in KEYS


def _role(user: User) -> str:
    return (user.role.value if hasattr(user.role, "value") else str(user.role)).lower()


def holds(granted: frozenset[str] | set[str], cap: str) -> bool:
    """True when a grant covers cap. approvals.sign covers approvals.sign:legal."""
    if "*" in granted or cap in granted:
        return True
    base, _, _qual = cap.partition(":")
    if base in granted:
        return True
    group = base.rsplit(".", 1)[0]
    return f"{group}.*" in granted


def invalidate(user_id: uuid.UUID | None = None) -> None:
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


async def capabilities_for(db: AsyncSession, user: User) -> frozenset[str]:
    hit = _cache.get(user.id)
    now = time.monotonic()
    if hit and now - hit[0] < _TTL:
        return hit[1]
    # one load per user when the entry expires under load, the rest wait for it
    lock = _loading.setdefault(user.id, asyncio.Lock())
    async with lock:
        hit = _cache.get(user.id)
        if hit and time.monotonic() - hit[0] < _TTL:
            return hit[1]
        return await _load(db, user)


async def _load(db: AsyncSession, user: User) -> frozenset[str]:
    now = time.monotonic()
    rows = (
        await db.execute(
            select(PermissionSet.capabilities)
            .join(
                PermissionAssignment,
                PermissionAssignment.permission_set_id == PermissionSet.id,
            )
            .where(
                PermissionAssignment.user_id == user.id,
                PermissionAssignment.tenant_id == user.tenant_id,
            )
        )
    ).all()
    caps = set(ROLE_DEFAULTS.get(_role(user), ROLE_DEFAULTS["user"]))
    for (granted,) in rows:
        caps.update(c for c in (granted or []) if isinstance(c, str))
    out = frozenset(caps)
    _cache[user.id] = (now, out)
    return out


async def has_capability(db: AsyncSession, user: User, cap: str) -> bool:
    return holds(await capabilities_for(db, user), cap)


def require_capability(cap: str) -> Callable:
    """Route dependency that 403s with the capability the caller lacks."""
    from app.core.deps import get_current_user, get_db

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await has_capability(db, user, cap):
            raise HTTPException(
                status_code=403,
                detail=f"This needs the {cap} capability. An admin can grant it under Admin, Permissions.",
            )
        return user

    return _check


def catalog_json() -> list[dict[str, str]]:
    return [
        {"key": c.key, "label": c.label, "group": c.group, "description": c.description}
        for c in CATALOG
    ]
