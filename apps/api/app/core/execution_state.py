"""Execution State Store — Redis-backed live state tracking for running agents."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: aioredis.Redis | None = None
_redis_available = True  # circuit breaker flag

STATE_TTL = 3600  # 1 hour


async def _get_redis() -> aioredis.Redis | None:
    """Get Redis connection. Returns None if Redis is unavailable."""
    global _pool, _redis_available
    if not _redis_available:
        return None
    try:
        if _pool is None:
            _pool = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        # Quick ping to verify connection
        await _pool.ping()
        return _pool
    except Exception as e:
        logger.warning("Redis unavailable for execution state: %s", e)
        _redis_available = False
        _pool = None
        # Auto-retry after 30 seconds
        import asyncio
        async def _reset_flag():
            await asyncio.sleep(30)
            global _redis_available
            _redis_available = True
        asyncio.create_task(_reset_flag())
        return None


def _live_key(execution_id: str) -> str:
    return f"exec:live:{execution_id}"


def _tree_key(parent_id: str) -> str:
    return f"exec:tree:{parent_id}"


def _tenant_key(tenant_id: str) -> str:
    return f"exec:tenant:{tenant_id}"


async def publish_state(
    execution_id: str,
    tenant_id: str,
    agent_id: str,
    agent_name: str,
    status: str,
    *,
    current_step: str | None = None,
    current_tool: str | None = None,
    node_statuses: dict[str, str] | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    iteration: int = 0,
    max_iterations: int = 10,
    error_message: str | None = None,
    parent_execution_id: str | None = None,
    confidence_score: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Publish or update the live state for an execution."""
    r = await _get_redis()
    if r is None:
        return  # Redis unavailable, skip live state
    key = _live_key(execution_id)
    now = datetime.now(timezone.utc).isoformat()

    state = {
        "execution_id": execution_id,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": status,
        "current_step": current_step or "",
        "current_tool": current_tool or "",
        "node_statuses": json.dumps(node_statuses or {}),
        "input_tokens": str(input_tokens),
        "output_tokens": str(output_tokens),
        "cost": str(cost),
        "iteration": str(iteration),
        "max_iterations": str(max_iterations),
        "error_message": error_message or "",
        "parent_execution_id": parent_execution_id or "",
        "confidence_score": str(confidence_score) if confidence_score is not None else "",
        "metadata": json.dumps(metadata or {}),
        "updated_at": now,
    }

    pipe = r.pipeline()
    pipe.hset(key, mapping=state)
    pipe.expire(key, STATE_TTL)
    pipe.sadd(_tenant_key(tenant_id), execution_id)

    if parent_execution_id:
        tree_key = _tree_key(parent_execution_id)
        pipe.sadd(tree_key, execution_id)
        pipe.expire(tree_key, STATE_TTL)

    await pipe.execute()


async def complete_state(execution_id: str, tenant_id: str) -> None:
    """Mark execution as complete and remove from active set."""
    r = await _get_redis()
    if r is None:
        return
    key = _live_key(execution_id)

    pipe = r.pipeline()
    pipe.hset(key, "status", "completed")
    pipe.hset(key, "updated_at", datetime.now(timezone.utc).isoformat())
    pipe.expire(key, STATE_TTL)
    pipe.srem(_tenant_key(tenant_id), execution_id)
    await pipe.execute()


async def fail_state(execution_id: str, tenant_id: str, error_message: str) -> None:
    """Mark execution as failed."""
    r = await _get_redis()
    if r is None:
        return
    key = _live_key(execution_id)

    pipe = r.pipeline()
    pipe.hset(key, mapping={
        "status": "failed",
        "error_message": error_message,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    pipe.expire(key, STATE_TTL)
    pipe.srem(_tenant_key(tenant_id), execution_id)
    await pipe.execute()


async def get_live_state(execution_id: str) -> dict[str, Any] | None:
    """Get the current live state for an execution."""
    r = await _get_redis()
    if r is None:
        return None
    state = await r.hgetall(_live_key(execution_id))
    if not state:
        return None
    # Deserialize JSON fields
    state["node_statuses"] = json.loads(state.get("node_statuses", "{}"))
    state["metadata"] = json.loads(state.get("metadata", "{}"))
    state["input_tokens"] = int(state.get("input_tokens", 0))
    state["output_tokens"] = int(state.get("output_tokens", 0))
    state["cost"] = float(state.get("cost", 0))
    state["iteration"] = int(state.get("iteration", 0))
    state["max_iterations"] = int(state.get("max_iterations", 10))
    if state.get("confidence_score"):
        state["confidence_score"] = float(state["confidence_score"])
    else:
        state["confidence_score"] = None
    return state


async def get_tenant_live_executions(tenant_id: str) -> list[dict[str, Any]]:
    """Get all currently-running executions for a tenant."""
    r = await _get_redis()
    if r is None:
        return []
    exec_ids = await r.smembers(_tenant_key(tenant_id))
    if not exec_ids:
        return []

    results = []
    for eid in exec_ids:
        state = await get_live_state(eid)
        if state:
            results.append(state)
        else:
            # Clean up stale reference
            await r.srem(_tenant_key(tenant_id), eid)
    return results


async def get_execution_tree(execution_id: str) -> dict[str, Any]:
    """Get the execution tree (parent + children) for an execution."""
    r = await _get_redis()
    if r is None:
        return {"parent": None, "children": []}

    parent_state = await get_live_state(execution_id)
    if not parent_state:
        return {"parent": None, "children": []}

    child_ids = await r.smembers(_tree_key(execution_id))
    children = []
    for cid in child_ids:
        child_state = await get_live_state(cid)
        if child_state:
            children.append(child_state)

    return {"parent": parent_state, "children": children}
