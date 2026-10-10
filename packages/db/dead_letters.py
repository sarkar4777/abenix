"""Dead-letter queue writes. One row per execution, carries what replay needs.

Lives beside the models so the API and the agent runtime write the same rows,
the runtime image does not ship the API package."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.dead_letter import DeadLetterExecution
from models.execution import Execution

logger = logging.getLogger("abenix.dlq")


def _as_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def build_original_input(
    execution: Execution,
    agent: Agent | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Snapshot everything replay needs to re-dispatch identically."""
    payload = payload or {}
    model_cfg = (getattr(agent, "model_config_", None) or {}) if agent else {}
    is_pipeline = payload.get("is_pipeline")
    if is_pipeline is None:
        is_pipeline = model_cfg.get("mode") == "pipeline" or (
            execution.model_used == "pipeline"
        )
    runtime_pool = payload.get("runtime_pool") or (
        getattr(agent, "runtime_pool", None) if agent else None
    )
    context = payload.get("context")
    return {
        "message": payload.get("message") or execution.input_message or "",
        "context": context if isinstance(context, dict) else {},
        "runtime_pool": runtime_pool or "default",
        "is_pipeline": bool(is_pipeline),
        "user_id": str(execution.user_id) if execution.user_id else None,
        "api_key_id": payload.get("api_key_id"),
        "subject_id": getattr(execution, "subject_id", None),
        "subject_type": getattr(execution, "subject_type", None),
        "model_used": execution.model_used,
        "trigger_id": payload.get("trigger_id"),
    }


async def get_dead_letter(
    db: AsyncSession, execution_id: uuid.UUID
) -> DeadLetterExecution | None:
    r = await db.execute(
        select(DeadLetterExecution).where(
            DeadLetterExecution.execution_id == execution_id
        )
    )
    return r.scalars().first()


async def dead_letter(
    db: AsyncSession,
    execution: Execution | uuid.UUID | str,
    *,
    reason: str,
    failure_code: str,
    payload: dict[str, Any] | None = None,
) -> DeadLetterExecution | None:
    """Record a terminal failure in the DLQ. Idempotent per execution.

    Caller commits. Returns the existing row on a repeat call, None when
    the execution cannot be found.
    """
    if not isinstance(execution, Execution):
        ex_id = _as_uuid(execution)
        if ex_id is None:
            return None
        execution = (
            await db.execute(select(Execution).where(Execution.id == ex_id))
        ).scalar_one_or_none()
        if execution is None:
            logger.warning("dead_letter: execution %s not found", ex_id)
            return None

    existing = await get_dead_letter(db, execution.id)
    if existing is not None:
        return existing

    agent = None
    if execution.agent_id:
        agent = (
            await db.execute(select(Agent).where(Agent.id == execution.agent_id))
        ).scalar_one_or_none()

    row = DeadLetterExecution(
        tenant_id=execution.tenant_id,
        execution_id=execution.id,
        agent_id=execution.agent_id,
        failure_code=(failure_code or "UNKNOWN")[:80],
        error_message=(reason or "")[:2000] or None,
        original_input=build_original_input(execution, agent, payload),
        replay_count=0,
        resolved=False,
    )
    try:
        # Savepoint so a unique-index race only undoes this insert.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return await get_dead_letter(db, execution.id)
    return row
