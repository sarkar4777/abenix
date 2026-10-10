"""Case intake and assessment.

Receiving a case returns immediately with status=received and fires the
assessment pipeline on a background task. Every platform call goes through
the Abenix SDK — this module holds no HTTP client of its own.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from abenix_sdk import Abenix, ActingSubject

from app.core.store import CaseStore
from app.routers._deps import (
    ASSESS_PIPELINE_SLUG,
    ASSESS_WAIT_SECONDS,
    get_sdk,
    get_store,
    get_subject,
    get_tenant_id,
)

logger = logging.getLogger("pharmavigil.cases")
router = APIRouter(prefix="/api/pv/cases", tags=["pv-cases"])


class CaseIn(BaseModel):
    narrative: str = Field(min_length=10, max_length=20000, description="The reporter's own words")
    suspect_drug: str = Field(min_length=1, max_length=200)
    reporter_type: str = Field(
        default="consumer",
        pattern="^(consumer|physician|pharmacist|nurse|other_hcp|lawyer|other)$",
    )
    country: str = Field(default="GB", pattern="^[A-Z]{2}$", description="ISO 3166 alpha-2")
    received_date: date | None = None
    attachment_urls: list[str] = Field(default_factory=list, max_length=10)


class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|merge)$")
    reviewer: str = Field(default="medical.reviewer", min_length=2, max_length=120)
    notes: str = Field(default="", max_length=4000)


def _ok(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None, "meta": None}


@router.get("")
async def list_cases(
    limit: int = 100,
    status: str | None = None,
    store: CaseStore = Depends(get_store),
):
    return _ok(await store.list(limit=limit, status=status))


@router.get("/stats")
async def case_stats(store: CaseStore = Depends(get_store)):
    return _ok(await store.stats())


@router.get("/{case_id}")
async def get_case(case_id: str, store: CaseStore = Depends(get_store)):
    row = await store.get(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    row["events"] = await store.events(case_id)
    return _ok(row)


@router.post("", status_code=202)
async def create_case(
    body: CaseIn,
    background: BackgroundTasks,
    store: CaseStore = Depends(get_store),
    subject: ActingSubject = Depends(get_subject),
    tenant_id: str = Depends(get_tenant_id),
):
    """Accept a report and start the assessment.

    202 rather than 201: the pipeline runs for a couple of minutes and the UI
    subscribes to the execution rather than holding the request open.
    """
    case = await store.create({
        "id": str(uuid.uuid4()),
        "narrative": body.narrative,
        "suspect_drug": body.suspect_drug,
        "reporter_type": body.reporter_type,
        "country": body.country,
        "received_date": (body.received_date or date.today()).isoformat(),
        "attachment_urls": body.attachment_urls,
    })
    background.add_task(_assess, case["id"], body, subject, tenant_id, store)
    return _ok(case)


@router.post("/{case_id}/reassess", status_code=202)
async def reassess_case(
    case_id: str,
    background: BackgroundTasks,
    store: CaseStore = Depends(get_store),
    subject: ActingSubject = Depends(get_subject),
    tenant_id: str = Depends(get_tenant_id),
):
    """Run the assessment again on a case whose last run failed."""
    row = await store.get(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    if row.get("status") != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"case is {row.get('status')}, only a failed assessment can be run again",
        )
    body = CaseIn(
        narrative=row["narrative"],
        suspect_drug=row["suspect_drug"],
        reporter_type=row.get("reporter_type") or "consumer",
        country=row.get("country") or "GB",
        received_date=row.get("received_date"),
        attachment_urls=row.get("attachment_urls") or [],
    )
    updated = await store.update(
        case_id, status="received", error_message=None,
        _event_type="reassess", _event_summary="Assessment started again",
    )
    background.add_task(_assess, case_id, body, subject, tenant_id, store)
    return _ok(updated)


@router.post("/{case_id}/review")
async def review_case(
    case_id: str,
    body: ReviewIn,
    store: CaseStore = Depends(get_store),
):
    """The human gate. Nothing is submitted to a regulator without it."""
    row = await store.get(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="case not found")
    if row.get("review_decision"):
        raise HTTPException(
            status_code=409,
            detail=f"{row.get('reviewed_by')} already chose {row.get('review_decision')} for this case",
        )
    if row.get("status") != "assessed":
        raise HTTPException(
            status_code=409,
            detail=f"case is {row.get('status')}, wait for the assessment to finish",
        )
    if body.decision in {"reject", "merge"} and not body.notes.strip():
        raise HTTPException(status_code=422, detail=f"Say why you {body.decision} this case")
    if body.decision == "merge" and not row.get("is_duplicate"):
        raise HTTPException(status_code=409, detail="this case was not flagged as a duplicate")
    updated = await store.record_review(case_id, body.decision, body.reviewer, body.notes)
    return _ok(updated)


async def _assess(
    case_id: str,
    body: CaseIn,
    subject: ActingSubject,
    tenant_id: str,
    store: CaseStore,
) -> None:
    """Run the Abenix pipeline and fold the result onto the case row."""
    await store.update(
        case_id, status="assessing",
        _event_type="assessing", _event_summary="Assessment pipeline started",
    )

    sdk: Abenix = get_sdk()
    # The signal node needs a denominator. The app owns the case history, so
    # the app supplies the counts rather than leaving the agent to invent a
    # contingency table — which it correctly refuses to do.
    try:
        counts = await store.frequency_snapshot()
    except Exception:  # noqa: BLE001
        counts = {}
    context = {
        "case_id": case_id,
        "received_date": (body.received_date or date.today()).isoformat(),
        "reporter_type": body.reporter_type,
        "country": body.country,
        "suspect_drug": body.suspect_drug,
        "attachment_urls": ",".join(body.attachment_urls),
        "tenant_id": tenant_id,
        "case_counts": json.dumps(counts, default=str),
    }

    try:
        result = await sdk.execute(
            ASSESS_PIPELINE_SLUG,
            body.narrative,
            act_as=subject,
            context=context,
            wait_timeout_seconds=ASSESS_WAIT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("assessment pipeline failed for %s", case_id)
        # httpx.ReadTimeout and friends stringify to "", which left the case
        # carrying a blank error and nothing to act on.
        detail = f"{type(exc).__name__}: {exc}".rstrip(": ")
        await store.update(
            case_id, status="failed", error_message=detail[:1000],
            _event_type="failed", _event_summary=detail[:200],
        )
        return
    finally:
        try:
            await sdk.close()
        except Exception:  # noqa: BLE001
            pass

    execution_id = getattr(result, "execution_id", None)
    status = (getattr(result, "status", "") or "").lower()
    if status in {"failed", "cancelled"}:
        await store.update(
            case_id, status="failed", execution_id=execution_id,
            error_message=f"pipeline reported {status}",
            _event_type="failed", _event_summary=f"pipeline {status}",
        )
        return

    out = getattr(result, "output", None)
    if not isinstance(out, dict):
        await store.update(
            case_id, status="failed", execution_id=execution_id,
            error_message="pipeline returned no structured output",
            _event_type="failed", _event_summary="no structured output",
        )
        return

    # "[not available]" is the engine's placeholder for a template that never
    # resolved. Storing it would put that text in front of a reviewer as if it
    # were a finding.
    def val(key: str) -> Any:
        v = out.get(key)
        if isinstance(v, str) and v.strip() in {"", "[not available]"}:
            return None
        return v

    fields = {k: val(k) for k in (
        "serious", "seriousness_criteria", "expedited", "reporting_clock_days",
        "due_date", "listedness", "who_umc", "naranjo_score", "naranjo_category",
        "primary_pt", "signal", "prr", "eb05", "signal_recommendation",
        "priority", "escalation_probability", "sla_hours", "priority_drivers",
        "recommended_reviewer", "is_duplicate", "duplicate_of", "coded_terms",
        "uncoded_terms", "narrative_text", "e2b", "reviewer_questions",
        "missing_information", "ready_to_submit",
    )}
    fields["narrative_text"] = val("narrative")
    fields["assessment"] = out
    fields["execution_id"] = execution_id
    fields["cost_usd"] = getattr(result, "cost", None)
    fields["duration_ms"] = getattr(result, "duration_ms", None)

    # A run can finish and still be short of what a submission needs. Say which
    # rather than leaving the case looking complete.
    gaps: list[str] = []
    if fields.get("uncoded_terms"):
        gaps.append(f"{len(fields['uncoded_terms'])} reaction term(s) uncoded")
    if fields.get("missing_information"):
        gaps.append(f"{len(fields['missing_information'])} mandatory field(s) missing")
    if not fields.get("narrative_text"):
        gaps.append("no narrative produced")
    fields["assessment_gaps"] = gaps or None

    await store.update(
        case_id, status="assessed", **fields,
        _event_type="assessed",
        _event_summary=(
            f"{fields.get('priority') or 'unprioritised'} · "
            f"{'serious' if fields.get('serious') else 'non-serious'} · "
            f"{fields.get('who_umc') or 'causality unknown'}"
            + (f" · {len(gaps)} gap(s)" if gaps else "")
        ),
    )


async def _noop() -> None:  # pragma: no cover - keeps asyncio import honest
    await asyncio.sleep(0)
