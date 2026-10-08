"""Admin DLQ — list dead-letter executions and trigger replays."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_role
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus  # noqa: E402
from models.dead_letter import DeadLetterExecution  # noqa: E402
from models.execution import Execution, ExecutionStatus  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/admin/dlq", tags=["admin-dlq"])


def _serialize(d: DeadLetterExecution, agent_name: str | None = None) -> dict[str, Any]:
    original = d.original_input or {}
    replay_id = getattr(d, "replay_execution_id", None)
    return {
        "id": str(d.id),
        "execution_id": str(d.execution_id),
        "agent_id": str(d.agent_id) if d.agent_id else None,
        "agent_name": agent_name,
        "failure_code": d.failure_code,
        "error_message": d.error_message,
        "original_input": original,
        "runtime_pool": original.get("runtime_pool") or "default",
        "is_pipeline": bool(original.get("is_pipeline")),
        "replay_count": d.replay_count,
        "last_replay_at": d.last_replay_at.isoformat() if d.last_replay_at else None,
        "replay_execution_id": str(replay_id) if replay_id else None,
        "resolved": d.resolved,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


@router.get("")
async def list_dlq(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(DeadLetterExecution)
        .where(DeadLetterExecution.tenant_id == user.tenant_id)
        .order_by(DeadLetterExecution.created_at.desc())
        .limit(200)
    )
    rows = result.scalars().all()
    # Enrich with agent name where available — single grouped lookup.
    agent_ids = {r.agent_id for r in rows if r.agent_id}
    agent_names: dict[uuid.UUID, str] = {}
    if agent_ids:
        ar = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        for a in ar.scalars().all():
            agent_names[a.id] = a.name
    return success(
        [
            _serialize(r, agent_names.get(r.agent_id) if r.agent_id else None)
            for r in rows
        ]
    )


@router.post("/{dlq_id}/replay")
async def replay_dlq(
    dlq_id: uuid.UUID,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Re-fire an execution from its captured original_input.

    A new execution is created with parent_execution_id pointing at the
    dead-lettered one and dispatched exactly like the original (same pool,
    pipeline flag, message, context). The original row is left untouched.
    """
    result = await db.execute(
        select(DeadLetterExecution).where(
            DeadLetterExecution.id == dlq_id,
            DeadLetterExecution.tenant_id == user.tenant_id,
        )
    )
    d = result.scalar_one_or_none()
    if not d:
        return error("DLQ entry not found", 404)
    if not d.agent_id:
        return error("DLQ entry has no agent — cannot replay", 400)

    agent = (
        await db.execute(select(Agent).where(Agent.id == d.agent_id))
    ).scalar_one_or_none()
    if agent is None or agent.status == AgentStatus.ARCHIVED:
        return error("Agent no longer exists — cannot replay", 400)

    original = d.original_input or {}
    message = original.get("message") or original.get("input_message") or ""
    context = (
        original.get("context") if isinstance(original.get("context"), dict) else {}
    )
    is_pipeline = bool(original.get("is_pipeline")) or (
        (agent.model_config_ or {}).get("mode") == "pipeline"
    )
    pool = (
        original.get("runtime_pool")
        or getattr(agent, "runtime_pool", None)
        or "default"
    )
    model_used = original.get("model_used") or (
        "pipeline" if is_pipeline else (agent.model_config_ or {}).get("model")
    )

    from app.core.acting_subject import subject_columns_for

    _sid, _stype = subject_columns_for(user)
    new_exec = Execution(
        tenant_id=user.tenant_id,
        agent_id=d.agent_id,
        user_id=user.id,
        subject_id=original.get("subject_id") or _sid,
        subject_type=original.get("subject_type") or _stype,
        input_message=message,
        status=ExecutionStatus.RUNNING,
        model_used=model_used,
        model_requested=model_used,
        started_at=datetime.now(timezone.utc),
        parent_execution_id=d.execution_id,
        retry_count=(d.replay_count or 0) + 1,
        trigger_kind="replay",
        trigger_name="Dead letter replay",
    )
    db.add(new_exec)
    d.replay_count = (d.replay_count or 0) + 1
    d.last_replay_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(new_exec)

    # Same path triggers use: queue when exec_remote is on, inline otherwise.
    # dispatch_execution marks the row FAILED itself when the submit fails.
    from app.routers.triggers import dispatch_execution

    _, dispatched = await dispatch_execution(
        db,
        agent=agent,
        user=user,
        message=message,
        context=context,
        execution=new_exec,
    )

    if hasattr(d, "replay_execution_id"):
        d.replay_execution_id = new_exec.id
    if dispatched:
        d.resolved = True
    await db.commit()

    return success(
        {
            "dlq_id": str(d.id),
            "new_execution_id": str(new_exec.id),
            "parent_execution_id": str(d.execution_id),
            "runtime_pool": pool,
            "is_pipeline": is_pipeline,
            "dispatched": dispatched,
            "resolved": d.resolved,
            "replay_count": d.replay_count,
        }
    )
