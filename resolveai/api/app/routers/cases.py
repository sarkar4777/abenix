"""Case-lifecycle endpoints: ingest, list, detail, take-over, close, approve/reject"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.store import CaseStore, PostgresStore
from app.routers._deps import (
    _maybe,
    get_sdk,
    get_store,
    get_subject,
    get_tenant_id,
)

logger = logging.getLogger("resolveai.cases")
router = APIRouter(prefix="/api/resolveai/cases", tags=["cases"])


# ─── Schemas ───────────────────────────────────────────────────────────


class IngestTicketRequest(BaseModel):
    customer_id: str
    channel: str = "chat"
    subject: str
    body: str
    order_id: str | None = None
    sku: str | None = None
    customer_tier: str = "standard"
    jurisdiction: str = "US"
    locale: str = "en"


class HumanTakeoverRequest(BaseModel):
    reason: str


class CloseCaseRequest(BaseModel):
    resolution: str
    closed_by: str = "manual"


class ApprovalRequest(BaseModel):
    action_id: str
    approver: str = Field(default="unknown")
    note: str | None = None


class RejectionRequest(BaseModel):
    action_id: str
    approver: str = "unknown"
    reason: str


INBOUND_PIPELINE_SLUG = "resolveai-inbound-resolution"


# ─── Endpoints ─────────────────────────────────────────────────────────


@router.post("", status_code=201)
async def ingest_ticket(
    body: IngestTicketRequest,
    request: Request,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> JSONResponse:
    """Commit the ticket row, then fire the Inbound Resolution pipeline"""
    case = await _maybe(store.ingest(body.model_dump(), tenant_id=tenant_id))
    subject = get_subject(request)
    asyncio.create_task(_run_inbound_pipeline(
        case_id=str(case["id"]),
        body=body,
        subject=subject,
        tenant_id=tenant_id,
        store=store,
    ))
    return JSONResponse(case, status_code=201)


async def _run_inbound_pipeline(
    *, case_id: str, body: IngestTicketRequest, subject, tenant_id: str, store: CaseStore
) -> None:
    """Background runner — same logic that used to live inline in"""
    sdk = get_sdk()
    prompt = (
        f"Ticket subject: {body.subject}\n\n"
        f"Customer ({body.customer_tier} tier, locale {body.locale}):\n{body.body}"
    )
    ctx = {
        "customer_id": body.customer_id,
        "customer_tier": body.customer_tier,
        "order_id": body.order_id,
        "sku": body.sku,
        "channel": body.channel,
        "jurisdiction": body.jurisdiction,
        "tenant_id": tenant_id,
    }
    try:
        result = await sdk.execute(
            INBOUND_PIPELINE_SLUG,
            prompt,
            act_as=subject,
            context=ctx,
            wait_timeout_seconds=300,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Inbound Resolution pipeline failed")
        await _maybe(store.update_status(
            case_id, "pipeline_error",
            _event_type="pipeline_error",
            _event_summary=str(exc),
        ))
        return
    finally:
        try:
            await sdk.close()
        except Exception:  # noqa: BLE001
            pass

    final = getattr(result, "output", None)
    resolution: str | None = None
    citations: list = []
    deflection: float | None = None
    action_plan: dict = {}

    if isinstance(final, str):
        stripped = final.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                import json as _json
                final = _json.loads(stripped)
            except _json.JSONDecodeError:
                pass
    if isinstance(final, str):
        resolution = final
    elif isinstance(final, dict):
        resolution = final.get("reply") or final.get("summary") or str(final)
        citations = final.get("citations") or []
        deflection = final.get("deflection_score")
        action_plan = final.get("action_plan") or {}
        if isinstance(deflection, str):
            try:
                deflection = float(deflection)
            except ValueError:
                deflection = None

    new_status = (
        "auto_resolved"
        if deflection is not None and deflection >= 0.6
        else "handed_to_human"
    )
    await _maybe(store.update_status(
        case_id, new_status,
        resolution=resolution,
        citations=citations,
        deflection_score=deflection,
        action_plan=action_plan,
        cost_usd=float(result.cost or 0.0),
        duration_ms=int(result.duration_ms or 0),
        _event_type="pipeline_completed",
        _event_summary=f"deflection={deflection} status={new_status}",
    ))


@router.get("")
async def list_cases(
    status: str | None = None,
    limit: int = 50,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    rows = await _maybe(store.list(status=status, limit=limit, tenant_id=tenant_id))
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/{case_id}")
async def get_case(
    case_id: str,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return {"data": case}


@router.post("/{case_id}/take-over")
async def human_takeover(
    case_id: str,
    body: HumanTakeoverRequest,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    updated = await _maybe(store.update_status(
        case_id, "human_handling",
        assigned_human="live-agent-queue",
        _event_type="human_takeover",
        _event_summary=body.reason,
        _event_actor="user:ops",
    ))
    return {"data": updated or case}


@router.post("/{case_id}/close")
async def close_case(
    case_id: str,
    body: CloseCaseRequest,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    """Manually close a case — e.g. human agent resolved it out of band."""
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    updated = await _maybe(store.update_status(
        case_id, "closed",
        resolution=body.resolution,
        closed_at=datetime.now(timezone.utc),
        _event_type="case_closed",
        _event_summary=f"closed by {body.closed_by}",
        _event_actor=f"user:{body.closed_by}",
    ))
    return {"data": updated or case}


@router.get("/{case_id}/audit-trail")
async def audit_trail(
    case_id: str,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    """All ActionAudit rows for a case (refunds, credits, escalations)."""
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if isinstance(store, PostgresStore):
        rows = await store.list_actions(case_id)
    else:
        rows = store.list_actions(case_id)

    return {"data": rows, "meta": {"count": len(rows)}}


@router.post("/{case_id}/approve")
async def approve_action(
    case_id: str,
    body: ApprovalRequest,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    """Sign off on a pending ActionAudit row — flips its status to approved."""
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    now = datetime.now(timezone.utc)
    if isinstance(store, PostgresStore):
        row = await store.get_action(body.action_id)
        if not row or row["case_id"] != case_id:
            raise HTTPException(status_code=404, detail="Action not found on this case")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Action already {row['status']}")
        updated = await store.update_action(
            body.action_id,
            status="approved",
            approved_by=body.approver,
            approved_at=now,
        )
    else:
        row = store.get_action(body.action_id)
        if not row or row["case_id"] != case_id:
            raise HTTPException(status_code=404, detail="Action not found on this case")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Action already {row['status']}")
        row["status"] = "approved"
        row["approved_by"] = body.approver
        row["approved_at"] = now.isoformat()
        updated = row

    await _maybe(store.append_event(case_id, {
        "type": "action_approved",
        "actor": f"user:{body.approver}",
        "summary": f"approved {updated['action_type']} ${updated['amount_usd']:.2f}",
        "payload": {"action_id": body.action_id, "note": body.note},
    }))
    return {"data": updated}


@router.post("/{case_id}/reject")
async def reject_action(
    case_id: str,
    body: RejectionRequest,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    """Reject a pending ActionAudit row — flips status to cancelled with reason."""
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    if isinstance(store, PostgresStore):
        row = await store.get_action(body.action_id)
        if not row or row["case_id"] != case_id:
            raise HTTPException(status_code=404, detail="Action not found on this case")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Action already {row['status']}")
        updated = await store.update_action(
            body.action_id,
            status="cancelled",
            approved_by=body.approver,
            approved_at=datetime.now(timezone.utc),
        )
    else:
        row = store.get_action(body.action_id)
        if not row or row["case_id"] != case_id:
            raise HTTPException(status_code=404, detail="Action not found on this case")
        if row["status"] != "pending_approval":
            raise HTTPException(status_code=409, detail=f"Action already {row['status']}")
        row["status"] = "cancelled"
        row["approved_by"] = body.approver
        row["approved_at"] = datetime.now(timezone.utc).isoformat()
        updated = row

    await _maybe(store.append_event(case_id, {
        "type": "action_rejected",
        "actor": f"user:{body.approver}",
        "summary": f"rejected {updated['action_type']}: {body.reason}",
        "payload": {"action_id": body.action_id, "reason": body.reason},
    }))
    return {"data": updated}
