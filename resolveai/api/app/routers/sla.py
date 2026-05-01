"""SLA sweep endpoint — manual trigger in phase 1."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request

from app.core.store import CaseStore, PostgresStore
from app.routers._deps import _maybe, get_sdk, get_store, get_subject, get_tenant_id

logger = logging.getLogger("resolveai.sla")
router = APIRouter(prefix="/api/resolveai/sla", tags=["sla"])

SLA_PIPELINE_SLUG = "resolveai-sla-sweep"


@router.post("/sweep")
async def sweep(
    request: Request,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Sweep cases past deadline + emit breach rows / Slack pings."""
    now = datetime.now(timezone.utc)

    if isinstance(store, PostgresStore):
        candidates = await store.open_sla_candidates(now=now)
        settings = await store.get_tenant_settings(tenant_id)
    else:
        candidates = store.open_sla_candidates(now=now)
        settings = store.get_tenant_settings(tenant_id)

    slack_url = settings.get("slack_escalation_url")
    breaches: list[dict[str, Any]] = []

    for case in candidates:
        # Compute how overdue we are.
        deadline = case.get("sla_deadline_at")
        try:
            dl = (
                datetime.fromisoformat(deadline)
                if isinstance(deadline, str) and deadline
                else deadline
            )
        except ValueError:
            dl = None
        minutes_overdue = 0
        if dl:
            if dl.tzinfo is None:
                dl = dl.replace(tzinfo=timezone.utc)
            minutes_overdue = max(0, int((now - dl).total_seconds() // 60))

        payload = {
            "sla_type": "resolution",
            "breached_at": now,
            "minutes_overdue": minutes_overdue,
            "escalated_to": "slack",
        }

        if isinstance(store, PostgresStore):
            breach = await store.record_sla_breach(case["id"], payload)
        else:
            breach = store.record_sla_breach(
                case["id"],
                {**payload, "breached_at": now.isoformat()},
            )

        await _maybe(store.append_event(case["id"], {
            "type": "sla_breach",
            "actor": "system",
            "summary": f"SLA missed by {minutes_overdue}min — escalating",
            "payload": {"breach_id": breach["id"]},
        }))
        breaches.append(breach)

    # Best-effort Slack ping — non-fatal if misconfigured.
    if slack_url and breaches:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(slack_url, json={
                    "text": (
                        f":rotating_light: {len(breaches)} ResolveAI case(s) "
                        f"breached SLA (tenant {tenant_id})."
                    ),
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Slack escalation failed: %s", exc)

    # Kick the sweep pipeline — optional, only if key configured.
    pipeline_output: dict[str, Any] | None = None
    try:
        sdk = get_sdk()
        subject = get_subject(request)
        try:
            result = await sdk.execute(
                SLA_PIPELINE_SLUG,
                json.dumps({"breaches": [b["id"] for b in breaches]}),
                act_as=subject,
                context={"tenant_id": tenant_id, "breach_count": len(breaches)},
                wait_timeout_seconds=60,
            )
            pipeline_output = {
                "output": getattr(result, "output", None),
                "cost_usd": result.cost,
                "duration_ms": result.duration_ms,
            }
        finally:
            try:
                await sdk.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.info("SLA pipeline not invoked: %s", exc)

    return {
        "data": {
            "swept_at": now.isoformat(),
            "breaches": breaches,
            "pipeline": pipeline_output,
        },
        "meta": {"breach_count": len(breaches)},
    }
