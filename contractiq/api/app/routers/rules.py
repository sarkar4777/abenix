"""Rule library — typed, versioned, four-eyes approved rules."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.models.contractiq_models import (
    ContractIQAuditEvent,
    ContractIQRule,
    ContractIQUser,
)
from app.routers.auth import get_contractiq_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/rules", tags=["contractiq-rules"])


def _ser(r: ContractIQRule) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "kind": r.kind,
        "commodity_family": r.commodity_family,
        "description": r.description,
        "expression": r.expression,
        "inputs_schema": r.inputs_schema,
        "outputs_schema": r.outputs_schema,
        "version": r.version,
        "status": r.status,
        "effective_from": r.effective_from.isoformat() if r.effective_from else None,
        "effective_to": r.effective_to.isoformat() if r.effective_to else None,
        "author_id": str(r.author_id) if r.author_id else None,
        "approver_id": str(r.approver_id) if r.approver_id else None,
        "tags": r.tags,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/")
async def list_rules(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    commodity_family: str | None = Query(None),
    status: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> JSONResponse:
    q = select(ContractIQRule)
    if commodity_family:
        q = q.where(ContractIQRule.commodity_family == commodity_family)
    if status:
        q = q.where(ContractIQRule.status == status)
    if kind:
        q = q.where(ContractIQRule.kind == kind)
    q = q.order_by(desc(ContractIQRule.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return success([_ser(r) for r in rows])


@router.post("/")
async def create_rule(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    required = {"name", "kind", "commodity_family", "expression"}
    missing = required - body.keys()
    if missing:
        return error(f"missing: {sorted(missing)}", 400)
    row = ContractIQRule(
        name=body["name"],
        kind=body["kind"],
        commodity_family=body["commodity_family"],
        description=body.get("description"),
        expression=body["expression"],
        inputs_schema=body.get("inputs_schema") or {},
        outputs_schema=body.get("outputs_schema") or {},
        version=body.get("version", "1.0.0"),
        status="draft",
        author_id=user.id,
        tags=body.get("tags") or [],
    )
    db.add(row)
    db.add(ContractIQAuditEvent(
        user_id=user.id, kind="rule", resource_type="rule", resource_id=row.name,
        action="create", after_state={"name": row.name, "version": row.version},
    ))
    await db.commit()
    await db.refresh(row)
    return success(_ser(row))


@router.post("/{rule_id}/approve")
async def approve_rule(
    rule_id: uuid.UUID,
    body: dict | None = None,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rule = (await db.execute(select(ContractIQRule).where(ContractIQRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        return error("rule not found", 404)
    if rule.author_id == user.id:
        return error("four-eyes — approver cannot be author", 403)
    if rule.status != "draft":
        return error(f"rule is {rule.status}, not draft", 400)
    before = {"status": rule.status, "approver_id": str(rule.approver_id) if rule.approver_id else None}
    rule.status = "active"
    rule.approver_id = user.id
    db.add(ContractIQAuditEvent(
        user_id=user.id, kind="rule", resource_type="rule", resource_id=rule.name,
        action="approve", before_state=before, after_state={"status": "active", "approver_id": str(user.id)},
    ))
    await db.commit()
    await db.refresh(rule)
    return success(_ser(rule))


@router.post("/{rule_id}/retire")
async def retire_rule(
    rule_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rule = (await db.execute(select(ContractIQRule).where(ContractIQRule.id == rule_id))).scalar_one_or_none()
    if not rule:
        return error("rule not found", 404)
    before = {"status": rule.status}
    rule.status = "retired"
    db.add(ContractIQAuditEvent(
        user_id=user.id, kind="rule", resource_type="rule", resource_id=rule.name,
        action="retire", before_state=before, after_state={"status": "retired"},
    ))
    await db.commit()
    await db.refresh(rule)
    return success(_ser(rule))
