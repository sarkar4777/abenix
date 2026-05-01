"""Batch Execution API — Execute an agent against multiple inputs in parallel."""
from __future__ import annotations

import asyncio
import uuid
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
from models.execution import Execution, ExecutionStatus
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

    # Verify agent exists and is active
    result = await db.execute(
        select(Agent).where(
            Agent.id == uuid.UUID(agent_id),
            or_(Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found", 404)
    if agent.status != AgentStatus.ACTIVE:
        return error("Agent is not active", 400)

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

    # Launch batch execution in background
    asyncio.create_task(
        _run_batch(batch_id, agent, user, inputs, max_concurrency, db)
    )

    return success({
        "batch_id": batch_id,
        "status": "running",
        "total_inputs": len(inputs),
        "max_concurrency": max_concurrency,
    }, status_code=202)


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


async def _run_batch(
    batch_id: str,
    agent: Agent,
    user: User,
    inputs: list[dict[str, Any]],
    max_concurrency: int,
    db: AsyncSession,
) -> None:
    """Execute all inputs against the agent with bounded concurrency."""
    from app.core.config import settings

    semaphore = asyncio.Semaphore(max_concurrency)
    job = await _load_batch(batch_id) or {}

    async def run_one(idx: int, inp: dict[str, Any]) -> None:
        async with semaphore:
            message = inp.get("message", "")
            context = inp.get("context", {})

            try:
                from engine.llm_router import LLMRouter
                from engine.agent_executor import AgentExecutor, build_tool_registry

                model_cfg = agent.model_config_ or {}
                tool_names = model_cfg.get("tools", [])

                registry = build_tool_registry(
                    tool_names,
                    agent_id=str(agent.id),
                    tenant_id=str(user.tenant_id),
                    execution_id=str(uuid.uuid4()),
                    agent_name=agent.name,
                    db_url=str(settings.database_url).replace("+asyncpg", ""),
                )

                executor = AgentExecutor(
                    llm_router=LLMRouter(),
                    tool_registry=registry,
                    system_prompt=agent.system_prompt or "",
                    model=model_cfg.get("model", "claude-sonnet-4-5-20250929"),
                    temperature=model_cfg.get("temperature", 0.3),
                    agent_id=str(agent.id),
                )

                result = await executor.invoke(message)

                current = await _load_batch(batch_id) or job
                current.setdefault("results", []).append({
                    "index": idx,
                    "status": "completed",
                    "output": result.output[:2000],
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost": float(result.cost),
                    "duration_ms": result.duration_ms,
                })
                current["completed"] = current.get("completed", 0) + 1
                await _save_batch(batch_id, current)

            except Exception as e:
                current = await _load_batch(batch_id) or job
                current.setdefault("results", []).append({
                    "index": idx,
                    "status": "failed",
                    "error": str(e)[:500],
                })
                current["failed"] = current.get("failed", 0) + 1
                await _save_batch(batch_id, current)

    tasks = [run_one(i, inp) for i, inp in enumerate(inputs)]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Reload latest state and finalize
    job = await _load_batch(batch_id) or job
    job["status"] = "completed" if job.get("failed", 0) == 0 else "partial"
    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    await _save_batch(batch_id, job)
