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


# Compatibility shim — the web bundle ships POST against /settings; we
# accept both verbs so old + new clients keep working. Delegates to the
# canonical PATCH handler above.
@router.post("/settings")
async def post_settings(
    patch: TenantSettingsPatch,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    return await patch_settings(patch=patch, store=store, tenant_id=tenant_id)


# Synthetic ticket fixtures — moved off the client bundle so we can
# vary them per tenant later and keep them admin-only. Matches the
# hardcoded SAMPLES that previously lived in cases/page.tsx.
SAMPLE_TICKETS: list[dict[str, Any]] = [
    {
        "customer_id": "c-1001",
        "customer_tier": "vip",
        "subject": "My order #5483 shipped wrong SKU",
        "body": "Ordered M, got L. Been a customer 4 years. Need this resolved fast.",
        "order_id": "ord-5483",
        "sku": "SKU-BLUE-M",
    },
    {
        "customer_id": "c-1002",
        "customer_tier": "standard",
        "subject": "Refund for damaged package",
        "body": "Box was crushed, item dented. Photos attached. Want a full refund.",
        "order_id": "ord-5484",
        "sku": "SKU-RED-L",
    },
    {
        "customer_id": "c-1003",
        "customer_tier": "standard",
        "subject": "Trial extension request",
        "body": "I did not get to evaluate the product, travel interfered.",
    },
    {
        "customer_id": "c-1004",
        "customer_tier": "gold",
        "subject": "Two duplicate charges on my card",
        "body": "I see two identical charges on my statement — please refund one.",
        "order_id": "ord-5501",
        "sku": "SKU-PRO-ANN",
    },
]


@router.get("/sample-tickets")
async def sample_tickets() -> dict[str, Any]:
    """Return canned synthetic tickets for the demo button on /cases.

    Lives behind the admin prefix so we can layer auth on later; for
    now the route is open the same way every other resolveai endpoint
    is during the platform build-out.
    """
    return {"data": SAMPLE_TICKETS, "meta": {"count": len(SAMPLE_TICKETS)}}


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
