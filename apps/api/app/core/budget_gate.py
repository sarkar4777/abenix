"""Agent spend caps for the routes that start runs outside /execute."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.core.responses import error


def per_run_cost_limit(agent: Any, requested: Any = None) -> float | None:
    from engine.agent_budget import run_cost_limit

    return run_cost_limit(getattr(agent, "per_execution_cost_limit", None), requested)


async def budget_breach(db: Any, agent: Any, tenant_id: Any) -> Any:
    from engine.agent_budget import check_agent_budget

    return await check_agent_budget(
        db,
        agent_id=agent.id,
        tenant_id=tenant_id,
        agent_name=agent.name,
        daily_cost_limit=getattr(agent, "daily_cost_limit", None),
        daily_budget_usd=getattr(agent, "daily_budget_usd", None),
    )


def breach_response(breach: Any) -> JSONResponse:
    from engine.agent_budget import BUDGET_EXCEEDED

    return error(
        breach.message, 429, error_code=BUDGET_EXCEEDED, details=breach.details()
    )


async def budget_error(db: Any, agent: Any, tenant_id: Any) -> JSONResponse | None:
    breach = await budget_breach(db, agent, tenant_id)
    return breach_response(breach) if breach is not None else None
