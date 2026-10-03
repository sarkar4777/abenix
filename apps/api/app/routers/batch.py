"""Batch Execution API — Execute an agent against multiple inputs in parallel."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus, AgentType
from models.user import User

router = APIRouter(prefix="/api/batch", tags=["batch"])


async def _get_redis():
    import redis.asyncio as aioredis
    from app.core.config import settings

    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def _save_batch(batch_id: str, data: dict[str, Any]) -> None:
    """Persist batch state to Redis (survives API restarts)."""
    import json

    r = await _get_redis()
    await r.set(f"batch:{batch_id}", json.dumps(data, default=str), ex=86400)  # 24h TTL
    await r.aclose()


async def _load_batch(batch_id: str) -> dict[str, Any] | None:
    """Load batch state from Redis."""
    import json

    r = await _get_redis()
    raw = await r.get(f"batch:{batch_id}")
    await r.aclose()
    return json.loads(raw) if raw else None


@router.post("/execute")
async def batch_execute(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    agent_id = body.get("agent_id")
    inputs = body.get("inputs", [])
    max_concurrency = min(body.get("max_concurrency", 5), 20)

    if not agent_id:
        return error("agent_id is required", 400)
    if not inputs or not isinstance(inputs, list):
        return error("inputs must be a non-empty array", 400)
    if len(inputs) > 1000:
        return error("Maximum 1000 inputs per batch", 400)

    try:
        agent_uuid = uuid.UUID(str(agent_id))
    except ValueError:
        return error("agent_id must be a UUID", 400)
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_uuid,
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)
    from app.services.agent_share import resolve_agent_access
    from models.resource_share import SharePermission

    if not await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EXECUTE
    ):
        return error("You do not have access to this agent", 403)
    if agent.status != AgentStatus.ACTIVE:
        return error("Agent is not active", 400)

    from app.core.budget_gate import budget_error

    over = await budget_error(db, agent, user.tenant_id)
    if over is not None:
        return over

    batch_id = str(uuid.uuid4())
    batch_state = {
        "id": batch_id,
        "agent_id": agent_id,
        "agent_name": agent.name,
        "tenant_id": str(user.tenant_id),
        "user_id": str(user.id),
        "status": "running",
        "total": len(inputs),
        "completed": 0,
        "failed": 0,
        "results": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await _save_batch(batch_id, batch_state)

    # Launch batch execution in background. Do NOT pass the request's `db`
    # session — it gets closed when this request returns, and the background
    # fan-out (asyncio.gather) cannot share a single asyncpg connection across
    # overlapping awaits anyway. The task opens its own session if it needs one.
    from app.core.acting_subject import subject_columns_for

    run_as = _RunAs(
        user=user,
        subject=subject_columns_for(user),
        api_key_id=getattr(user, "_api_key_id", None),
        cost_limit=body.get("cost_limit"),
    )
    asyncio.create_task(_run_batch(batch_id, agent, run_as, inputs, max_concurrency))

    return success(
        {
            "batch_id": batch_id,
            "status": "running",
            "total_inputs": len(inputs),
            "max_concurrency": max_concurrency,
        },
        status_code=202,
    )


@router.get("/{batch_id}")
async def get_batch_status(
    batch_id: str,
    user: User = Depends(get_current_user),
) -> Any:
    job = await _load_batch(batch_id)
    if not job:
        return error("Batch job not found", 404)
    if job.get("tenant_id") != str(user.tenant_id):
        return error("Batch job not found", 404)

    return success(job)


@dataclass
class _RunAs:
    user: Any
    subject: tuple
    api_key_id: Any = None
    cost_limit: Any = None


async def _append_result(
    batch_id: str, job: dict[str, Any], entry: dict[str, Any], ok: bool
) -> None:
    current = await _load_batch(batch_id) or job
    current.setdefault("results", []).append(entry)
    key = "completed" if ok else "failed"
    current[key] = current.get(key, 0) + 1
    await _save_batch(batch_id, current)


async def _run_one(
    agent: Agent, run_as: _RunAs, message: str
) -> tuple[bool, dict[str, Any]]:
    """One input as its own recorded run, refused when the agent's daily cap is spent."""
    from app.core.budget_gate import budget_breach, per_run_cost_limit
    from app.core.config import settings
    from app.core.deps import async_session
    from app.services import inline_run
    from engine.agent_budget import BUDGET_EXCEEDED
    from engine.agent_executor import AgentExecutor
    from engine.llm_router import LLMRouter

    user = run_as.user
    model_cfg = agent.model_config_ or {}
    model = model_cfg.get("model", "claude-sonnet-4-5-20250929")
    if model_cfg.get("mode") == "pipeline":
        return False, {
            "status": "failed",
            "error": "Pipeline agents run through /api/agents/{id}/execute, not batch.",
        }
    async with async_session() as db:
        breach = await budget_breach(db, agent, user.tenant_id)
        if breach is not None:
            return False, {
                "status": "failed",
                "failure_code": BUDGET_EXCEEDED,
                "error": breach.message,
            }
        execution = inline_run.open_run(
            agent=agent,
            user=user,
            message=message,
            model=model,
            subject=run_as.subject,
        )
        db.add(execution)
        await db.commit()
        await db.refresh(execution)
        parts = await inline_run.prepare(
            db,
            agent,
            user,
            execution,
            agent_id=str(agent.id),
            tenant_id=str(user.tenant_id),
            execution_id=str(execution.id),
            agent_name=agent.name,
            db_url=str(settings.database_url).replace("+asyncpg", ""),
            user_id=str(user.id),
            user_role=(
                user.role.value if hasattr(user.role, "value") else str(user.role)
            ),
        )
    executor = AgentExecutor(
        llm_router=LLMRouter(),
        tool_registry=parts["registry"],
        system_prompt=parts["system_prompt"],
        moderation_gate=parts["moderation"].gate,
        model=model,
        temperature=model_cfg.get("temperature", 0.3),
        agent_id=str(agent.id),
        execution_id=str(execution.id),
        tenant_id=str(user.tenant_id),
        cost_limit=per_run_cost_limit(agent, run_as.cost_limit),
    )
    result = None
    try:
        result = await executor.invoke(message)
        code = inline_run.record_result(execution, result, "batch")
    except Exception as e:
        code = inline_run.record_error(execution, e)
    async with async_session() as db:
        execution = await db.merge(execution)
        await inline_run.after(db, execution, parts)
        await inline_run.settle(db, execution, run_as.api_key_id)

    entry: dict[str, Any] = {
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "cost": float(execution.cost or 0),
        "input_tokens": execution.input_tokens or 0,
        "output_tokens": execution.output_tokens or 0,
        "duration_ms": execution.duration_ms,
    }
    if result is not None:
        entry["output"] = (result.output or "")[:2000]
    if code:
        entry["failure_code"] = code
        entry["error"] = (execution.error_message or "")[:500]
    return code is None, entry


async def _run_batch(
    batch_id: str,
    agent: Agent,
    run_as: _RunAs,
    inputs: list[dict[str, Any]],
    max_concurrency: int,
) -> None:
    """Execute all inputs against the agent with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrency)
    job = await _load_batch(batch_id) or {}

    async def run_one(idx: int, inp: dict[str, Any]) -> None:
        async with semaphore:
            message = str(inp.get("message", "") if isinstance(inp, dict) else inp)
            context = inp.get("context") if isinstance(inp, dict) else None
            if context:
                lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
                message = f"{message}\n\n[Input Parameters]\n{lines}"
            try:
                ok, entry = await _run_one(agent, run_as, message)
            except Exception as e:
                ok, entry = False, {"status": "failed", "error": str(e)[:500]}
            await _append_result(batch_id, job, {"index": idx, **entry}, ok)

    tasks = [run_one(i, inp) for i, inp in enumerate(inputs)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Reload latest state and finalize
    job = await _load_batch(batch_id) or job
    job["status"] = "completed" if job.get("failed", 0) == 0 else "partial"
    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    await _save_batch(batch_id, job)
