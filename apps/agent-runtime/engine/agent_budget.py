"""Per-agent spend caps, checked before a run starts.

daily_cost_limit caps what an agent spends in a UTC day across every caller.
daily_budget_usd caps what one tenant spends on that agent in a UTC day.
per_execution_cost_limit caps one run, checked by the executor after each model call.
A cap of zero or less counts as no cap, the same as the admin screen.

A saved agent run as a pipeline step is billed to the pipeline's execution row,
so its spend is read back from that row's node_results (metadata.billed_agent_id
and metadata.cost) instead of adding a second row that would count twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import text

BUDGET_EXCEEDED = "BUDGET_EXCEEDED"

_SPENT_SQL = text(
    "SELECT COALESCE(SUM(cost), 0) AS spent_all, "
    "COALESCE(SUM(CASE WHEN tenant_id = CAST(:tid AS uuid) THEN cost ELSE 0 END), 0) AS spent_tenant "
    "FROM executions WHERE agent_id = CAST(:aid AS uuid) AND created_at >= :since"
)
_STEP_SPENT_SQL = text(
    "SELECT COALESCE(SUM(c.cost), 0) AS spent_all, "
    "COALESCE(SUM(CASE WHEN c.tenant_id = CAST(:tid AS uuid) THEN c.cost ELSE 0 END), 0) AS spent_tenant "
    "FROM (SELECT e.tenant_id, (nr.value->'metadata'->>'cost')::numeric AS cost "
    "FROM executions e CROSS JOIN LATERAL jsonb_each("
    "CASE WHEN jsonb_typeof(e.node_results) = 'object' THEN e.node_results ELSE '{}'::jsonb END"
    ") nr "
    "WHERE e.created_at >= :since AND e.node_results IS NOT NULL "
    "AND e.agent_id IS DISTINCT FROM CAST(:aid AS uuid) "
    "AND nr.value->'metadata'->>'billed_agent_id' = CAST(:aid AS text) "
    "AND jsonb_typeof(nr.value->'metadata'->'cost') = 'number') c"
)
_CAPS_SQL = text(
    "SELECT name, daily_cost_limit, daily_budget_usd FROM agents WHERE id = CAST(:aid AS uuid)"
)


@dataclass(frozen=True)
class BudgetBreach:
    limit_name: str
    limit: float
    spent: float
    message: str

    def details(self) -> dict[str, Any]:
        return {
            "limit": self.limit_name,
            "cap_usd": self.limit,
            "spent_today_usd": round(self.spent, 4),
        }


def _cap(value: Any) -> float | None:
    try:
        v = float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return v if v and v > 0 else None


def run_cost_limit(*limits: Any) -> float | None:
    """The tightest positive per-run cap among the given values, None when there is none."""
    caps = [c for c in (_cap(v) for v in limits) if c is not None]
    return min(caps) if caps else None


def run_budget_message(limit: float, spent: float) -> str:
    return (
        f"This run stopped at its per-run budget of ${limit:,.2f} "
        f"(${spent:,.4f} spent). The work done so far is kept in the trace. "
        "The agent's owner can raise the per-run cost limit."
    )


def day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime.combine(
        now.astimezone(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )


def evaluate(
    agent_name: str,
    *,
    daily_cost_limit: Any,
    daily_budget_usd: Any,
    spent_all: float,
    spent_tenant: float,
) -> BudgetBreach | None:
    name = agent_name or "This agent"
    agent_cap = _cap(daily_cost_limit)
    if agent_cap is not None and spent_all >= agent_cap:
        return BudgetBreach(
            "daily_cost_limit",
            agent_cap,
            spent_all,
            f"{name} has reached its daily spending limit of ${agent_cap:,.2f} "
            f"(${spent_all:,.2f} spent today, UTC). New runs can start after midnight UTC, "
            "or the agent's owner can raise the limit.",
        )
    tenant_cap = _cap(daily_budget_usd)
    if tenant_cap is not None and spent_tenant >= tenant_cap:
        return BudgetBreach(
            "daily_budget_usd",
            tenant_cap,
            spent_tenant,
            f"{name} has used its daily budget of ${tenant_cap:,.2f} for your organization "
            f"(${spent_tenant:,.2f} spent today, UTC). New runs can start after midnight UTC, "
            "or an admin can raise the budget under Admin, Scaling.",
        )
    return None


async def spent_today(
    session: Any, agent_id: Any, tenant_id: Any, now: datetime | None = None
) -> tuple[float, float]:
    params = {"aid": str(agent_id), "tid": str(tenant_id), "since": day_start(now)}
    spent_all = spent_tenant = 0.0
    for sql in (_SPENT_SQL, _STEP_SPENT_SQL):
        row = (await session.execute(sql, params)).first()
        if row:
            spent_all += float(row[0] or 0)
            spent_tenant += float(row[1] or 0)
    return spent_all, spent_tenant


async def check_agent_budget(
    session: Any,
    *,
    agent_id: Any,
    tenant_id: Any,
    agent_name: str,
    daily_cost_limit: Any,
    daily_budget_usd: Any,
    now: datetime | None = None,
) -> BudgetBreach | None:
    if _cap(daily_cost_limit) is None and _cap(daily_budget_usd) is None:
        return None
    spent_all, spent_tenant = await spent_today(session, agent_id, tenant_id, now)
    return evaluate(
        agent_name,
        daily_cost_limit=daily_cost_limit,
        daily_budget_usd=daily_budget_usd,
        spent_all=spent_all,
        spent_tenant=spent_tenant,
    )


async def check_agent_budget_by_id(
    session: Any, agent_id: Any, tenant_id: Any, now: datetime | None = None
) -> BudgetBreach | None:
    row = (await session.execute(_CAPS_SQL, {"aid": str(agent_id)})).first()
    if not row:
        return None
    return await check_agent_budget(
        session,
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_name=row[0],
        daily_cost_limit=row[1],
        daily_budget_usd=row[2],
        now=now,
    )
