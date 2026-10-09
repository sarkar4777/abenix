"""Needs you: what is waiting on the current user, counted per inbox tab."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import capabilities_for, holds
from app.core.deps import get_current_user, get_db
from app.core.permissions import features_for, is_admin
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus  # noqa: E402
from models.approval import Approval, ApprovalStatus  # noqa: E402
from models.autonomy import AgentAction  # noqa: E402
from models.execution import Execution, ExecutionStatus  # noqa: E402
from models.moderation_policy import ModerationReview  # noqa: E402
from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/me", tags=["inbox"])

TABS = ("approvals", "proposals", "watching", "held", "marketplace", "alerts")
# improvement releases get their own tab, not counted under approvals
RELEASE_GATE = "improvement.release"
TTL_SECONDS = 15.0
_MAX_CACHED = 5000
_cache: dict[uuid.UUID, tuple[float, dict[str, Any]]] = {}

SIDEBAR_MODES = ("essentials", "all")


def invalidate(user_id: uuid.UUID | None = None) -> None:
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


def _role(user: Any) -> str:
    role = getattr(user, "role", "")
    return str(getattr(role, "value", role)).lower()


def _signer(user: Any, caps: frozenset[str]) -> bool:
    return _role(user) in ("admin", "creator") or holds(caps, "approvals.sign")


def can_sign(
    user: Any,
    caps: frozenset[str],
    *,
    requested_by: Any,
    policy: dict[str, Any] | None,
    gate_kind: str | None,
    signoffs: list[dict[str, Any]] | None,
    agent_creator_id: str | None = None,
    self_approval: str | None = None,
) -> bool:
    """Mirrors approver_denial and promotion_denial without touching the database."""
    me = str(user.id)
    if any(str(s.get("user_id")) == me for s in signoffs or []):
        return False
    if gate_kind == "decision_publish" and not holds(caps, "decisions.review"):
        return False
    if (
        gate_kind in ("autonomy.promote", RELEASE_GATE)
        and agent_creator_id == me
        and not self_approval
    ):
        return False
    if policy:
        if not holds(caps, str(policy.get("capability") or "approvals.sign")):
            return False
        return not (policy.get("exclude_requester") and str(requested_by) == me)
    return _signer(user, caps)


async def _signable_kinds(
    db: AsyncSession, user: Any, caps: frozenset[str]
) -> list[str | None]:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(
                Approval.requested_by,
                Approval.policy,
                Approval.gate_kind,
                Approval.signoffs,
                Approval.payload["agent_creator_id"].astext,
                Approval.payload["self_approval"].astext,
            )
            .where(
                Approval.tenant_id == user.tenant_id,
                Approval.status == ApprovalStatus.pending,
                or_(Approval.expires_at.is_(None), Approval.expires_at > now),
            )
            .limit(500)
        )
    ).all()
    return [
        r[2]
        for r in rows
        if can_sign(
            user,
            caps,
            requested_by=r[0],
            policy=r[1],
            gate_kind=r[2],
            signoffs=r[3],
            agent_creator_id=r[4],
            self_approval=r[5],
        )
    ]


async def _approvals(db: AsyncSession, user: Any, caps: frozenset[str], kinds) -> int:
    n = sum(1 for k in await kinds() if k != RELEASE_GATE)
    if _signer(user, caps):
        from app.core.hitl import list_pending_hitl

        try:
            n += len(await list_pending_hitl(str(user.tenant_id)))
        except Exception as e:  # noqa: BLE001 — redis down only hides agent gates
            logger.warning("inbox: hitl gates unavailable: %s", e)
    return n


async def _watching(db: AsyncSession, user: Any) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    AgentAction.tenant_id == user.tenant_id,
                    AgentAction.status == "watching",
                    AgentAction.reviewer_answer.is_(None),
                )
            )
        ).scalar()
        or 0
    )


async def _held(db: AsyncSession, user: Any) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    ModerationReview.tenant_id == user.tenant_id,
                    ModerationReview.status == "pending",
                )
            )
        ).scalar()
        or 0
    )


async def _marketplace(db: AsyncSession, user: Any) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    Agent.tenant_id == user.tenant_id,
                    Agent.status == AgentStatus.PENDING_REVIEW,
                )
            )
        ).scalar()
        or 0
    )


async def rising_failures(db: AsyncSession, user: Any) -> list[dict[str, Any]]:
    """Failure causes that are new today or up on the day before."""
    now = datetime.now(timezone.utc)
    day = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(
                Execution.failure_code,
                func.count().filter(Execution.created_at >= day),
                func.count().filter(Execution.created_at < day),
                func.max(Execution.created_at),
                func.max(Execution.error_message),
            )
            .where(
                Execution.tenant_id == user.tenant_id,
                Execution.status == ExecutionStatus.FAILED,
                Execution.created_at >= now - timedelta(hours=48),
            )
            .group_by(Execution.failure_code)
        )
    ).all()
    out = []
    for code, today, before, latest, sample in rows:
        today, before = int(today or 0), int(before or 0)
        if today <= before:
            continue
        out.append(
            {
                "failure_code": code or "UNKNOWN_ERROR",
                "count": today,
                "previous": before,
                "trend": "new" if before == 0 else "rising",
                "latest_at": latest.isoformat() if latest else None,
                "sample_message": (sample or "")[:300],
            }
        )
    out.sort(key=lambda g: g["count"], reverse=True)
    return out


async def compute_counts(db: AsyncSession, user: Any) -> dict[str, Any]:
    caps = await capabilities_for(db, user)
    feats = features_for(user)
    memo: dict[str, list[str | None]] = {}

    async def kinds() -> list[str | None]:
        # one approvals query feeds both the approvals and proposals tabs
        if "k" not in memo:
            memo["k"] = await _signable_kinds(db, user, caps)
        return memo["k"]

    async def _proposals() -> int:
        return sum(1 for k in await kinds() if k == RELEASE_GATE)

    sources: dict[str, Any] = {"approvals": lambda: _approvals(db, user, caps, kinds)}
    if holds(caps, "improvements.approve"):
        sources["proposals"] = _proposals
    if holds(caps, "actions.review"):
        sources["watching"] = lambda: _watching(db, user)
    if holds(caps, "moderation.review"):
        sources["held"] = lambda: _held(db, user)
    if is_admin(user):
        from app.core.platform_features import marketplace_enabled

        try:
            on = await marketplace_enabled(db)
        except Exception:  # noqa: BLE001
            on = False
        if on:
            sources["marketplace"] = lambda: _marketplace(db, user)
    if feats.get("view_alerts"):

        async def _alerts() -> int:
            return len(await rising_failures(db, user))

        sources["alerts"] = _alerts

    counts: dict[str, int] = {}
    failed: list[str] = []
    for key, run in sources.items():
        try:
            counts[key] = int(await run())
        except (
            Exception
        ) as e:  # noqa: BLE001 — one broken source never blanks the inbox
            logger.warning("inbox: %s count failed: %s", key, e)
            await db.rollback()
            counts[key] = 0
            failed.append(key)
    return {
        "total": sum(counts.values()),
        "counts": counts,
        "available": [k for k in TABS if k in counts],
        "unavailable": failed,
    }


@router.get("/inbox-counts")
async def inbox_counts(
    fresh: bool = Query(False, description="Skip the short per-user cache"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    now = time.monotonic()
    hit = _cache.get(user.id)
    if hit and not fresh and now - hit[0] < TTL_SECONDS:
        return success({**hit[1], "cached": True})
    data = await compute_counts(db, user)
    if len(_cache) >= _MAX_CACHED:
        _cache.clear()
    _cache[user.id] = (now, data)
    return success({**data, "cached": False})


@router.get("/inbox/alerts")
async def inbox_alerts(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not features_for(user).get("view_alerts"):
        return error("Alerts are not turned on for your role.", 403)
    return success(await rising_failures(db, user))


def _ui_prefs(user: Any) -> dict[str, Any]:
    ui = (getattr(user, "notification_settings", None) or {}).get("ui") or {}
    mode = ui.get("sidebar_mode")
    return {"sidebar_mode": mode if mode in SIDEBAR_MODES else "essentials"}


@router.get("/ui-prefs")
async def get_ui_prefs(user: User = Depends(get_current_user)) -> JSONResponse:
    return success(_ui_prefs(user))


@router.put("/ui-prefs")
async def put_ui_prefs(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    mode = body.get("sidebar_mode")
    if mode not in SIDEBAR_MODES:
        return error("sidebar_mode must be essentials or all", 400)
    prefs = dict(user.notification_settings or {})
    prefs["ui"] = {**(prefs.get("ui") or {}), "sidebar_mode": mode}
    user.notification_settings = prefs
    await db.commit()
    return success(_ui_prefs(user))
