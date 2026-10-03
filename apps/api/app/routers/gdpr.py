"""GDPR endpoints. Right to erasure + right to receipts.

  POST /api/gdpr/users/{user_id}/purge          admin-only cascade delete
  GET  /api/gdpr/users/{user_id}/receipts       audit trail (admin or self)
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services.gdpr_purge import list_receipts, purge_user

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User, UserRole

router = APIRouter(prefix="/api/gdpr", tags=["gdpr"])


async def _in_tenant(db: AsyncSession, user: User, subject_id: uuid.UUID) -> bool:
    found = await db.execute(
        select(User.id).where(User.id == subject_id, User.tenant_id == user.tenant_id)
    )
    return found.scalar_one_or_none() is not None


@router.post("/users/{user_id}/purge")
async def purge_endpoint(
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if user.role != UserRole.ADMIN and user.id != user_id:
        return error("Forbidden", 403)
    if not await _in_tenant(db, user, user_id):
        return error("User not found", 404)
    receipt = await purge_user(
        db,
        tenant_id=user.tenant_id,
        subject_user_id=user_id,
        requested_by=user.id,
    )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "gdpr.purge_executed",
        {"subject_user_id": str(user_id), "stores": list(receipt.keys())},
        request,
    )
    await db.commit()
    return success(
        {
            "subject_user_id": str(user_id),
            "receipt": receipt,
        }
    )


@router.get("/users/{user_id}/receipts")
async def receipts_endpoint(
    user_id: uuid.UUID,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if user.role != UserRole.ADMIN and user.id != user_id:
        return error("Forbidden", 403)
    if not await _in_tenant(db, user, user_id):
        return error("User not found", 404)
    rows = await list_receipts(db, user_id, limit=min(limit, 1000))
    return success(
        [
            {
                "id": str(r.id),
                "store": r.store,
                "status": r.status,
                "error": r.error,
                "retries": r.retries,
                "affected": r.affected_count,
                "attempted_at": r.attempted_at.isoformat() if r.attempted_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "requested_by": str(r.requested_by) if r.requested_by else None,
            }
            for r in rows
        ]
    )


__all__ = ["router"]
