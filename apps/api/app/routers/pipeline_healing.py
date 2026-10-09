"""Self-healing pipelines — diff browse, surgeon-propose, patch apply/reject/rollba"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
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


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _can_edit_pipeline(
    user: User, pipeline: Agent, proposal: PipelinePatchProposal | None = None
) -> bool:
    """Admin, pipeline owner, or the approver of this proposal."""
    if user.role == "admin":
        return True
    if str(pipeline.creator_id) == str(user.id):
        return True
    if proposal is not None and proposal.decided_by is not None:
        return str(proposal.decided_by) == str(user.id)
    return False


def config_hash(pipeline_cfg: Any) -> str:
    """sha256 of the canonical JSON form of a pipeline_config."""
    canon = json.dumps(pipeline_cfg, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_ENGINE_TOOLS = {"agent_step", "wait", "state_get", "state_set", "__structured__"}


def with_node_tools(model_cfg: dict[str, Any], pipeline_cfg: Any) -> dict[str, Any]:
    """model_config whose tools list covers every tool the nodes call."""
    tools = list(model_cfg.get("tools") or [])
    for n in (pipeline_cfg or {}).get("nodes") or []:
        if not isinstance(n, dict):
            continue
        name = n.get("tool_name") or n.get("tool")
        if (
            isinstance(name, str)
            and name
            and name not in _ENGINE_TOOLS
            and name not in tools
        ):
            tools.append(name)
    return {**model_cfg, "tools": tools}


def _current_cfg(pipeline: Agent) -> dict[str, Any]:
    cfg = (pipeline.model_config_ or {}) if hasattr(pipeline, "model_config_") else {}
    return cfg.get("pipeline_config") or {}


async def _load_pipeline(
    db: AsyncSession, user: User, pipeline_id: str
) -> Agent | None:
    pid = _parse_uuid(pipeline_id)
    if pid is None:
        return None
    return (
        await db.execute(
            select(Agent).where(Agent.id == pid, Agent.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()


async def _load_proposal(
    db: AsyncSession, user: User, pipeline: Agent, patch_id: str
) -> PipelinePatchProposal | None:
    pat = _parse_uuid(patch_id)
    if pat is None:
        return None
    return (
        await db.execute(
            select(PipelinePatchProposal).where(
                PipelinePatchProposal.id == pat,
                PipelinePatchProposal.pipeline_id == pipeline.id,
                PipelinePatchProposal.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _proposal_dict(r: PipelinePatchProposal) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "title": r.title,
        "rationale": r.rationale,
        "confidence": float(r.confidence),
        "risk_level": r.risk_level,
        "status": _status_value(r.status),
        "json_patch": r.json_patch,
        "dsl_before": r.dsl_before,
        "dsl_after": r.dsl_after,
        "dsl_before_sha256": r.dsl_before_sha256,
        "has_applied_snapshot": r.applied_snapshot is not None,
        "triggering_diff_id": (
            str(r.triggering_diff_id) if r.triggering_diff_id else None
        ),
        "triggering_execution_id": (
            str(r.triggering_execution_id) if r.triggering_execution_id else None
        ),
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decided_by": str(r.decided_by) if r.decided_by else None,
        "rolled_back_at": (r.rolled_back_at.isoformat() if r.rolled_back_at else None),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/{pipeline_id}/diffs")
async def list_diffs(
    pipeline_id: str,
    limit: int = 25,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent failure-diff snapshots for this pipeline (newest first)."""
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")

    rows = (
        (
            await db.execute(
                select(PipelineRunDiff)
                .where(
                    PipelineRunDiff.pipeline_id == pipeline.id,
                    PipelineRunDiff.tenant_id == user.tenant_id,
                )
                .order_by(desc(PipelineRunDiff.created_at))
                .limit(min(max(1, limit), 100))
            )
        )
        .scalars()
        .all()
    )

    return success(
        [
            {
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
            }
            for r in rows
        ],
        meta={"can_edit": _can_edit_pipeline(user, pipeline)},
    )


@router.get("/{pipeline_id}/patches")
async def list_patches(
    pipeline_id: str,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List drafted patches for this pipeline; filter by status."""
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")

    status_filter: PipelinePatchStatus | None = None
    if status:
        try:
            status_filter = PipelinePatchStatus(status.strip().lower())
        except ValueError:
            allowed = ", ".join(s.value for s in PipelinePatchStatus)
            return error(f"status must be one of: {allowed}", 400, "bad_status")

    q = select(PipelinePatchProposal).where(
        PipelinePatchProposal.pipeline_id == pipeline.id,
        PipelinePatchProposal.tenant_id == user.tenant_id,
    )
    if status_filter is not None:
        q = q.where(PipelinePatchProposal.status == status_filter)
    q = q.order_by(desc(PipelinePatchProposal.created_at))
    rows = (await db.execute(q)).scalars().all()

    # can_edit covers apply/reject. Rollback additionally allows the
    # approver, which the UI checks per row via decided_by.
    return success(
        [_proposal_dict(r) for r in rows],
        meta={
            "can_edit": _can_edit_pipeline(user, pipeline),
            "user_id": str(user.id),
        },
    )


@router.post("/{pipeline_id}/diagnose")
async def diagnose(
    pipeline_id: str,
    body: DiagnoseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the Pipeline Surgeon against the latest (or specified) failure"""
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")
    if not _can_edit_pipeline(user, pipeline):
        return error(
            "Only admins or the pipeline owner can run the surgeon", 403, "forbidden"
        )

    # Find the diff to operate on
    q = (
        select(PipelineRunDiff)
        .where(
            PipelineRunDiff.pipeline_id == pipeline.id,
            PipelineRunDiff.tenant_id == user.tenant_id,
        )
        .order_by(desc(PipelineRunDiff.created_at))
    )
    if body.execution_id:
        exec_id = _parse_uuid(body.execution_id)
        if exec_id is None:
            return error("execution_id is not a valid UUID", 400, "bad_request")
        q = q.where(PipelineRunDiff.execution_id == exec_id)
    diff = (await db.execute(q.limit(1))).scalar_one_or_none()
    if not diff:
        return error("No failure diff found for this pipeline yet", 404, "no_diff")

    # Pull last 3 successful executions for evidence (just summary fields)
    recent_ok = (
        (
            await db.execute(
                select(Execution)
                .where(
                    Execution.agent_id == pipeline.id,
                    Execution.tenant_id == user.tenant_id,
                    Execution.status == ExecutionStatus.COMPLETED,
                )
                .order_by(desc(Execution.created_at))
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    recent_successes = [
        {
            "execution_id": str(e.id),
            "duration_ms": e.duration_ms,
            "output_preview": (e.output_message or "")[:600],
        }
        for e in recent_ok
    ]

    # The current DSL we will patch
    pipeline_cfg = _current_cfg(pipeline)
    if not pipeline_cfg or "nodes" not in pipeline_cfg:
        return error("This agent has no pipeline DSL to patch", 400, "not_a_pipeline")
    dsl_before = {"pipeline_config": pipeline_cfg}
    before_hash = config_hash(pipeline_cfg)

    # Tool registry bounds which tools the surgeon may reference.
    try:
        from engine.tool_resolver import get_default_registry_descriptions
    except ImportError as e:
        return error(f"Tool registry unavailable: {e}", 500, "internal")
    try:
        tool_registry = get_default_registry_descriptions()
    except Exception as e:
        return error(f"Tool registry could not be loaded: {e}", 500, "internal")
    if not tool_registry:
        return error("Tool registry is empty, refusing to draft", 500, "internal")

    # Run the surgeon
    try:
        from engine.llm_router import LLMRouter
        from engine.pipeline_surgeon import propose_patch
    except ImportError as e:
        return error(f"Surgeon module unavailable: {e}", 500, "internal")

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
    except ValueError as e:
        return error(f"Surgeon proposal rejected: {e}", 422, "surgeon_rejected")
    except Exception as e:
        return error(f"Surgeon could not propose a patch: {e}", 502, "surgeon_failed")

    # Supersede earlier pending proposals targeting the same failure
    pending_for_node = (
        (
            await db.execute(
                select(PipelinePatchProposal).where(
                    PipelinePatchProposal.pipeline_id == pipeline.id,
                    PipelinePatchProposal.tenant_id == user.tenant_id,
                    PipelinePatchProposal.status == PipelinePatchStatus.PENDING,
                )
            )
        )
        .scalars()
        .all()
    )
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
        dsl_before_sha256=before_hash,
        json_patch=proposal["json_patch"],
        dsl_after=proposal["dsl_after"],
        status=PipelinePatchStatus.PENDING,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)

    return success(_proposal_dict(rec))


@router.post("/{pipeline_id}/patches/{patch_id}/apply")
async def apply_patch(
    pipeline_id: str,
    patch_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a pending patch to the live pipeline DSL.

    Compare-and-swap: the live config must still hash to the proposal's
    dsl_before_sha256, otherwise 409. The replaced config is snapshotted on
    the proposal and an activity_logs row is written.
    """
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")
    if not _can_edit_pipeline(user, pipeline):
        return error(
            "Only admins or the pipeline owner can apply patches", 403, "forbidden"
        )

    proposal = await _load_proposal(db, user, pipeline, patch_id)
    if not proposal:
        return error("Patch not found", 404, "not_found")
    if proposal.status != PipelinePatchStatus.PENDING:
        return error(
            f"Patch is {_status_value(proposal.status)} — only pending patches "
            "can be applied",
            400,
            "bad_state",
        )

    new_pipeline_cfg = (proposal.dsl_after or {}).get("pipeline_config")
    if not new_pipeline_cfg:
        return error("Patched DSL is malformed (no pipeline_config)", 400, "bad_dsl")

    current_cfg = _current_cfg(pipeline)
    current_hash = config_hash(current_cfg)
    expected_hash = proposal.dsl_before_sha256 or config_hash(
        (proposal.dsl_before or {}).get("pipeline_config")
    )
    if current_hash != expected_hash:
        return error(
            "Pipeline changed since this patch was drafted, diagnose again",
            409,
            "stale_patch",
            details={"expected_sha256": expected_hash, "current_sha256": current_hash},
        )

    from app.services import agent_revisions as revs

    prev_state = revs.agent_state(pipeline)
    cfg = dict(pipeline.model_config_ or {})
    cfg["pipeline_config"] = new_pipeline_cfg
    # a patch that adds a step with a new tool would otherwise fail the tools check on run
    pipeline.model_config_ = with_node_tools(cfg, new_pipeline_cfg)
    if prev_state.get("status") == "active":
        blocked = await revs.eval_gate_refusal(db, pipeline, live_edit=True)
        if blocked:
            await db.rollback()
            return blocked
    try:
        await revs.record_revision(
            db,
            pipeline,
            changed_by=user.id,
            change_type="healing_patch",
            source="healing",
            previous_state=prev_state,
            diff_summary=f"Healing patch applied: {proposal.title}",
        )
    except revs.RevisionWriteError:
        await db.rollback()
        return revs.revision_failed()
    proposal.applied_snapshot = current_cfg
    proposal.status = PipelinePatchStatus.ACCEPTED
    proposal.decided_by = user.id
    proposal.decided_at = datetime.now(timezone.utc)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "pipeline_patch.applied",
        {
            "pipeline_id": str(pipeline.id),
            "patch_id": str(proposal.id),
            "title": proposal.title,
            "risk_level": proposal.risk_level,
            "confidence": float(proposal.confidence),
            "before_sha256": current_hash,
            "after_sha256": config_hash(new_pipeline_cfg),
        },
        request,
        resource_type="pipeline_patch_proposal",
        resource_id=str(proposal.id),
    )
    await db.commit()

    return success(
        {
            "id": str(proposal.id),
            "status": "accepted",
            "applied_at": proposal.decided_at.isoformat(),
            "after_sha256": config_hash(new_pipeline_cfg),
        }
    )


@router.post("/{pipeline_id}/patches/{patch_id}/reject")
async def reject_patch(
    pipeline_id: str,
    patch_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")
    if not _can_edit_pipeline(user, pipeline):
        return error(
            "Only admins or the pipeline owner can reject patches", 403, "forbidden"
        )

    proposal = await _load_proposal(db, user, pipeline, patch_id)
    if not proposal:
        return error("Patch not found", 404, "not_found")
    if proposal.status != PipelinePatchStatus.PENDING:
        return error(
            f"Patch is {_status_value(proposal.status)}; cannot reject",
            400,
            "bad_state",
        )

    proposal.status = PipelinePatchStatus.REJECTED
    proposal.decided_by = user.id
    proposal.decided_at = datetime.now(timezone.utc)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "pipeline_patch.rejected",
        {
            "pipeline_id": str(pipeline.id),
            "patch_id": str(proposal.id),
            "title": proposal.title,
        },
        request,
        resource_type="pipeline_patch_proposal",
        resource_id=str(proposal.id),
    )
    await db.commit()
    return success({"id": str(proposal.id), "status": "rejected"})


@router.post("/{pipeline_id}/patches/{patch_id}/rollback")
async def rollback_patch(
    pipeline_id: str,
    patch_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Roll back an accepted patch by restoring the snapshot apply took.

    Allowed for admins, the pipeline owner, or the user who approved the
    patch. Refuses with 409 when the live config no longer matches what the
    patch produced, so a later edit is never silently discarded.
    """
    pipeline = await _load_pipeline(db, user, pipeline_id)
    if not pipeline:
        return error("Pipeline not found", 404, "not_found")

    proposal = await _load_proposal(db, user, pipeline, patch_id)
    if not proposal:
        return error("Patch not found", 404, "not_found")
    if not _can_edit_pipeline(user, pipeline, proposal):
        return error(
            "Only admins, the pipeline owner or the approver can roll back",
            403,
            "forbidden",
        )
    if proposal.status != PipelinePatchStatus.ACCEPTED:
        return error("Only accepted patches can be rolled back", 400, "bad_state")
    if proposal.rolled_back_at:
        return error("Patch was already rolled back", 400, "bad_state")

    restore_cfg = proposal.applied_snapshot or (proposal.dsl_before or {}).get(
        "pipeline_config"
    )
    if not restore_cfg:
        return error("No snapshot to restore — cannot roll back safely", 400, "bad_dsl")

    current_cfg = _current_cfg(pipeline)
    current_hash = config_hash(current_cfg)
    applied_hash = config_hash((proposal.dsl_after or {}).get("pipeline_config"))
    if current_hash != applied_hash:
        return error(
            "Pipeline was edited after this patch was applied, roll back by hand",
            409,
            "stale_rollback",
            details={"applied_sha256": applied_hash, "current_sha256": current_hash},
        )

    from app.services import agent_revisions as revs

    prev_state = revs.agent_state(pipeline)
    cfg = dict(pipeline.model_config_ or {})
    cfg["pipeline_config"] = restore_cfg
    pipeline.model_config_ = cfg
    # a rollback is the way back, so it never waits on the eval gate
    try:
        await revs.record_revision(
            db,
            pipeline,
            changed_by=user.id,
            change_type="healing_rollback",
            source="revert",
            previous_state=prev_state,
            diff_summary=f"Healing patch rolled back: {proposal.title}",
        )
    except revs.RevisionWriteError:
        await db.rollback()
        return revs.revision_failed()
    proposal.rolled_back_at = datetime.now(timezone.utc)
    proposal.rolled_back_by = user.id
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "pipeline_patch.rolled_back",
        {
            "pipeline_id": str(pipeline.id),
            "patch_id": str(proposal.id),
            "title": proposal.title,
            "before_sha256": current_hash,
            "after_sha256": config_hash(restore_cfg),
        },
        request,
        resource_type="pipeline_patch_proposal",
        resource_id=str(proposal.id),
    )
    await db.commit()
    return success(
        {"id": str(proposal.id), "rolled_back_at": proposal.rolled_back_at.isoformat()}
    )
