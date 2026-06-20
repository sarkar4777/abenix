"""Audit log query surface. Immutable. Read-only for everyone except admins."""

from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import success
from app.models.contractiq_models import ContractIQAuditEvent, ContractIQUser
from app.routers.auth import get_contractiq_user

router = APIRouter(prefix="/api/contractiq/audit", tags=["contractiq-audit"])


@router.get("/events")
async def list_events(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    kind: str | None = Query(None),
    resource_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> JSONResponse:
    q = select(ContractIQAuditEvent)
    if kind:
        q = q.where(ContractIQAuditEvent.kind == kind)
    if resource_type:
        q = q.where(ContractIQAuditEvent.resource_type == resource_type)
    q = q.order_by(desc(ContractIQAuditEvent.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return success([
        {
            "id": str(r.id),
            "user_id": str(r.user_id) if r.user_id else None,
            "kind": r.kind,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "action": r.action,
            "before": r.before_state,
            "after": r.after_state,
            "metadata": r.audit_metadata,
            "ip_address": r.ip_address,
            "calc_signature": r.calc_signature,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])
