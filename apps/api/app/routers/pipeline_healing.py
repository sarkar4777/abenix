"""Self-healing pipelines — diff browse, surgeon-propose, patch apply/reject/rollba"""
from __future__ import annotations

import json as _json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))

from models.agent import Agent
from models.execution import Execution, ExecutionStatus
from models.pipeline_healing import (
    PipelinePatchProposal,
    PipelinePatchStatus,
    PipelineRunDiff,
)
from models.user import User

router = APIRouter(prefix="/api/pipelines", tags=["pipeline-healing"])


class DiagnoseRequest(BaseModel):
    execution_id: str | None = None  # diagnose a specific failure; default = latest


def _can_edit_pipeline(user: User, pipeline: Agent) -> bool:
    if user.role == "admin":
        return True
    return str(pipeline.creator_id) == str(user.id)


@router.get("/{pipeline_id}/diffs")
async def list_diffs(
    pipeline_id: str,
    limit: int = 25,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent failure-diff snapshots for this pipeline (newest first)."""
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)

    rows = (await db.execute(
        select(PipelineRunDiff)
        .where(
            PipelineRunDiff.pipeline_id == pipeline.id,
            PipelineRunDiff.tenant_id == user.tenant_id,
        )
        .order_by(desc(PipelineRunDiff.created_at))
        .limit(min(max(1, limit), 100))
    )).scalars().all()

    return success([{
        "id": str(r.id),
        "execution_id": str(r.execution_id),
        "node_id": r.node_id,
        "node_kind": r.node_kind,
        "node_target": r.node_target,
        "error_class": r.error_class,
        "error_message": r.error_message,
        "expected_shape": r.expected_shape,
        "observed_shape": r.observed_shape,
        "expected_sample": r.expected_sample,
        "observed_sample": r.observed_sample,
        "upstream_inputs": r.upstream_inputs,
        "recent_success_count": r.recent_success_count,
        "recent_failure_count": r.recent_failure_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows])


@router.get("/{pipeline_id}/patches")
async def list_patches(
    pipeline_id: str,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List drafted patches for this pipeline; filter by status."""
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)

    q = select(PipelinePatchProposal).where(
        PipelinePatchProposal.pipeline_id == pipeline.id,
        PipelinePatchProposal.tenant_id == user.tenant_id,
    )
    if status:
        q = q.where(PipelinePatchProposal.status == PipelinePatchStatus(status))
    q = q.order_by(desc(PipelinePatchProposal.created_at))
    rows = (await db.execute(q)).scalars().all()

    return success([{
        "id": str(r.id),
        "title": r.title,
        "rationale": r.rationale,
        "confidence": float(r.confidence),
        "risk_level": r.risk_level,
        "status": r.status.value if hasattr(r.status, "value") else str(r.status),
        "json_patch": r.json_patch,
        "dsl_before": r.dsl_before,
        "dsl_after": r.dsl_after,
        "triggering_diff_id": str(r.triggering_diff_id) if r.triggering_diff_id else None,
        "triggering_execution_id": str(r.triggering_execution_id) if r.triggering_execution_id else None,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decided_by": str(r.decided_by) if r.decided_by else None,
        "rolled_back_at": r.rolled_back_at.isoformat() if r.rolled_back_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows])


@router.post("/{pipeline_id}/diagnose")
async def diagnose(
    pipeline_id: str,
    body: DiagnoseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the Pipeline Surgeon against the latest (or specified) failure"""
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)
    if not _can_edit_pipeline(user, pipeline):
        return error("Only admins or the pipeline owner can run the surgeon", "forbidden", status_code=403)

    # Find the diff to operate on
    q = select(PipelineRunDiff).where(
        PipelineRunDiff.pipeline_id == pipeline.id,
        PipelineRunDiff.tenant_id == user.tenant_id,
    ).order_by(desc(PipelineRunDiff.created_at))
    if body.execution_id:
        q = q.where(PipelineRunDiff.execution_id == uuid.UUID(body.execution_id))
    diff = (await db.execute(q.limit(1))).scalar_one_or_none()
    if not diff:
        return error("No failure diff found for this pipeline yet", "no_diff", status_code=404)

    # Pull last 3 successful executions for evidence (just summary fields)
    recent_ok = (await db.execute(
        select(Execution)
        .where(
            Execution.agent_id == pipeline.id,
            Execution.tenant_id == user.tenant_id,
            Execution.status == ExecutionStatus.COMPLETED,
        )
        .order_by(desc(Execution.created_at))
        .limit(3)
    )).scalars().all()
    recent_successes = [{
        "execution_id": str(e.id),
        "duration_ms": e.duration_ms,
        "output_preview": (e.output_message or "")[:600],
    } for e in recent_ok]

    # The current DSL we will patch
    cfg = (pipeline.model_config_ or {}) if hasattr(pipeline, "model_config_") else {}
    pipeline_cfg = cfg.get("pipeline_config") or {}
    if not pipeline_cfg or "nodes" not in pipeline_cfg:
        return error("This agent has no pipeline DSL to patch", "not_a_pipeline", status_code=400)
    dsl_before = {"pipeline_config": pipeline_cfg}

    # Tool registry — minimal listing so the LLM knows what's available.
    try:
        from engine.tool_resolver import get_default_registry_descriptions  # type: ignore
        tool_registry = get_default_registry_descriptions()
    except Exception:
        tool_registry = []

    # Run the surgeon
    try:
        from engine.llm_router import LLMRouter
        from engine.pipeline_surgeon import propose_patch
    except ImportError as e:
        return error(f"Surgeon module unavailable: {e}", "internal", status_code=500)

    failure_payload = {
        "node_id": diff.node_id,
        "node_kind": diff.node_kind,
        "node_target": diff.node_target,
        "error_class": diff.error_class,
        "error_message": diff.error_message,
        "expected_shape": diff.expected_shape,
        "observed_shape": diff.observed_shape,
        "expected_sample": diff.expected_sample,
        "observed_sample": diff.observed_sample,
        "upstream_inputs": diff.upstream_inputs,
        "recent_success_count": diff.recent_success_count,
        "recent_failure_count": diff.recent_failure_count,
    }

    # Surgeon model is an admin-tunable platform setting so all
    # universally-available LLM tools share one configuration surface.
    from app.core.platform_settings import get_setting
    llm = LLMRouter()
    surgeon_model = await get_setting(
        "pipeline_surgeon.model",
        default="claude-sonnet-4-5-20250929",
    )
    try:
        proposal = await propose_patch(
            llm_router=llm,
            model=surgeon_model,
            dsl_before=dsl_before,
            failure=failure_payload,
            recent_successes=recent_successes,
            tool_registry=tool_registry,
        )
    except Exception as e:
        return error(f"Surgeon could not propose a patch: {e}", "surgeon_failed", status_code=502)

    # Supersede earlier pending proposals targeting the same failure
    pending_for_node = (await db.execute(
        select(PipelinePatchProposal).where(
            PipelinePatchProposal.pipeline_id == pipeline.id,
            PipelinePatchProposal.tenant_id == user.tenant_id,
            PipelinePatchProposal.status == PipelinePatchStatus.PENDING,
        )
    )).scalars().all()
    for older in pending_for_node:
        older.status = PipelinePatchStatus.SUPERSEDED

    rec = PipelinePatchProposal(
        tenant_id=user.tenant_id,
        pipeline_id=pipeline.id,
        triggering_diff_id=diff.id,
        triggering_execution_id=diff.execution_id,
        title=proposal["title"],
        rationale=proposal["rationale"],
        confidence=proposal["confidence"],
        risk_level=proposal["risk_level"],
        dsl_before=proposal["dsl_before"],
        json_patch=proposal["json_patch"],
        dsl_after=proposal["dsl_after"],
        status=PipelinePatchStatus.PENDING,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    return success({
        "id": str(rec.id),
        "title": rec.title,
        "rationale": rec.rationale,
        "confidence": float(rec.confidence),
        "risk_level": rec.risk_level,
        "json_patch": rec.json_patch,
        "dsl_before": rec.dsl_before,
        "dsl_after": rec.dsl_after,
        "status": rec.status.value if hasattr(rec.status, "value") else str(rec.status),
    })


@router.post("/{pipeline_id}/patches/{patch_id}/apply")
async def apply_patch(
    pipeline_id: str,
    patch_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a pending patch to the live pipeline DSL.  Records dsl_before
    in the proposal row so rollback is single-click."""
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)
    if not _can_edit_pipeline(user, pipeline):
        return error("Only admins or the pipeline owner can apply patches", "forbidden", status_code=403)

    proposal = (await db.execute(
        select(PipelinePatchProposal).where(
            PipelinePatchProposal.id == uuid.UUID(patch_id),
            PipelinePatchProposal.pipeline_id == pipeline.id,
            PipelinePatchProposal.tenant_id == user.tenant_id,
        )
    )).scalar_one_or_none()
    if not proposal:
        return error("Patch not found", "not_found", status_code=404)
    if proposal.status != PipelinePatchStatus.PENDING:
        return error(f"Patch is {proposal.status.value} — only pending patches can be applied", "bad_state", status_code=400)

    new_pipeline_cfg = (proposal.dsl_after or {}).get("pipeline_config")
    if not new_pipeline_cfg:
        return error("Patched DSL is malformed (no pipeline_config)", "bad_dsl", status_code=400)

    # Persist into the agent's model_config_
    cfg = dict(pipeline.model_config_ or {})
    cfg["pipeline_config"] = new_pipeline_cfg
    pipeline.model_config_ = cfg
    proposal.status = PipelinePatchStatus.ACCEPTED
    proposal.decided_by = user.id
    proposal.decided_at = datetime.now(timezone.utc)
    await db.commit()

    return success({
        "id": str(proposal.id),
        "status": "accepted",
        "applied_at": proposal.decided_at.isoformat(),
    })


@router.post("/{pipeline_id}/patches/{patch_id}/reject")
async def reject_patch(
    pipeline_id: str,
    patch_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)
    if not _can_edit_pipeline(user, pipeline):
        return error("Only admins or the pipeline owner can reject patches", "forbidden", status_code=403)

    proposal = (await db.execute(
        select(PipelinePatchProposal).where(
            PipelinePatchProposal.id == uuid.UUID(patch_id),
            PipelinePatchProposal.pipeline_id == pipeline.id,
            PipelinePatchProposal.tenant_id == user.tenant_id,
        )
    )).scalar_one_or_none()
    if not proposal:
        return error("Patch not found", "not_found", status_code=404)
    if proposal.status != PipelinePatchStatus.PENDING:
        return error(f"Patch is {proposal.status.value}; cannot reject", "bad_state", status_code=400)

    proposal.status = PipelinePatchStatus.REJECTED
    proposal.decided_by = user.id
    proposal.decided_at = datetime.now(timezone.utc)
    await db.commit()
    return success({"id": str(proposal.id), "status": "rejected"})


@router.post("/{pipeline_id}/patches/{patch_id}/rollback")
async def rollback_patch(
    pipeline_id: str,
    patch_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Roll back a previously-accepted patch by writing dsl_before back to
    the agent.  Marks the proposal as rolled_back but keeps it for audit."""
    pipeline = (await db.execute(
        select(Agent).where(Agent.id == uuid.UUID(pipeline_id), Agent.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not pipeline:
        return error("Pipeline not found", "not_found", status_code=404)
    if not _can_edit_pipeline(user, pipeline):
        return error("Only admins or the pipeline owner can roll back", "forbidden", status_code=403)

    proposal = (await db.execute(
        select(PipelinePatchProposal).where(
            PipelinePatchProposal.id == uuid.UUID(patch_id),
            PipelinePatchProposal.pipeline_id == pipeline.id,
            PipelinePatchProposal.tenant_id == user.tenant_id,
        )
    )).scalar_one_or_none()
    if not proposal:
        return error("Patch not found", "not_found", status_code=404)
    if proposal.status != PipelinePatchStatus.ACCEPTED:
        return error("Only accepted patches can be rolled back", "bad_state", status_code=400)
    if proposal.rolled_back_at:
        return error("Patch was already rolled back", "bad_state", status_code=400)

    before_cfg = (proposal.dsl_before or {}).get("pipeline_config")
    if not before_cfg:
        return error("dsl_before missing — cannot roll back safely", "bad_dsl", status_code=400)

    cfg = dict(pipeline.model_config_ or {})
    cfg["pipeline_config"] = before_cfg
    pipeline.model_config_ = cfg
    proposal.rolled_back_at = datetime.now(timezone.utc)
    proposal.rolled_back_by = user.id
    await db.commit()
    return success({"id": str(proposal.id), "rolled_back_at": proposal.rolled_back_at.isoformat()})
