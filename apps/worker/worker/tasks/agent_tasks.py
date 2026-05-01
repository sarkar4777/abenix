"""Celery task: execute an agent asynchronously.

Mirrors the API's _non_stream_execution logic but runs in a Celery worker.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Add agent-runtime and packages/db to sys.path
_root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_root / "apps" / "agent-runtime"))
sys.path.insert(0, str(_root / "packages" / "db"))

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
)


def _get_sync_db_url() -> str:
    """Convert async DB URL to sync psycopg2-compatible URL."""
    return DATABASE_URL.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )


def _fetch_agent(agent_id: str) -> dict[str, Any] | None:
    """Fetch agent config from DB using psycopg2."""
    import psycopg2

    conn = psycopg2.connect(_get_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, system_prompt, model_config_, status "
                "FROM agents WHERE id = %s",
                (agent_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            model_config = row[3]
            if isinstance(model_config, str):
                model_config = json.loads(model_config)

            return {
                "id": str(row[0]),
                "tenant_id": str(row[1]),
                "system_prompt": row[2] or "",
                "model_config": model_config or {},
                "status": row[4],
            }
    finally:
        conn.close()


def _update_execution(
    execution_id: str,
    status: str,
    output: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float = 0.0,
    anthropic_cost: float = 0.0,
    openai_cost: float = 0.0,
    google_cost: float = 0.0,
    other_cost: float = 0.0,
    duration_ms: int = 0,
    tool_calls: list[dict[str, Any]] | None = None,
    error_message: str | None = None,
) -> None:
    """Update execution record in DB with per-provider cost split."""
    import psycopg2

    conn = psycopg2.connect(_get_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE executions SET "
                "status = %s, output_message = %s, "
                "input_tokens = %s, output_tokens = %s, "
                "cost = %s, "
                "anthropic_cost = %s, openai_cost = %s, "
                "google_cost = %s, other_cost = %s, "
                "duration_ms = %s, "
                "tool_calls = %s, error_message = %s, "
                "completed_at = %s "
                "WHERE id = %s",
                (
                    status.upper(),
                    output,
                    input_tokens,
                    output_tokens,
                    cost,
                    anthropic_cost,
                    openai_cost,
                    google_cost,
                    other_cost,
                    duration_ms,
                    json.dumps(tool_calls) if tool_calls else None,
                    error_message,
                    datetime.now(timezone.utc),
                    execution_id,
                ),
            )
            conn.commit()
    finally:
        conn.close()


async def _run_agent_async(
    agent_id: str,
    message: str,
) -> dict[str, Any]:
    """Async wrapper: create executor and invoke."""
    from engine.agent_executor import AgentExecutor, build_tool_registry
    from engine.llm_router import LLMRouter

    agent = _fetch_agent(agent_id)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found")

    if agent["status"] != "ACTIVE":
        raise ValueError(f"Agent {agent_id} is not active (status={agent['status']})")

    model_cfg = agent["model_config"]
    model = model_cfg.get("model", "claude-sonnet-4-5-20250929")
    temperature = model_cfg.get("temperature", 0.7)
    tool_names = model_cfg.get("tools", [])

    llm_router = LLMRouter()
    tool_registry = build_tool_registry(tool_names)

    executor = AgentExecutor(
        llm_router=llm_router,
        tool_registry=tool_registry,
        system_prompt=agent["system_prompt"],
        model=model,
        temperature=temperature,
        agent_id=agent_id,
    )

    result = await executor.invoke(message)

    return {
        "output": result.output,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost": round(result.cost, 6),
        "anthropic_cost": round(result.anthropic_cost, 6),
        "openai_cost": round(result.openai_cost, 6),
        "google_cost": round(result.google_cost, 6),
        "other_cost": round(result.other_cost, 6),
        "duration_ms": result.duration_ms,
        "tool_calls": result.tool_calls,
        "model": result.model,
    }


@celery_app.task(
    bind=True,
    name="worker.tasks.agent_tasks.run_agent",
    max_retries=1,
    default_retry_delay=10,
)
def run_agent(
    self,
    agent_id: str,
    session_id: str,
    message: str,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Execute an agent run asynchronously via Celery."""
    self.update_state(
        state="RUNNING",
        meta={"agent_id": agent_id, "step": "initializing"},
    )

    try:
        self.update_state(
            state="RUNNING",
            meta={"agent_id": agent_id, "step": "executing"},
        )
        result = asyncio.run(_run_agent_async(agent_id, message))

        if execution_id:
            _update_execution(
                execution_id=execution_id,
                status="COMPLETED",
                output=result["output"],
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                cost=result["cost"],
                anthropic_cost=result.get("anthropic_cost", 0.0),
                openai_cost=result.get("openai_cost", 0.0),
                google_cost=result.get("google_cost", 0.0),
                other_cost=result.get("other_cost", 0.0),
                duration_ms=result["duration_ms"],
                tool_calls=result["tool_calls"],
            )

        return {
            "status": "completed",
            "agent_id": agent_id,
            "session_id": session_id,
            **result,
        }

    except Exception as exc:
        logger.exception("Agent execution failed: agent=%s", agent_id)

        if execution_id:
            _update_execution(
                execution_id=execution_id,
                status="FAILED",
                error_message=str(exc),
            )

        raise self.retry(exc=exc)
