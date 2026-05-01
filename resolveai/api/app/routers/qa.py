"""Post-resolution QA endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.store import CaseStore, PostgresStore
from app.routers._deps import _maybe, get_sdk, get_store, get_subject, get_tenant_id

logger = logging.getLogger("resolveai.qa")
router = APIRouter(prefix="/api/resolveai/qa", tags=["qa"])

QA_PIPELINE_SLUG = "resolveai-post-qa"


@router.post("/run/{case_id}")
async def run_qa(
    case_id: str,
    request: Request,
    store: CaseStore = Depends(get_store),
) -> dict[str, Any]:
    """Grade a case + persist a predicted CSAT row."""
    case = await _maybe(store.get(case_id))
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    sdk = get_sdk()
    subject = get_subject(request)
    prompt = (
        f"Grade this closed case on tone, correctness, and policy adherence; "
        f"predict CSAT 1-5.\n\n"
        f"Subject: {case.get('subject')}\n"
        f"Resolution: {case.get('resolution')}\n"
        f"Citations: {case.get('citations')}\n"
    )
    try:
        result = await sdk.execute(
            QA_PIPELINE_SLUG,
            prompt,
            act_as=subject,
            context={"case_id": case_id, "tenant_id": case.get("tenant_id")},
            wait_timeout_seconds=120,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Post-QA pipeline failed")
        raise HTTPException(status_code=502, detail=f"qa pipeline error: {exc}")
    finally:
        try:
            await sdk.close()
        except Exception:  # noqa: BLE001
            pass

    output = getattr(result, "output", None)
    parsed: dict[str, Any] = {}
    if isinstance(output, dict):
        parsed = output
    elif isinstance(output, str):
        try:
            parsed = json.loads(output)
        except (ValueError, TypeError):
            parsed = {"raw": output}

    # Pipeline LLMs sometimes return placeholder strings like
    # "[not available]" when the agent didn't produce a number; treat
    # those as the neutral 3 instead of letting int() crash with 500.
    raw_score = parsed.get("predicted_csat") or parsed.get("score") or 3
    try:
        score = int(raw_score)
    except (TypeError, ValueError):
        try:
            score = int(round(float(raw_score)))
        except (TypeError, ValueError):
            score = 3
    score = max(1, min(5, score))
    bucket = (
        "detractor" if score <= 2
        else "passive" if score == 3
        else "promoter"
    )
    red_flags = parsed.get("red_flags") or []

    if isinstance(store, PostgresStore):
        row = await store.record_csat(
            case_id, score, "predicted",
            predicted_nps_bucket=bucket,
            red_flags=red_flags,
        )
    else:
        row = store.record_csat(
            case_id, score, "predicted",
            predicted_nps_bucket=bucket,
            red_flags=red_flags,
        )

    await _maybe(store.append_event(case_id, {
        "type": "qa_scored",
        "actor": "pipeline",
        "summary": f"predicted CSAT={score} ({bucket})",
        "payload": {"score_id": row["id"], "red_flags": red_flags},
    }))

    return {
        "data": {
            "score": row,
            "pipeline_output": parsed,
            "cost_usd": result.cost,
            "duration_ms": result.duration_ms,
        }
    }


@router.get("/scores")
async def list_scores(
    store: CaseStore = Depends(get_store),
    tenant_id: str = Depends(get_tenant_id),
) -> dict[str, Any]:
    """Aggregate predictions vs actuals — phase-2 admin dashboard feed."""
    if isinstance(store, PostgresStore):
        rows = await store.list_csat(tenant_id=tenant_id)
    else:
        rows = store.list_csat(tenant_id=tenant_id)

    predicted = [r for r in rows if r["source"] == "predicted"]
    survey = [r for r in rows if r["source"] == "survey"]
    agent = [r for r in rows if r["source"] == "agent_rating"]

    def _avg(xs: list[dict[str, Any]]) -> float:
        return round(sum(x["score"] for x in xs) / len(xs), 3) if xs else 0.0

    bucket_counts = {"detractor": 0, "passive": 0, "promoter": 0}
    for r in predicted:
        b = r.get("predicted_nps_bucket")
        if b in bucket_counts:
            bucket_counts[b] += 1

    return {
        "data": rows,
        "meta": {
            "total": len(rows),
            "predicted_avg": _avg(predicted),
            "survey_avg": _avg(survey),
            "agent_rating_avg": _avg(agent),
            "nps_buckets": bucket_counts,
        },
    }
