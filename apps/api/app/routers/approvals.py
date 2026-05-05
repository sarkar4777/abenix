"""Approvals API — backend-enforced multi-step sign-off.

Status flips to ``approved`` once at least ``required_signoffs`` rows in the
JSONB ``signoffs`` array carry decision=``approve``. A single ``deny`` flips
status to ``denied``. The ``approval_gate`` runtime tool long-polls
``GET /api/approvals/{id}`` so it sees status transitions.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.connectors import ApprovalCreate, ApprovalSignoffRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.approval import Approval, ApprovalStatus  # noqa: E402
from models.user import User  # noqa: E402

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
    }


def _evaluate_status(a: Approval) -> ApprovalStatus:
    """Walk the signoffs array and return the new status. Pure function."""
    signoffs = a.signoffs or []
    approve_count = sum(1 for s in signoffs if s.get("decision") == "approve")
    deny_count = sum(1 for s in signoffs if s.get("decision") == "deny")
    if deny_count > 0:
        return ApprovalStatus.denied
    if approve_count >= a.required_signoffs:
        return ApprovalStatus.approved
    if a.expires_at and a.expires_at < datetime.now(timezone.utc):
        return ApprovalStatus.expired
    return ApprovalStatus.pending


async def _expire_stale(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Sweep pending rows past their deadline. Cheap inline call from list/get."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Approval)
        .where(
            Approval.tenant_id == tenant_id,
            Approval.status == ApprovalStatus.pending,
            Approval.expires_at.isnot(None),
            Approval.expires_at < now,
        )
        .values(status=ApprovalStatus.expired, decided_at=now)
    )
    await db.commit()


@router.post("")
async def create_approval(
    body: ApprovalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    expires_at = None
    if body.expires_seconds:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=body.expires_seconds
        )
    a = Approval(
        tenant_id=user.tenant_id,
        agent_id=body.agent_id,
        agent_execution_id=body.agent_execution_id,
        title=body.title,
        payload=body.payload,
        required_signoffs=body.required_signoffs,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=expires_at,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
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
    stmt = stmt.order_by(Approval.created_at.desc()).limit(200)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    _ = mine  # tenant scope is enough for now; keep param for future per-user routing
    return success([_serialize(a) for a in rows])


@router.get("/{approval_id}")
async def get_approval(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_id, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)
    # Expire if past deadline so long-polls see the transition.
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


@router.post("/{approval_id}/signoff")
async def sign_off(
    approval_id: uuid.UUID,
    body: ApprovalSignoffRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.decision not in ("approve", "deny"):
        return error("decision must be 'approve' or 'deny'", 400)
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_id, Approval.tenant_id == user.tenant_id
        )
    )
    a = result.scalar_one_or_none()
    if not a:
        return error("Approval not found", 404)
    if a.status != ApprovalStatus.pending:
        return error(f"Approval is already {a.status.value}", 409)

    signoffs = list(a.signoffs or [])
    if any(s.get("user_id") == str(user.id) for s in signoffs):
        return error("User has already signed off on this approval", 409)
    signoffs.append(
        {
            "user_id": str(user.id),
            "user_email": user.email,
            "decision": body.decision,
            "reason": body.reason or "",
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    a.signoffs = signoffs
    new_status = _evaluate_status(a)
    a.status = new_status
    if new_status != ApprovalStatus.pending:
        a.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(a)
    return success(_serialize(a))
