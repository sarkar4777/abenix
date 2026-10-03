"""Agent daily caps stop new runs with BUDGET_EXCEEDED, the per-run cap reaches the pipeline executor."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.failure_codes import classify_exception
from engine import agent_budget
from engine.agent_budget import BUDGET_EXCEEDED, check_agent_budget, evaluate


class _Result:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class SpendSession:
    def __init__(self, spent_all=0.0, spent_tenant=0.0, caps_row=None, step=(0, 0)):
        self.spent = (spent_all, spent_tenant)
        self.step = step
        self.caps_row = caps_row
        self.calls: list[tuple[str, dict]] = []
        self.commits = 0
        self.added = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "FROM agents" in sql:
            return _Result(self.caps_row)
        if "node_results" in sql:
            return _Result(self.step)
        return _Result(self.spent)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    def add(self, obj):
        self.added.append(obj)


class NoQuerySession:
    async def execute(self, *a, **k):
        raise AssertionError("an agent without caps must not query spend")


def test_no_caps_means_no_breach():
    assert (
        evaluate(
            "A",
            daily_cost_limit=None,
            daily_budget_usd=None,
            spent_all=1e6,
            spent_tenant=1e6,
        )
        is None
    )


def test_zero_cap_is_no_cap():
    assert (
        evaluate(
            "A", daily_cost_limit=0, daily_budget_usd=0, spent_all=50, spent_tenant=50
        )
        is None
    )


def test_agent_wide_daily_limit():
    breach = evaluate(
        "Renewal bot",
        daily_cost_limit=5,
        daily_budget_usd=None,
        spent_all=5.2,
        spent_tenant=0.1,
    )
    assert breach.limit_name == "daily_cost_limit"
    assert "Renewal bot has reached its daily spending limit of $5.00" in breach.message
    assert "$5.20 spent today" in breach.message
    assert breach.details() == {
        "limit": "daily_cost_limit",
        "cap_usd": 5.0,
        "spent_today_usd": 5.2,
    }


def test_tenant_daily_budget():
    breach = evaluate(
        "Bot", daily_cost_limit=100, daily_budget_usd=2, spent_all=40, spent_tenant=2
    )
    assert breach.limit_name == "daily_budget_usd"
    assert "for your organization" in breach.message
    assert "Admin, Scaling" in breach.message


def test_under_both_caps():
    assert (
        evaluate(
            "Bot",
            daily_cost_limit=10,
            daily_budget_usd=5,
            spent_all=9.99,
            spent_tenant=4.99,
        )
        is None
    )


def test_messages_classify_as_budget_exceeded():
    for limit in ("daily_cost_limit", "daily_budget_usd"):
        breach = evaluate(
            "Bot",
            daily_cost_limit=1 if limit == "daily_cost_limit" else None,
            daily_budget_usd=1 if limit == "daily_budget_usd" else None,
            spent_all=3,
            spent_tenant=3,
        )
        assert classify_exception(breach.message) == BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_check_skips_the_query_without_caps():
    assert (
        await check_agent_budget(
            NoQuerySession(),
            agent_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            agent_name="A",
            daily_cost_limit=None,
            daily_budget_usd=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_spend_is_summed_from_utc_midnight_for_the_agent_and_tenant():
    agent_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    session = SpendSession(spent_all=3.0, spent_tenant=1.0)
    now = datetime(2026, 10, 3, 22, 15, tzinfo=timezone.utc)
    breach = await check_agent_budget(
        session,
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_name="A",
        daily_cost_limit=3,
        daily_budget_usd=None,
        now=now,
    )
    assert breach is not None and breach.spent == 3.0
    sql, params = session.calls[0]
    assert "FROM executions" in sql and "agent_id" in sql
    assert params == {
        "aid": str(agent_id),
        "tid": str(tenant_id),
        "since": datetime(2026, 10, 3, tzinfo=timezone.utc),
    }


@pytest.mark.asyncio
async def test_check_by_id_reads_the_caps():
    session = SpendSession(spent_all=0.5, spent_tenant=0.5, caps_row=("Bot", None, 0.5))
    breach = await agent_budget.check_agent_budget_by_id(
        session, uuid.uuid4(), uuid.uuid4()
    )
    assert breach.limit_name == "daily_budget_usd"
    missing = SpendSession(caps_row=None)
    assert (
        await agent_budget.check_agent_budget_by_id(missing, uuid.uuid4(), uuid.uuid4())
        is None
    )


@pytest.mark.asyncio
async def test_pipeline_routes_answer_429_with_the_code():
    from app.routers import pipelines

    agent = SimpleNamespace(
        id=uuid.uuid4(), name="Flow", daily_cost_limit=1, daily_budget_usd=None
    )
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    resp = await pipelines._budget_error(SpendSession(spent_all=1.5), agent, user)
    assert resp.status_code == 429
    body = json.loads(resp.body)
    assert body["error"]["error_code"] == BUDGET_EXCEEDED
    assert body["error"]["details"]["limit"] == "daily_cost_limit"
    assert "Flow has reached" in body["error"]["message"]
    assert (
        await pipelines._budget_error(SpendSession(spent_all=0.5), agent, user) is None
    )


def test_pipeline_per_run_cap_takes_the_tighter_limit():
    from app.routers import pipelines

    agent = SimpleNamespace(per_execution_cost_limit=0.5)
    assert pipelines._run_cost_limit(agent, 2.0) == 0.5
    assert pipelines._run_cost_limit(agent, 0.1) == 0.1
    assert (
        pipelines._run_cost_limit(SimpleNamespace(per_execution_cost_limit=None), None)
        is None
    )
    assert (
        pipelines._run_cost_limit(SimpleNamespace(per_execution_cost_limit=0), None)
        is None
    )


def test_agent_execute_passes_the_per_run_cap():
    from app.routers import agents

    assert (
        agents._per_run_cost_limit(SimpleNamespace(per_execution_cost_limit=0.25))
        == 0.25
    )
    assert (
        agents._per_run_cost_limit(SimpleNamespace(per_execution_cost_limit=None))
        is None
    )


@pytest.mark.asyncio
async def test_triggered_run_over_budget_is_recorded_as_failed():
    from app.core.config import settings
    from app.routers import triggers
    from models.execution import ExecutionStatus

    agent = SimpleNamespace(
        id=uuid.uuid4(),
        name="Nightly",
        model_config_={},
        runtime_pool="default",
        daily_cost_limit=2,
        daily_budget_usd=None,
    )
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    execution = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=user.tenant_id, status=ExecutionStatus.RUNNING
    )
    backend = SimpleNamespace(submit=AsyncMock())
    session = SpendSession(spent_all=2.5)
    with patch.object(settings, "scaling_exec_remote", True), patch(
        "engine.queue_backend.get_queue_backend", return_value=backend
    ), patch.object(triggers, "_notify_trigger_failure", AsyncMock()) as notify:
        result, dispatched = await triggers.dispatch_execution(
            session,
            agent=agent,
            user=user,
            message="go",
            context={},
            trigger_id=str(uuid.uuid4()),
            execution=execution,
        )
    assert dispatched is False
    backend.submit.assert_not_awaited()
    assert result.status == ExecutionStatus.FAILED
    assert result.failure_code == BUDGET_EXCEEDED
    assert "Nightly has reached its daily spending limit" in result.error_message
    notify.assert_awaited_once()

    resp = triggers._not_dispatched_error(result)
    assert resp.status_code == 429
    assert json.loads(resp.body)["error"]["error_code"] == BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_pipeline_agent_step_stops_on_budget(monkeypatch):
    from engine.tools import agent_step

    breach = evaluate(
        "Child", daily_cost_limit=1, daily_budget_usd=None, spent_all=2, spent_tenant=2
    )
    seen = {}

    async def fake_breach(agent_id, tenant_id, db_url):
        seen.update(agent_id=agent_id, tenant_id=tenant_id)
        return breach

    monkeypatch.setattr(agent_step, "_budget_breach", fake_breach)
    result = await agent_step.AgentStepTool().execute(
        {
            "input_message": "hi",
            "system_prompt": "be brief",
            "__agent_id__": "a1",
            "__tenant_id__": "t1",
        }
    )
    assert result.is_error
    assert result.content.startswith("Budget exceeded: Child has reached")
    assert result.metadata["failure_code"] == BUDGET_EXCEEDED
    assert seen == {"agent_id": "a1", "tenant_id": "t1"}
    assert classify_exception(result.content) == BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_inline_agent_step_has_no_budget_to_check():
    from engine.tools import agent_step

    assert await agent_step._budget_breach("", "t1", "postgresql://x") is None
    assert await agent_step._budget_breach("a1", "t1", "") is None


@pytest.mark.asyncio
async def test_pipeline_step_spend_counts_toward_the_child_agent():
    agent_id, tenant_id = uuid.uuid4(), uuid.uuid4()
    session = SpendSession(spent_all=0.75, spent_tenant=0.5, step=(0.5, 0.25))
    assert await agent_budget.spent_today(session, agent_id, tenant_id) == (1.25, 0.75)
    step_sql, params = session.calls[1]
    assert "billed_agent_id" in step_sql and "metadata" in step_sql
    assert "IS DISTINCT FROM" in step_sql
    assert params["aid"] == str(agent_id)
    breach = await check_agent_budget(
        session,
        agent_id=agent_id,
        tenant_id=tenant_id,
        agent_name="Child",
        daily_cost_limit=1,
        daily_budget_usd=None,
    )
    assert breach is not None and breach.spent == pytest.approx(1.25)


def test_step_spend_query_never_reads_the_tenant_quota_columns():
    sql = str(agent_budget._STEP_SPENT_SQL)
    assert "e.cost" not in sql and "SUM(cost)" not in sql


def test_run_budget_message_is_plain():
    msg = agent_budget.run_budget_message(0.5, 0.61234)
    assert msg.startswith("This run stopped at its per-run budget of $0.50")
    assert "$0.6123 spent" in msg
    assert classify_exception(msg) == BUDGET_EXCEEDED


def _step_args(**kw):
    return {
        "input_message": "hi",
        "system_prompt": "be brief",
        "__agent_id__": "child-1",
        "__tenant_id__": "t1",
        **kw,
    }


def _patch_step(monkeypatch, result, cap=0.2):
    from engine.tools import agent_step

    async def no_breach(*a):
        return None

    async def settings(agent_id, db_url):
        return {}, cap, "active"

    monkeypatch.setattr(agent_step, "_budget_breach", no_breach)
    monkeypatch.setattr(agent_step, "_agent_settings", settings)
    built = {}

    class FakeExecutor:
        def __init__(self, **kw):
            built.update(kw)

        async def invoke(self, message):
            return result

    monkeypatch.setattr("engine.agent_executor.AgentExecutor", FakeExecutor)
    monkeypatch.setattr(
        "engine.agent_executor.build_tool_registry", lambda *a, **k: object()
    )
    return agent_step, built


def _child_result(**kw):
    base = dict(
        output="partial\n\nThis run stopped because it at its per-run budget of $0.20",
        model="m",
        input_tokens=3,
        output_tokens=2,
        cost=0.21,
        duration_ms=5,
        tool_calls=[],
        node_traces=[],
        budget_exceeded=True,
        failure_code=BUDGET_EXCEEDED,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_agent_step_gives_the_child_its_per_run_cap(monkeypatch):
    agent_step, built = _patch_step(monkeypatch, _child_result())
    result = await agent_step.AgentStepTool().execute(_step_args())
    assert built["cost_limit"] == 0.2
    assert result.is_error
    assert result.content.startswith("Budget exceeded: partial")
    assert result.metadata["failure_code"] == BUDGET_EXCEEDED
    assert result.metadata["cost"] == 0.21
    assert result.metadata["billed_agent_id"] == "child-1"
    assert classify_exception(result.content) == BUDGET_EXCEEDED


@pytest.mark.asyncio
async def test_agent_step_bills_a_saved_child_on_success(monkeypatch):
    done = _child_result(output="ok", budget_exceeded=False, failure_code="")
    agent_step, _ = _patch_step(monkeypatch, done)
    result = await agent_step.AgentStepTool().execute(_step_args())
    assert not result.is_error
    assert result.metadata["billed_agent_id"] == "child-1"
    assert result.metadata["cost"] == 0.21
    inline = await agent_step.AgentStepTool().execute(_step_args(__agent_id__=""))
    assert "billed_agent_id" not in inline.metadata


def test_consumer_run_cap_is_the_tighter_of_agent_and_request():
    import consumer

    assert consumer._run_cost_cap({"per_execution_cost_limit": 0.5}, {}) == 0.5
    assert (
        consumer._run_cost_cap({"per_execution_cost_limit": 0.5}, {"cost_limit": 0.1})
        == 0.1
    )
    assert consumer._run_cost_cap({"per_execution_cost_limit": None}, {}) is None
    assert consumer._run_cost_cap({}, {"cost_limit": 0}) is None


@pytest.mark.asyncio
async def test_execution_router_passes_the_cap_both_ways(monkeypatch):
    from engine import execution_router

    built = []

    class FakeExecutor:
        def __init__(self, **kw):
            built.append(kw)

        async def invoke(self, message):
            return _child_result()

        async def stream(self, message):
            yield SimpleNamespace(event="done", data={"failure_code": BUDGET_EXCEEDED})

    monkeypatch.setattr("engine.agent_executor.AgentExecutor", FakeExecutor)
    monkeypatch.setattr(
        "engine.agent_executor.build_tool_registry", lambda *a, **k: object()
    )
    monkeypatch.setattr("engine.llm_router.LLMRouter", lambda: object())
    cfg = execution_router.ExecutionConfig(
        message="hi", system_prompt="", cost_limit=0.2
    )
    res = await execution_router._execute_embedded(cfg)
    assert res.failure_code == BUDGET_EXCEEDED and "per-run budget" in res.error
    events = [e async for e in execution_router._stream_embedded(cfg)]
    assert events[-1]["data"]["failure_code"] == BUDGET_EXCEEDED
    assert [b["cost_limit"] for b in built] == [0.2, 0.2]
