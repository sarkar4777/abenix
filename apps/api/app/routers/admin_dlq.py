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

from app.core.deps import get_current_user, get_db, require_role
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent  # noqa: E402
from models.dead_letter import DeadLetterExecution  # noqa: E402
from models.execution import Execution, ExecutionStatus  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/admin/dlq", tags=["admin-dlq"])


def _serialize(d: DeadLetterExecution, agent_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "execution_id": str(d.execution_id),
        "agent_id": str(d.agent_id) if d.agent_id else None,
        "agent_name": agent_name,
        "failure_code": d.failure_code,
        "error_message": d.error_message,
        "original_input": d.original_input or {},
        "replay_count": d.replay_count,
        "last_replay_at": d.last_replay_at.isoformat() if d.last_replay_at else None,
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

    Implementation: clone the original Execution row to a new RUNNING execution
    and dispatch via the same agent execute path. This avoids mutating the
    original failed row so audit trails stay intact.
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

    original = d.original_input or {}
    message = original.get("message") or original.get("input_message") or ""
    context = original.get("context") or {}

    new_exec = Execution(
        tenant_id=user.tenant_id,
        agent_id=d.agent_id,
        user_id=user.id,
        input_message=message,
        status=ExecutionStatus.RUNNING,
        model_used="replay",
    )
    db.add(new_exec)
    d.replay_count = (d.replay_count or 0) + 1
    d.last_replay_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(new_exec)

    # Best-effort dispatch via the queue backend; fall back to inline marker.
    try:
        runtime_path = Path(__file__).resolve().parents[3] / "agent-runtime"
        if str(runtime_path) not in sys.path and runtime_path.exists():
            sys.path.insert(0, str(runtime_path))
        from engine.queue_backend import get_queue_backend  # type: ignore

        backend = get_queue_backend()
        await backend.submit(
            "default",
            {
                "execution_id": str(new_exec.id),
                "agent_id": str(d.agent_id),
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "message": message,
                "context": context,
                "is_pipeline": False,
            },
        )
        dispatched = True
    except Exception:
        dispatched = False

    return success(
        {
            "dlq_id": str(d.id),
            "new_execution_id": str(new_exec.id),
            "dispatched": dispatched,
            "replay_count": d.replay_count,
        }
    )
