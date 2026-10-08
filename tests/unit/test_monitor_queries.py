"""Scaling list filters and the analytics leaderboard order."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.routers.admin_scaling import agent_scale_filters
from app.routers.analytics import _by_usage
from models.agent import Agent
from models.execution import Execution


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_scaling_search_matches_name_or_slug_and_pool():
    sql = _sql(select(Agent.id).where(*agent_scale_filters("chat", " wingman ")))
    assert "agents.runtime_pool = 'chat'" in sql
    assert "agents.name ILIKE '%%wingman%%'" in sql
    assert "agents.slug ILIKE '%%wingman%%'" in sql


def test_scaling_without_filters_has_no_where():
    assert agent_scale_filters() == []
    assert agent_scale_filters("", "   ") == []


def test_leaderboard_ranks_by_spend_then_tokens_with_nulls_as_zero():
    sql = _sql(
        select(Execution.agent_id).group_by(Execution.agent_id).order_by(*_by_usage())
    )
    order = sql.split("ORDER BY", 1)[1]
    assert order.index("coalesce(sum(executions.cost), 0) DESC") < order.index(
        "input_tokens"
    )
    # a sum over only NULL costs used to sort first under DESC
    assert "sum(executions.cost) DESC" not in order.replace(
        "coalesce(sum(executions.cost), 0) DESC", ""
    )
    assert "count(executions.id) DESC" in order
