"""Approvals API — backend-enforced multi-step sign-off.

Status flips to ``approved`` once at least ``required_signoffs`` rows in the
JSONB ``signoffs`` array carry decision=``approve``. A single ``deny`` flips
status to ``denied``. The ``approval_gate`` runtime tool long-polls
``GET /api/approvals/{id}`` so it sees status transitions.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.deps import get_current_user, get_db
from app.core.hitl import (
    approver_denial,
    is_self_approval,
    get_pending_hitl,
    hitl_row_id,
    hitl_to_approval_row,
    list_pending_hitl,
    parse_hitl_id,
    write_hitl_decision,
)
from app.core.notifications import create_notification
from app.core.responses import error, success
from app.schemas.connectors import (
    ApprovalCreate,
    ApprovalSignoffRequest,
    ApprovalWebhookConfig,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.approval import Approval, ApprovalStatus  # noqa: E402
from models.execution import Execution  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def _serialize(a: Approval) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "agent_id": str(a.agent_id) if a.agent_id else None,
        "agent_execution_id": (
            str(a.agent_execution_id) if a.agent_execution_id else None
        ),
        "title": a.title or "",
        "payload": a.payload or {},
        "required_signoffs": a.required_signoffs,
        "signoffs": a.signoffs or [],
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "requested_by": str(a.requested_by) if a.requested_by else None,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "gate_kind": a.gate_kind,
        "policy": a.policy,
        "client_token": a.client_token,
    }


def _evaluate_status(a: Approval) -> ApprovalStatus:
    """Walk the signoffs array and return the new status. Pure function."""
    signoffs = a.signoffs or []
    approve_count = sum(1 for s in signoffs if s.get("decision") == "approve")
    deny_count = sum(1 for s in signoffs if s.get("decision") == "deny")
    if deny_count > 0:
        return ApprovalStatus.denied
    if any(s.get("decision") == "return" for s in signoffs):
        return ApprovalStatus.returned
    if approve_count >= a.required_signoffs:
        return ApprovalStatus.approved
    if a.expires_at and a.expires_at < datetime.now(timezone.utc):
        return ApprovalStatus.expired
    return ApprovalStatus.pending


async def _tier_floor(
    db: AsyncSession, user: User, body: Any
) -> tuple[int, dict | None]:
    """Sign-offs and signing rules for a new approval: what was asked, raised to the tier's policy."""
    from engine import governance, risk

    tier = body.risk_tier
    if not tier and body.agent_execution_id:
        from models.execution import Execution

        tier = (
            await db.execute(
                select(Execution.risk_tier).where(
                    Execution.id == body.agent_execution_id,
                    Execution.tenant_id == user.tenant_id,
                )
            )
        ).scalar()
    if not tier or risk.normalize(tier) == "low":
        return body.required_signoffs, None
    await governance.ensure_fresh()
    pol = (
        governance.policy(str(user.tenant_id), risk.normalize(tier)).get(
            "publish_approvals"
        )
        or {}
    )
    floor = int(pol.get("min_approvers") or 0)
    policy = {
        "exclude_requester": bool(pol.get("exclude_author")),
        "capability": pol.get("capability") or "approvals.sign",
        "risk_tier": risk.normalize(tier),
        "escalate_after_hours": int(pol.get("escalate_after_hours") or 0),
    }
    return max(body.required_signoffs, floor), policy


async def escalate_overdue(db: AsyncSession) -> int:
    """Tell a tenant's admins once about each tiered approval nobody has acted on in time."""
    now = datetime.now(timezone.utc)
    rows = (
        (
            await db.execute(
                select(Approval).where(
                    Approval.status == ApprovalStatus.pending,
                    Approval.escalated_at.is_(None),
                    Approval.policy.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for a in rows:
        hours = int((a.policy or {}).get("escalate_after_hours") or 0)
        if hours <= 0 or a.created_at + timedelta(hours=hours) > now:
            continue
        admins = (
            (
                await db.execute(
                    select(User.id).where(
                        User.tenant_id == a.tenant_id,
                        User.role == "admin",
                        User.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        got = len(a.signoffs or [])
        for uid in admins:
            await create_notification(
                db,
                tenant_id=a.tenant_id,
                user_id=uid,
                type="system_alert",
                title=f"Approval waiting over {hours}h: {a.title or 'untitled'}",
                message=f"{got} of {a.required_signoffs} sign-offs so far. It is {a.policy.get('risk_tier', 'tiered')} risk, so it needs someone to act.",
                link="/approvals",
                metadata={"approval_id": str(a.id)},
            )
        a.escalated_at = now
        sent += 1
    await db.commit()
    return sent


async def _expire_stale(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Sweep pending rows past their deadline. Cheap inline call from list/get."""
    from app.services.events import emit

    now = datetime.now(timezone.utc)
    expired = (
        await db.execute(
            update(Approval)
            .where(
                Approval.tenant_id == tenant_id,
                Approval.status == ApprovalStatus.pending,
                Approval.expires_at.isnot(None),
                Approval.expires_at < now,
            )
            .values(status=ApprovalStatus.expired, decided_at=now)
            .returning(Approval.id, Approval.title, Approval.gate_kind)
        )
    ).all()
    for aid, title, gate_kind in expired:
        await emit(
            db,
            tenant_id,
            "approval.resolved",
            {
                "approval_id": str(aid),
                "status": ApprovalStatus.expired.value,
                "gate_kind": gate_kind,
                "title": title,
            },
        )
    await db.commit()
    for aid, _, gate_kind in expired:
        if gate_kind == "decision_publish":
            from app.routers.decisions import on_approval_resolved

            row = await db.get(Approval, aid)
            if row is not None:
                await on_approval_resolved(db, row)


@router.post("")
async def create_approval(
    body: ApprovalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.client_token:
        existing = await db.execute(
            select(Approval).where(
                Approval.tenant_id == user.tenant_id,
                Approval.client_token == body.client_token,
            )
        )
        prior = existing.scalar_one_or_none()
        if prior is not None:
            return success(_serialize(prior), status_code=200)

    expires_at = None
    if body.expires_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=body.expires_seconds
        )
    required, policy = await _tier_floor(db, user, body)
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=body.agent_id,
        agent_execution_id=body.agent_execution_id,
        title=body.title,
        payload=body.payload,
        required_signoffs=required,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=expires_at,
        gate_kind=body.gate_kind,
        client_token=body.client_token,
        policy=policy,
    )
    db.add(a)
    await db.flush()
    from app.services.events import emit

    await emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": a.gate_kind,
            "required_signoffs": a.required_signoffs,
        },
    )
    await db.commit()
    await db.refresh(a)
    await _notify_pending(db, a, requester=user)
    return success(_serialize(a), status_code=201)


@router.get("")
async def list_approvals(
    mine: int = Query(
        0,
        description="If 1, restrict to approvals the caller has rights to act on (tenant scope today)",
    ),
    status: str | None = Query(
        None, description="pending | approved | denied | expired"
    ),
    execution_id: uuid.UUID | None = Query(
        None, description="Filter to approvals linked to a specific execution"
    ),
    agent_id: uuid.UUID | None = Query(
        None, description="Filter to approvals raised by a specific agent"
    ),
    kind: str | None = Query(None, description="Filter by gate_kind discriminator"),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await _expire_stale(db, user.tenant_id)
    stmt = select(Approval).where(Approval.tenant_id == user.tenant_id)
    if status:
        try:
            stmt = stmt.where(Approval.status == ApprovalStatus(status))
        except ValueError:
            return error(f"Invalid status: {status}", 400)
    if execution_id is not None:
        stmt = stmt.where(Approval.agent_execution_id == execution_id)
    if agent_id is not None:
        stmt = stmt.where(Approval.agent_id == agent_id)
    if kind:
        stmt = stmt.where(Approval.gate_kind == kind)
    stmt = stmt.order_by(Approval.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    _ = mine  # tenant scope is enough for now; keep param for future per-user routing
    items = [_serialize(a) for a in rows]

    # Runtime human_approval gates live in Redis, not in the approvals table
    include_hitl = (
        (status is None or status == "pending")
        and (kind is None or kind == "human_approval")
        and agent_id is None
    )
    if include_hitl:
        try:
            gates = await list_pending_hitl(str(user.tenant_id))
        except Exception as e:
            logger.warning("hitl pending list unavailable: %s", e)
            gates = []
        for g in gates:
            if execution_id is not None and str(g.get("execution_id")) != str(
                execution_id
            ):
                continue
            items.append(hitl_to_approval_row(g))
        items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        items = items[:limit]
    return success(items)


async def _hitl_execution(
    db: AsyncSession, user: User, execution_id: str
) -> Execution | None:
    try:
        ex_uuid = uuid.UUID(execution_id)
    except ValueError:
        return None
    res = await db.execute(
        select(Execution).where(
            Execution.id == ex_uuid, Execution.tenant_id == user.tenant_id
        )
    )
    return res.scalar_one_or_none()


async def _hitl_history_row(
    db: AsyncSession, tenant_id: uuid.UUID, execution_id: str, gate_id: str
) -> Approval | None:
    res = await db.execute(
        select(Approval).where(
            Approval.tenant_id == tenant_id,
            Approval.client_token == hitl_row_id(execution_id, gate_id),
        )
    )
    return res.scalar_one_or_none()


async def _hitl_snapshot(
    db: AsyncSession, user: User, execution_id: str, gate_id: str
) -> dict[str, Any] | None:
    """Pending gate as a row, the recorded decision row, or None."""
    exec_row = await _hitl_execution(db, user, execution_id)
    if exec_row is None:
        return None
    pending = await get_pending_hitl(str(user.tenant_id), execution_id, gate_id)
    if pending is not None:
        row = hitl_to_approval_row(pending)
        row["requested_by"] = str(exec_row.user_id) if exec_row.user_id else None
        return row
    history = await _hitl_history_row(db, user.tenant_id, execution_id, gate_id)
    if history is not None:
        return _serialize(history)
    return None


@router.get("/webhooks")
async def get_webhook(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    settings = await _tenant_settings(db, user.tenant_id)
    return success(
        {
            "url": settings.get("approval_webhook_url"),
            "has_secret": bool(settings.get("approval_webhook_secret")),
        }
    )


@router.put("/webhooks")
async def set_webhook(
    body: ApprovalWebhookConfig,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if user.role.value not in ("admin", "owner"):
        return error("Only tenant admins can configure approval webhooks", 403)
    res = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = res.scalar_one_or_none()
    if not tenant:
        return error("Tenant not found", 404)
    settings = dict(tenant.settings or {})
    if body.url is None:
        settings.pop("approval_webhook_url", None)
    else:
        settings["approval_webhook_url"] = body.url.strip() or None
    if body.secret is not None:
        if body.secret == "":
            settings.pop("approval_webhook_secret", None)
        else:
            settings["approval_webhook_secret"] = crypto.encrypt(tenant.id, body.secret)
    from sqlalchemy.orm.attributes import flag_modified

    tenant.settings = settings
    flag_modified(tenant, "settings")
    await db.commit()
    return success(
        {
            "url": settings.get("approval_webhook_url"),
            "has_secret": bool(settings.get("approval_webhook_secret")),
        }
    )


def _parse_approval_id(approval_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(approval_id)
    except (ValueError, TypeError):
        return None


@router.get("/{approval_id}")
async def get_approval(
    approval_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    hitl = parse_hitl_id(approval_id)
    if hitl:
        row = await _hitl_snapshot(db, user, *hitl)
        return success(row) if row else error("Approval not found", 404)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)
    if (
        a.status == ApprovalStatus.pending
        and a.expires_at
        and a.expires_at < datetime.now(timezone.utc)
    ):
        a.status = ApprovalStatus.expired
        a.decided_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(a)
    return success(_serialize(a))


@router.get("/{approval_id}/wait")
async def wait_for_approval(
    approval_id: str,
    timeout_seconds: int = Query(30, ge=1, le=120),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Long-poll a single approval until status leaves pending or timeout fires.

    SDK consumers call this from a worker that picked up an `approval_id`
    out-of-band (queue, webhook, scheduled job) and want the resolved row
    without burning CPU on a 2-second loop.
    """
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    hitl = parse_hitl_id(approval_id)
    if hitl:
        while True:
            row = await _hitl_snapshot(db, user, *hitl)
            if row is None:
                return error("Approval not found", 404)
            if row.get("status") != "pending" or datetime.now(timezone.utc) >= deadline:
                return success(row)
            await asyncio.sleep(1.0)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    while True:
        result = await db.execute(
            select(Approval).where(
                Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
            )
        )
        a = result.scalar_one_or_none()
        if not a:
            return error("Approval not found", 404)
        if (
            a.status == ApprovalStatus.pending
            and a.expires_at
            and a.expires_at < datetime.now(timezone.utc)
        ):
            a.status = ApprovalStatus.expired
            a.decided_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(a)
        if a.status != ApprovalStatus.pending:
            return success(_serialize(a))
        if datetime.now(timezone.utc) >= deadline:
            return success(_serialize(a))
        await asyncio.sleep(1.0)


async def _sign_off_hitl(
    db: AsyncSession,
    user: User,
    execution_id: str,
    gate_id: str,
    body: ApprovalSignoffRequest,
) -> JSONResponse:
    exec_row = await _hitl_execution(db, user, execution_id)
    if exec_row is None:
        return error("Approval not found", 404)
    history = await _hitl_history_row(db, user.tenant_id, execution_id, gate_id)
    if history is not None:
        return error(f"Approval is already {history.status.value}", 409)
    pending = await get_pending_hitl(str(user.tenant_id), execution_id, gate_id)
    if pending is None:
        return error("Approval not found", 404)
    denial = await approver_denial(db, user, exec_row.user_id)
    if denial:
        return error(denial, 403)

    decision = "approved" if body.decision == "approve" else "rejected"
    written = await write_hitl_decision(
        execution_id=execution_id,
        gate_id=gate_id,
        decision=decision,
        reviewer=user.full_name or user.email,
        reviewer_id=str(user.id),
        tenant_id=str(user.tenant_id),
        comment=body.reason or "",
    )
    if not written:
        return error("Approval is already decided", 409)

    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "user_id": str(user.id),
        "user_email": user.email,
        "decision": body.decision,
        "reason": body.reason or "",
        "at": now.isoformat(),
    }
    if body.client_token:
        record["client_token"] = body.client_token
    # History row so the decision shows under recent decisions and notifies the requester
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=exec_row.agent_id,
        agent_execution_id=exec_row.id,
        title=pending.get("action") or "Approval requested",
        payload={
            "details": pending.get("details") or "",
            "risk_level": pending.get("risk_level") or "medium",
            "agent_name": pending.get("agent_name") or "",
            "gate_id": gate_id,
        },
        required_signoffs=1,
        signoffs=[record],
        status=(
            ApprovalStatus.approved if decision == "approved" else ApprovalStatus.denied
        ),
        requested_by=exec_row.user_id,
        expires_at=None,
        decided_at=now,
        gate_kind="human_approval",
        client_token=hitl_row_id(execution_id, gate_id),
    )
    requested_at = pending.get("requested_at")
    if requested_at:
        a.created_at = datetime.fromtimestamp(float(requested_at), tz=timezone.utc)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    await _notify_resolved(db, a, decider=user)
    return success(_serialize(a))


@router.post("/{approval_id}/signoff")
async def sign_off(
    approval_id: str,
    body: ApprovalSignoffRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.decision not in ("approve", "deny", "return"):
        return error("decision must be approve, deny or return", 400)
    if body.decision == "return" and not (body.reason or "").strip():
        return error("Say what needs to change, so the requester can correct it.", 400)
    hitl = parse_hitl_id(approval_id)
    if hitl:
        return await _sign_off_hitl(db, user, hitl[0], hitl[1], body)
    approval_uuid = _parse_approval_id(approval_id)
    if approval_uuid is None:
        return error("Approval not found", 404)
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_uuid, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)

    if body.client_token:
        for s in a.signoffs or []:
            if s.get("client_token") == body.client_token:
                return success(_serialize(a))

    if a.status != ApprovalStatus.pending:
        return error(f"Approval is already {a.status.value}", 409)

    denial = await approver_denial(db, user, a.requested_by, a.policy)
    if denial:
        return error(denial, 403)

    signoffs = list(a.signoffs or [])
    if any(s.get("user_id") == str(user.id) for s in signoffs):
        return error("User has already signed off on this approval", 409)
    record: dict[str, Any] = {
        "user_id": str(user.id),
        "user_email": user.email,
        "decision": body.decision,
        "reason": body.reason or "",
        "at": datetime.now(timezone.utc).isoformat(),
        "self_approved": is_self_approval(user, a.requested_by),
    }
    if body.client_token:
        record["client_token"] = body.client_token
    signoffs.append(record)
    a.signoffs = signoffs
    prev_status = a.status
    new_status = _evaluate_status(a)
    a.status = new_status
    if new_status != ApprovalStatus.pending:
        a.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(a)
    if prev_status == ApprovalStatus.pending and new_status != ApprovalStatus.pending:
        from app.services.events import emit

        await emit(
            db,
            a.tenant_id,
            "approval.resolved",
            {
                "approval_id": str(a.id),
                "status": new_status.value,
                "gate_kind": a.gate_kind,
                "title": a.title,
            },
        )
        await db.commit()
        if a.gate_kind == "decision_publish":
            from app.routers.decisions import on_approval_resolved

            await on_approval_resolved(db, a)
        await _notify_resolved(db, a, decider=user)
    return success(_serialize(a))


async def _tenant_settings(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any]:
    res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = res.scalar_one_or_none()
    return dict(tenant.settings or {}) if tenant else {}


async def _post_webhook(
    settings: dict[str, Any],
    event: str,
    payload: dict[str, Any],
    tenant_id: uuid.UUID | str | None = None,
) -> None:
    url = (settings.get("approval_webhook_url") or "").strip()
    if not url:
        return
    secret = settings.get("approval_webhook_secret") or ""
    if secret and tenant_id is not None:
        secret = crypto.decrypt(tenant_id, secret)
    body = {"event": event, "data": payload}
    headers = {"Content-Type": "application/json"}
    if secret:
        import hashlib
        import hmac
        import json as _json

        raw = _json.dumps(body, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-Abenix-Signature"] = f"sha256={sig}"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=body, headers=headers)
    except Exception as e:
        logger.warning("approval webhook to %s failed: %s", url, e)


async def _notify_pending(
    db: AsyncSession, approval: Approval, *, requester: User
) -> None:
    """Tell every other user in the tenant a new approval needs their attention."""
    res = await db.execute(
        select(User).where(
            User.tenant_id == approval.tenant_id,
            User.is_active.is_(True),
            User.id != requester.id,
        )
    )
    targets = res.scalars().all()
    title = approval.title or "Approval requested"
    truncated_title = title if len(title) <= 80 else title[:77] + "..."
    requester_name = requester.full_name or requester.email or "An agent"
    message = f"{requester_name} requested approval — open the queue to review."
    metadata = {
        "approval_id": str(approval.id),
        "agent_id": str(approval.agent_id) if approval.agent_id else None,
        "agent_execution_id": (
            str(approval.agent_execution_id) if approval.agent_execution_id else None
        ),
        "required_signoffs": approval.required_signoffs,
        "expires_at": (
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "gate_kind": approval.gate_kind,
    }
    for target in targets:
        await create_notification(
            db,
            tenant_id=approval.tenant_id,
            user_id=target.id,
            type="approval_pending",
            title=truncated_title,
            message=message,
            link="/approvals",
            metadata=metadata,
        )
    await db.commit()
    settings = await _tenant_settings(db, approval.tenant_id)
    await _post_webhook(
        settings, "approval_pending", _serialize(approval), approval.tenant_id
    )


async def _notify_resolved(
    db: AsyncSession, approval: Approval, *, decider: User
) -> None:
    """Tell the requester (and any prior signers) that the approval landed."""
    if not approval.requested_by:
        return
    status_value = (
        approval.status.value
        if hasattr(approval.status, "value")
        else str(approval.status)
    )
    title = approval.title or "Approval resolved"
    truncated_title = title if len(title) <= 80 else title[:77] + "..."
    decider_name = decider.full_name or decider.email or "A reviewer"
    message = f"{decider_name} {status_value} this request."
    targets: set[uuid.UUID] = {approval.requested_by}
    for s in approval.signoffs or []:
        sid = s.get("user_id")
        if sid:
            try:
                targets.add(uuid.UUID(sid))
            except (ValueError, TypeError):
                continue
    targets.discard(decider.id)
    metadata = {
        "approval_id": str(approval.id),
        "status": status_value,
        "agent_id": str(approval.agent_id) if approval.agent_id else None,
        "gate_kind": approval.gate_kind,
    }
    for target_id in targets:
        await create_notification(
            db,
            tenant_id=approval.tenant_id,
            user_id=target_id,
            type="approval_resolved",
            title=truncated_title,
            message=message,
            link="/approvals",
            metadata=metadata,
        )
    if targets:
        await db.commit()
    settings = await _tenant_settings(db, approval.tenant_id)
    await _post_webhook(
        settings, "approval_resolved", _serialize(approval), approval.tenant_id
    )
