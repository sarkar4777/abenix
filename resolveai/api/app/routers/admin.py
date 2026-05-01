"""Admin surface: tenant settings + pending-approvals queue."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.store import CaseStore, PostgresStore
from app.routers._deps import _maybe, get_store, get_tenant_id

router = APIRouter(prefix="/api/resolveai/admin", tags=["admin"])


class TenantSettingsPatch(BaseModel):
    approval_tiers: dict[str, float] | None = None
    sla_first_response_minutes: int | None = None
    sla_resolution_minutes: int | None = None
    slack_escalation_url: str | None = None
    moderation_policy_id: str | None = None
    integrations: dict[str, str] | None = None


@router.get("/settings")
async def get_settings(
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    if isinstance(store, PostgresStore):
        row = await store.get_tenant_settings(tenant_id)
    else:
        row = store.get_tenant_settings(tenant_id)
    return {"data": row}


@router.patch("/settings")
async def patch_settings(
    patch: TenantSettingsPatch,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    data = patch.model_dump(exclude_none=True)
    if isinstance(store, PostgresStore):
        row = await store.update_tenant_settings(tenant_id, data)
    else:
        row = store.update_tenant_settings(tenant_id, data)
    return {"data": row}


@router.get("/pending-approvals")
async def pending_approvals(
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Everything awaiting a human sign-off across cases, newest first."""
    if isinstance(store, PostgresStore):
        rows = await store.pending_approvals(tenant_id=tenant_id)
    else:
        rows = store.pending_approvals(tenant_id=tenant_id)

    # Attach minimal case context so the UI doesn't need N+1 round-trips.
    enriched: list[dict[str, Any]] = []
    for row in rows:
        case = await _maybe(store.get(row["case_id"]))
        enriched.append({
            **row,
            "case": {
                "id": case["id"],
                "subject": case.get("subject"),
                "customer_id": case.get("customer_id"),
                "customer_tier": case.get("customer_tier"),
                "status": case.get("status"),
            } if case else None,
        })

    return {"data": enriched, "meta": {"count": len(enriched)}}
