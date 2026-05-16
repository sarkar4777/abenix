"""Content-moderation API — OpenAI-backed, tenant-scoped."""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, update as sa_update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.moderation_policy import (
    ModerationAction,
    ModerationEvent,
    ModerationEventOutcome,
    ModerationPolicy,
)
from models.user import User, UserRole

# Engine-side imports — we reuse the same evaluate() the gate uses so
# /vet stays byte-identical to what an agent run would see.
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))
from engine.moderation_client import evaluate, content_hash  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/moderation", tags=["moderation"])


def _policy_dict(p: ModerationPolicy) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "tenant_id": str(p.tenant_id),
        "name": p.name,
        "description": p.description,
        "is_active": p.is_active,
        "pre_llm": p.pre_llm,
        "post_llm": p.post_llm,
        "on_tool_output": p.on_tool_output,
        "provider": p.provider,
        "provider_model": p.provider_model,
        "thresholds": p.thresholds or {},
        "default_threshold": float(p.default_threshold),
        "category_actions": p.category_actions or {},
        "default_action": (
            p.default_action.value
            if isinstance(p.default_action, ModerationAction)
            else str(p.default_action)
        ),
        "custom_patterns": p.custom_patterns or [],
        "redaction_mask": p.redaction_mask,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _event_dict(e: ModerationEvent) -> dict[str, Any]:
    pr = e.provider_response or {}
    return {
        "id": str(e.id),
        "tenant_id": str(e.tenant_id),
        "policy_id": str(e.policy_id) if e.policy_id else None,
        "user_id": str(e.user_id) if e.user_id else None,
        "execution_id": str(e.execution_id) if e.execution_id else None,
        "source": e.source,
        "outcome": (
            e.outcome.value
            if isinstance(e.outcome, ModerationEventOutcome)
            else str(e.outcome)
        ),
        "content_sha256": e.content_sha256,
        "content_preview": e.content_preview,
        "provider_response": pr,
        # Surface the provider error captured at vet-time so the UI can
        # render the underlying reason instead of a generic "error" badge.
        "provider_error": pr.get("_provider_error") if isinstance(pr, dict) else None,
        "acted_categories": e.acted_categories or [],
        "latency_ms": e.latency_ms,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


async def _active_policy(
    db: AsyncSession, tenant_id: uuid.UUID
) -> ModerationPolicy | None:
    q = (
        select(ModerationPolicy)
        .where(ModerationPolicy.tenant_id == tenant_id)
        .where(ModerationPolicy.is_active.is_(True))
        .order_by(desc(ModerationPolicy.updated_at))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()


@router.post("/vet")
async def vet(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Vet a piece of content against the tenant's active moderation policy."""
    content = str(body.get("content") or "").strip()
    if not content:
        return error("content is required", 400)
    strict = bool(body.get("strict"))
    overrides = body.get("policy_overrides") or {}

    policy = await _active_policy(db, user.tenant_id)

    # Merge: policy → overrides → strict-mode clamps
    thresholds = dict((policy.thresholds if policy else {}) or {})
    thresholds.update(overrides.get("thresholds") or {})
    default_threshold = overrides.get("default_threshold") or (
        float(policy.default_threshold) if policy else 0.5
    )
    category_actions = dict((policy.category_actions if policy else {}) or {})
    category_actions.update(overrides.get("category_actions") or {})
    default_action = overrides.get("default_action") or (
        (
            policy.default_action.value
            if policy and isinstance(policy.default_action, ModerationAction)
            else policy.default_action
        )
        if policy
        else "block"
    )
    custom_patterns = list((policy.custom_patterns if policy else []) or [])
    custom_patterns.extend(overrides.get("custom_patterns") or [])
    provider_model = overrides.get("provider_model") or (
        policy.provider_model if policy else "omni-moderation-latest"
    )
    redaction_mask = policy.redaction_mask if policy else "█████"

    if strict:
        default_threshold = min(default_threshold, 0.3)
        default_action = "block"

    decision = await evaluate(
        content,
        thresholds=thresholds,
        default_threshold=default_threshold,
        category_actions=category_actions,
        default_action=default_action,
        custom_patterns=custom_patterns,
        redaction_mask=redaction_mask,
        model=provider_model,
    )

    persisted_provider_response = dict(decision.provider_response or {})
    if decision.error:
        persisted_provider_response["_provider_error"] = decision.error
    event = ModerationEvent(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        policy_id=policy.id if policy else None,
        user_id=user.id,
        execution_id=None,
        source="api_vet",
        outcome=(
            ModerationEventOutcome(decision.outcome)
            if decision.outcome in [o.value for o in ModerationEventOutcome]
            else ModerationEventOutcome.ERROR
        ),
        content_sha256=content_hash(content),
        content_preview=content[:500],
        provider_response=persisted_provider_response,
        acted_categories=decision.triggered_categories,
        latency_ms=decision.latency_ms,
    )
    db.add(event)
    await db.flush()

    if decision.outcome in ("blocked", "flagged", "redacted"):
        await log_action(
            db,
            user.tenant_id,
            user.id,
            action=f"moderation_{decision.outcome}",
            details={
                "source": "api_vet",
                "categories": decision.triggered_categories,
                "reason": decision.reason,
            },
            request=request,
            resource_type="moderation_event",
            resource_id=str(event.id),
        )

    await db.commit()

    payload = {
        "event_id": str(event.id),
        "outcome": decision.outcome,
        "action": decision.action,
        "flagged": decision.flagged,
        "triggered_categories": decision.triggered_categories,
        "category_scores": {
            k: round(v, 4) for k, v in (decision.category_scores or {}).items()
        },
        "reason": decision.reason,
        "latency_ms": decision.latency_ms,
        "policy_id": str(policy.id) if policy else None,
        "strict": strict,
    }
    if decision.error:
        payload["provider_error"] = decision.error
    if decision.redacted_content is not None and decision.redacted_content != content:
        payload["redacted_content"] = decision.redacted_content
    return success(payload)


@router.get("/policies")
async def list_policies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = (
        select(ModerationPolicy)
        .where(ModerationPolicy.tenant_id == user.tenant_id)
        .order_by(desc(ModerationPolicy.updated_at))
    )
    rows = (await db.execute(q)).scalars().all()
    return success([_policy_dict(r) for r in rows])


@router.post("/policies")
async def create_policy(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role != UserRole.ADMIN:
        return error("only tenant admins can manage policies", 403)

    name = str(body.get("name") or "").strip()
    if not name:
        return error("name is required", 400)

    default_action_raw = str(body.get("default_action") or "block").lower()
    try:
        default_action_enum = ModerationAction(default_action_raw)
    except ValueError:
        return error(f"invalid default_action: {default_action_raw}", 400)

    # Respect "only one active at a time" semantics: if the new policy
    # is active, deactivate others.
    is_active = bool(body.get("is_active", True))
    if is_active:
        await db.execute(
            sa_update(ModerationPolicy)
            .where(ModerationPolicy.tenant_id == user.tenant_id)
            .where(ModerationPolicy.is_active.is_(True))
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )

    p = ModerationPolicy(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        name=name,
        description=body.get("description"),
        is_active=is_active,
        pre_llm=bool(body.get("pre_llm", True)),
        post_llm=bool(body.get("post_llm", True)),
        on_tool_output=bool(body.get("on_tool_output", False)),
        provider=str(body.get("provider") or "openai"),
        provider_model=str(body.get("provider_model") or "omni-moderation-latest"),
        thresholds=body.get("thresholds") or {},
        default_threshold=float(body.get("default_threshold") or 0.5),
        category_actions=body.get("category_actions") or {},
        default_action=default_action_enum,
        custom_patterns=body.get("custom_patterns") or [],
        redaction_mask=str(body.get("redaction_mask") or "█████"),
        created_by=user.id,
    )
    db.add(p)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        action="moderation_policy_created",
        details={"policy_id": str(p.id), "name": p.name, "is_active": p.is_active},
        request=request,
        resource_type="moderation_policy",
        resource_id=str(p.id),
    )
    await db.commit()
    return success(_policy_dict(p), status_code=201)


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        pid = uuid.UUID(policy_id)
    except ValueError:
        return error("invalid policy_id", 400)
    q = select(ModerationPolicy).where(
        ModerationPolicy.id == pid,
        ModerationPolicy.tenant_id == user.tenant_id,
    )
    row = (await db.execute(q)).scalars().first()
    if not row:
        return error("not found", 404)
    return success(_policy_dict(row))


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role != UserRole.ADMIN:
        return error("only tenant admins can manage policies", 403)
    try:
        pid = uuid.UUID(policy_id)
    except ValueError:
        return error("invalid policy_id", 400)
    q = select(ModerationPolicy).where(
        ModerationPolicy.id == pid,
        ModerationPolicy.tenant_id == user.tenant_id,
    )
    p = (await db.execute(q)).scalars().first()
    if not p:
        return error("not found", 404)

    # Enforce single-active: if toggling to active, deactivate others.
    if body.get("is_active") is True and not p.is_active:
        await db.execute(
            sa_update(ModerationPolicy)
            .where(ModerationPolicy.tenant_id == user.tenant_id)
            .where(ModerationPolicy.is_active.is_(True))
            .values(is_active=False, updated_at=datetime.now(timezone.utc))
        )

    fields = [
        "name",
        "description",
        "is_active",
        "pre_llm",
        "post_llm",
        "on_tool_output",
        "provider",
        "provider_model",
        "thresholds",
        "default_threshold",
        "category_actions",
        "custom_patterns",
        "redaction_mask",
    ]
    for k in fields:
        if k in body:
            setattr(p, k, body[k])
    if "default_action" in body:
        try:
            p.default_action = ModerationAction(str(body["default_action"]).lower())
        except ValueError:
            return error(f"invalid default_action: {body['default_action']}", 400)
    p.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        action="moderation_policy_updated",
        details={"policy_id": str(p.id), "fields": list(body.keys())},
        request=request,
        resource_type="moderation_policy",
        resource_id=str(p.id),
    )
    await db.commit()
    return success(_policy_dict(p))


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role != UserRole.ADMIN:
        return error("only tenant admins can manage policies", 403)
    try:
        pid = uuid.UUID(policy_id)
    except ValueError:
        return error("invalid policy_id", 400)
    q = select(ModerationPolicy).where(
        ModerationPolicy.id == pid,
        ModerationPolicy.tenant_id == user.tenant_id,
    )
    p = (await db.execute(q)).scalars().first()
    if not p:
        return error("not found", 404)
    await db.delete(p)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        action="moderation_policy_deleted",
        details={"policy_id": str(pid)},
        request=request,
        resource_type="moderation_policy",
        resource_id=str(pid),
    )
    await db.commit()
    return success({"deleted": True})


@router.get("/events")
async def list_events(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    outcome: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> JSONResponse:
    q = select(ModerationEvent).where(ModerationEvent.tenant_id == user.tenant_id)
    if outcome:
        try:
            q = q.where(ModerationEvent.outcome == ModerationEventOutcome(outcome))
        except ValueError:
            return error(f"invalid outcome: {outcome}", 400)
    if source:
        q = q.where(ModerationEvent.source == source)
    q = q.order_by(desc(ModerationEvent.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return success([_event_dict(r) for r in rows])
