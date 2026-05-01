"""Trend-mining endpoints (Voice of Customer)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.core.store import CaseStore, PostgresStore
from app.routers._deps import _maybe, get_sdk, get_store, get_subject, get_tenant_id

logger = logging.getLogger("resolveai.trends")
router = APIRouter(prefix="/api/resolveai/trends", tags=["trends"])

TRENDS_PIPELINE_SLUG = "resolveai-trend-mining"


@router.post("/mine")
async def mine_trends(
    request: Request,
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Cluster the last 72h of cases, write VoCInsight rows, return them."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)

    all_cases = await _maybe(store.list(limit=1000, tenant_id=tenant_id))
    recent: list[dict[str, Any]] = []
    for c in all_cases:
        created = c.get("created_at")
        try:
            dt = (
                datetime.fromisoformat(created)
                if isinstance(created, str) and created
                else created
            )
        except ValueError:
            dt = None
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt and dt >= cutoff:
            recent.append(c)

    # Fire the trend-mining pipeline with the slimmed-down corpus.
    pipeline_output: Any = None
    pipeline_cost = 0.0
    pipeline_duration = 0
    try:
        sdk = get_sdk()
        subject = get_subject(request)
        try:
            result = await sdk.execute(
                TRENDS_PIPELINE_SLUG,
                json.dumps({
                    "tenant_id": tenant_id,
                    "window_hours": 72,
                    "case_count": len(recent),
                }),
                act_as=subject,
                context={
                    "tenant_id": tenant_id,
                    "cases": [
                        {
                            "id": c["id"],
                            "subject": c.get("subject"),
                            "sku": c.get("sku"),
                            "ticket_category": c.get("ticket_category"),
                        }
                        for c in recent[:200]
                    ],
                },
                wait_timeout_seconds=180,
            )
            pipeline_output = getattr(result, "output", None)
            pipeline_cost = float(result.cost or 0.0)
            pipeline_duration = int(result.duration_ms or 0)
        finally:
            try:
                await sdk.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.info("Trend-mining pipeline not invoked: %s", exc)

    # Normalise the pipeline output into a list of cluster dicts.
    clusters: list[dict[str, Any]] = []
    if isinstance(pipeline_output, dict) and isinstance(pipeline_output.get("clusters"), list):
        clusters = pipeline_output["clusters"]
    elif isinstance(pipeline_output, list):
        clusters = pipeline_output
    elif isinstance(pipeline_output, str):
        try:
            parsed = json.loads(pipeline_output)
            if isinstance(parsed, dict) and isinstance(parsed.get("clusters"), list):
                clusters = parsed["clusters"]
            elif isinstance(parsed, list):
                clusters = parsed
        except (ValueError, TypeError):
            pass

    written: list[dict[str, Any]] = []
    for cluster in clusters:
        payload = {
            "tenant_id": tenant_id,
            "cluster_id": cluster.get("cluster_id", "cluster-unknown"),
            "signal": cluster.get("signal", ""),
            "case_count": int(cluster.get("case_count", 0)),
            "anomaly_score": float(cluster.get("anomaly_score", 0.0)),
            "example_case_ids": cluster.get("example_case_ids", []),
            "suggested_action": cluster.get("suggested_action", ""),
            "status": "open",
        }
        if isinstance(store, PostgresStore):
            row = await store.record_voc(payload)
        else:
            row = store.record_voc(payload)
        written.append(row)

    return {
        "data": written,
        "meta": {
            "corpus_size": len(recent),
            "clusters_detected": len(clusters),
            "insights_written": len(written),
            "pipeline_cost_usd": pipeline_cost,
            "pipeline_duration_ms": pipeline_duration,
        },
    }


@router.get("/insights")
async def list_insights(
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    if isinstance(store, PostgresStore):
        rows = await store.list_voc(tenant_id=tenant_id)
    else:
        rows = store.list_voc(tenant_id=tenant_id)
    open_rows = [r for r in rows if r.get("status") == "open"]
    return {"data": open_rows, "meta": {"total": len(rows), "open": len(open_rows)}}
