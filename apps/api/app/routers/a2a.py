"""Agent-to-Agent Protocol (A2A) — cross-platform agent discovery and invocation."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent, AgentStatus

router = APIRouter(prefix="/api/a2a", tags=["a2a"])


@router.get("/discover")
async def discover_agents(
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Public endpoint: discover all published agents on this Abenix instance."""
    result = await db.execute(
        select(Agent).where(
            Agent.is_published.is_(True), Agent.status == AgentStatus.ACTIVE
        )
    )
    agents = result.scalars().all()
    return success(
        {
            "protocol": "abenix-a2a-v1",
            "instance": "abenix",
            "agent_count": len(agents),
            "agents": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "slug": a.slug,
                    "description": a.description,
                    "category": a.category,
                    "model": (a.model_config_ or {}).get(
                        "model", "claude-sonnet-4-5-20250929"
                    ),
                    "tools": (a.model_config_ or {}).get("tools", []),
                    "input_variables": (a.model_config_ or {}).get(
                        "input_variables", []
                    ),
                    "card_url": f"/api/a2a/agents/{a.id}/card",
                    "invoke_url": f"/api/a2a/agents/{a.id}/invoke",
                }
                for a in agents
            ],
        }
    )


@router.get("/agents/{agent_id}/card")
async def get_agent_card(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Public endpoint: return A2A agent card with capabilities and input schema."""
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.status == AgentStatus.ACTIVE)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found or not active", 404)

    mc = agent.model_config_ or {}
    input_vars = mc.get("input_variables", [])

    # Build input schema from input_variables
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The task or prompt for the agent",
            },
        },
        "required": ["message"],
    }
    for v in input_vars:
        input_schema["properties"][v["name"]] = {
            "type": v.get("type", "string"),
            "description": v.get("description", ""),
        }
        if v.get("required"):
            input_schema["required"].append(v["name"])

    return success(
        {
            "protocol": "abenix-a2a-v1",
            "agent": {
                "id": str(agent.id),
                "name": agent.name,
                "slug": agent.slug,
                "description": agent.description,
                "category": agent.category,
                "version": agent.version,
            },
            "capabilities": {
                "model": mc.get("model", "claude-sonnet-4-5-20250929"),
                "tools": mc.get("tools", []),
                "mode": mc.get("mode", "agent"),
                "max_iterations": mc.get("max_iterations", 10),
                "streaming": True,
            },
            "input_schema": input_schema,
            "authentication": {
                "type": "api_key",
                "header": "X-API-Key",
                "description": "Abenix API key with execute permission",
            },
            "invoke_url": f"/api/a2a/agents/{agent.id}/invoke",
            "pricing": {
                "type": "per_execution",
                "estimated_cost_usd": 0.01,
                "currency": "USD",
            },
        }
    )


@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(
    agent_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """A2A invocation: execute an agent from an external platform."""
    # Auth via API key
    api_key = request.headers.get("x-api-key", "")
    if not api_key:
        return error("X-API-Key header required for A2A invocation", 401)

    from app.core.deps import _authenticate_via_api_key

    user = await _authenticate_via_api_key(api_key, db)
    if not user:
        return error("Invalid API key", 401)

    # Parse request
    try:
        body = await request.json()
    except Exception:
        return error("Invalid JSON body", 400)

    message = body.get("message", "")
    context = body.get("context", {})
    requested_limit = body.get("cost_limit")

    if not message:
        return error("message is required", 400)

    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.status == AgentStatus.ACTIVE)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return error("Agent not found or not active", 404)
    from app.services.agent_share import resolve_agent_access
    from models.resource_share import SharePermission

    if not agent.is_published and not await resolve_agent_access(
        db, user, agent, permission_required=SharePermission.EXECUTE
    ):
        return error("Agent not found or not active", 404)

    from app.core.budget_gate import budget_error, per_run_cost_limit

    over = await budget_error(db, agent, user.tenant_id)
    if over is not None:
        return over

    from app.core.acting_subject import subject_columns_for
    from app.core.config import settings
    from app.services import inline_run
    from engine.agent_executor import AgentExecutor
    from engine.llm_router import LLMRouter

    mc = agent.model_config_ or {}
    model = mc.get("model", "claude-sonnet-4-5-20250929")
    if mc.get("mode") == "pipeline":
        return error(
            "Pipeline agents run through /api/agents/{id}/execute, not a2a.", 400
        )

    if context:
        context_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
        message = f"{message}\n\n[Input Parameters]\n{context_lines}"

    execution = inline_run.open_run(
        agent=agent,
        user=user,
        message=message,
        model=model,
        subject=subject_columns_for(user),
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
        user_role=user.role.value if hasattr(user.role, "value") else str(user.role),
    )

    executor = AgentExecutor(
        llm_router=LLMRouter(),
        tool_registry=parts["registry"],
        system_prompt=parts["system_prompt"],
        moderation_gate=parts["moderation"].gate,
        model=model,
        temperature=mc.get("temperature", 0.3),
        agent_id=str(agent.id),
        execution_id=str(execution.id),
        tenant_id=str(user.tenant_id),
        cost_limit=per_run_cost_limit(agent, requested_limit),
    )

    try:
        result = await executor.invoke(message)
    except Exception as e:
        inline_run.record_error(execution, e)
        await inline_run.after(db, execution, parts)
        await inline_run.settle(db, execution, getattr(user, "_api_key_id", None))
        return error(
            f"Execution failed: {str(e)[:500]}",
            500,
            details={"execution_id": str(execution.id)},
        )
    code = inline_run.record_result(execution, result, "a2a")
    await inline_run.after(db, execution, parts)
    await inline_run.settle(db, execution, getattr(user, "_api_key_id", None))
    return success(
        {
            "protocol": "abenix-a2a-v1",
            "execution_id": str(execution.id),
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "status": execution.status.value,
            "failure_code": code,
            "output": result.output,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost": float(result.cost),
            "duration_ms": result.duration_ms,
            "tool_calls": result.tool_calls,
        }
    )
