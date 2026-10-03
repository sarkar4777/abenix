"""a2a and batch runs record execution rows and honour the agent's daily caps."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.agent_budget import BUDGET_EXCEEDED
from models.execution import Execution, ExecutionStatus


class _R:
    def __init__(self, obj=None, row=None):
        self.obj, self.row = obj, row

    def scalar_one_or_none(self):
        return self.obj

    def first(self):
        return self.row if self.row is not None else self.obj


class Db:
    def __init__(self, spent=0.0, obj=None):
        self.spent, self.obj = spent, obj
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "billed_agent_id" in sql:
            return _R(row=(0, 0))
        if "SUM(cost)" in sql:
            return _R(row=(self.spent, self.spent))
        return _R(obj=self.obj)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    async def merge(self, obj):
        return obj

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _parts() -> dict:
    gate = MagicMock()
    gate.gate = None
    return {
        "registry": MagicMock(),
        "system_prompt": "x",
        "mcp_clients": [],
        "moderation": gate,
        "kb_ids": [],
    }


def _agent(**kw):
    base = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Summariser",
        daily_cost_limit=1.0,
        daily_budget_usd=None,
        per_execution_cost_limit=0.5,
        model_config_={"model": "m-1", "tools": []},
        system_prompt="be brief",
        is_published=False,
        status="active",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        role=SimpleNamespace(value="member"),
        _api_key_id=uuid.uuid4(),
    )


def _result(**kw):
    base = dict(
        output="done",
        input_tokens=120,
        output_tokens=40,
        cost=0.012,
        anthropic_cost=0.012,
        openai_cost=0.0,
        google_cost=0.0,
        other_cost=0.0,
        duration_ms=850,
        tool_calls=[],
        model="m-1",
        fallback_reason="",
        node_traces=[],
        moderation_blocked=False,
        grounding_violation=False,
        risk_tier="low",
        risk_reasons=[],
        governance_refusal=None,
        budget_exceeded=False,
        failure_code="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _request(body):
    req = MagicMock()
    req.headers = {"x-api-key": "af_test"}
    req.json = AsyncMock(return_value=body)
    return req


def _body(resp):
    return json.loads(resp.body)


def _row(agent=None, user=None):
    from app.services import inline_run

    return inline_run.open_run(
        agent=agent or _agent(),
        user=user or _user(),
        message="hi",
        model="m-1",
        subject=(None, None),
    )


def test_record_result_keeps_spend_and_outcome():
    from app.services import inline_run

    ex = _row()
    assert ex.status == ExecutionStatus.RUNNING and ex.id is not None
    code = inline_run.record_result(ex, _result(), "a2a")
    assert code is None
    assert ex.status == ExecutionStatus.COMPLETED
    assert float(ex.cost) == 0.012
    assert (ex.input_tokens, ex.output_tokens) == (120, 40)
    assert ex.execution_trace["source"] == "a2a"
    assert ex.completed_at is not None and ex.duration_ms == 850


@pytest.mark.parametrize(
    "kw,code",
    [
        ({"budget_exceeded": True, "failure_code": BUDGET_EXCEEDED}, BUDGET_EXCEEDED),
        ({"moderation_blocked": True}, "MODERATION_BLOCKED"),
        ({"grounding_violation": True}, "GROUNDING_REQUIRED_VIOLATION"),
        (
            {"governance_refusal": {"code": "KILL_SWITCH", "message": "paused"}},
            "KILL_SWITCH",
        ),
    ],
)
def test_record_result_marks_stopped_runs_failed_with_their_spend(kw, code):
    from app.services import inline_run

    ex = _row()
    assert inline_run.record_result(ex, _result(cost=0.3, **kw), "batch") == code
    assert ex.status == ExecutionStatus.FAILED
    assert ex.failure_code == code
    assert float(ex.cost) == 0.3
    assert ex.error_message


def test_record_error_classifies_the_exception():
    from app.services import inline_run

    ex = _row()
    code = inline_run.record_error(ex, TimeoutError("timed out"))
    assert ex.status == ExecutionStatus.FAILED
    assert ex.failure_code == code and code
    assert "timed out" in ex.error_message


@pytest.mark.asyncio
async def test_a2a_refuses_over_budget_before_any_row():
    from app.routers import a2a

    agent, user = _agent(), _user()
    agent.tenant_id = user.tenant_id
    db = Db(spent=2.0, obj=agent)
    with patch(
        "app.core.deps._authenticate_via_api_key", AsyncMock(return_value=user)
    ), patch(
        "app.services.agent_share.resolve_agent_access", AsyncMock(return_value=True)
    ), patch(
        "engine.agent_executor.AgentExecutor"
    ) as executor:
        resp = await a2a.invoke_agent(agent.id, _request({"message": "go"}), db=db)
    assert resp.status_code == 429
    err = _body(resp)["error"]
    assert err["error_code"] == BUDGET_EXCEEDED
    assert "spent today, UTC" in err["message"]
    assert db.added == []
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_a2a_hides_private_agents_the_caller_cannot_run():
    from app.routers import a2a

    db = Db(obj=_agent())
    with patch(
        "app.core.deps._authenticate_via_api_key", AsyncMock(return_value=_user())
    ), patch(
        "app.services.agent_share.resolve_agent_access", AsyncMock(return_value=False)
    ):
        resp = await a2a.invoke_agent(uuid.uuid4(), _request({"message": "go"}), db=db)
    assert resp.status_code == 404
    assert db.added == []


@pytest.mark.asyncio
async def test_a2a_records_the_run_with_cost_and_tokens():
    from app.routers import a2a

    agent, user = _agent(is_published=True), _user()
    db = Db(spent=0.1, obj=agent)
    inst = MagicMock()
    inst.invoke = AsyncMock(return_value=_result())
    settle = AsyncMock()
    with patch(
        "app.core.deps._authenticate_via_api_key", AsyncMock(return_value=user)
    ), patch("engine.agent_executor.AgentExecutor", return_value=inst) as cls, patch(
        "app.services.inline_run.prepare", AsyncMock(return_value=_parts())
    ), patch(
        "app.services.inline_run.after", AsyncMock()
    ), patch(
        "engine.llm_router.LLMRouter"
    ), patch(
        "app.services.inline_run.settle", settle
    ):
        resp = await a2a.invoke_agent(
            agent.id, _request({"message": "go", "cost_limit": 0.2}), db=db
        )
    assert resp.status_code == 200
    data = _body(resp)["data"]
    ex = next(o for o in db.added if isinstance(o, Execution))
    assert data["execution_id"] == str(ex.id)
    assert data["status"] == "completed"
    assert ex.status == ExecutionStatus.COMPLETED
    assert ex.tenant_id == user.tenant_id and ex.user_id == user.id
    assert float(ex.cost) == 0.012 and ex.output_tokens == 40
    kwargs = cls.call_args.kwargs
    assert kwargs["execution_id"] == str(ex.id)
    assert kwargs["cost_limit"] == 0.2
    settle.assert_awaited_once()
    assert settle.await_args.args[2] == user._api_key_id


@pytest.mark.asyncio
async def test_a2a_records_a_crashed_run_as_failed():
    from app.routers import a2a

    agent = _agent(is_published=True)
    db = Db(obj=agent)
    inst = MagicMock()
    inst.invoke = AsyncMock(side_effect=RuntimeError("provider down"))
    with patch(
        "app.core.deps._authenticate_via_api_key", AsyncMock(return_value=_user())
    ), patch("engine.agent_executor.AgentExecutor", return_value=inst), patch(
        "app.services.inline_run.prepare", AsyncMock(return_value=_parts())
    ), patch(
        "app.services.inline_run.after", AsyncMock()
    ), patch(
        "engine.llm_router.LLMRouter"
    ), patch(
        "app.services.inline_run.settle", AsyncMock()
    ):
        resp = await a2a.invoke_agent(agent.id, _request({"message": "go"}), db=db)
    assert resp.status_code == 500
    ex = next(o for o in db.added if isinstance(o, Execution))
    assert ex.status == ExecutionStatus.FAILED
    assert ex.failure_code
    assert _body(resp)["error"]["details"]["execution_id"] == str(ex.id)


@pytest.mark.asyncio
async def test_batch_refuses_over_budget_before_queueing():
    from app.routers import batch

    user = _user()
    agent = _agent(tenant_id=user.tenant_id)
    db = Db(spent=5.0, obj=agent)
    from models.agent import AgentStatus

    agent.status = AgentStatus.ACTIVE
    with patch(
        "app.services.agent_share.resolve_agent_access", AsyncMock(return_value=True)
    ), patch.object(batch.asyncio, "create_task") as spawn, patch.object(
        batch, "_save_batch", AsyncMock()
    ):
        resp = await batch.batch_execute(
            {"agent_id": str(agent.id), "inputs": [{"message": "a"}]},
            user=user,
            db=db,
        )
    assert resp.status_code == 429
    assert _body(resp)["error"]["error_code"] == BUDGET_EXCEEDED
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_batch_needs_execute_access():
    from app.routers import batch
    from models.agent import AgentStatus

    agent = _agent(status=AgentStatus.ACTIVE)
    with patch(
        "app.services.agent_share.resolve_agent_access", AsyncMock(return_value=False)
    ):
        resp = await batch.batch_execute(
            {"agent_id": str(agent.id), "inputs": [{"message": "a"}]},
            user=_user(),
            db=Db(obj=agent),
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_batch_item_stops_once_the_daily_cap_is_spent():
    from app.routers import batch

    db = Db(spent=1.0)
    run_as = batch._RunAs(user=_user(), subject=(None, None))
    with patch("app.core.deps.async_session", return_value=db), patch(
        "engine.agent_executor.AgentExecutor"
    ) as executor:
        ok, entry = await batch._run_one(_agent(), run_as, "hello")
    assert not ok
    assert entry["failure_code"] == BUDGET_EXCEEDED
    assert "daily spending limit" in entry["error"]
    assert db.added == []
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_batch_item_is_a_recorded_run():
    from app.routers import batch

    db = Db(spent=0.0)
    user = _user()
    run_as = batch._RunAs(
        user=user, subject=("cust-7", "end_user"), api_key_id="k1", cost_limit=None
    )
    inst = MagicMock()
    inst.invoke = AsyncMock(return_value=_result(cost=0.04))
    settle = AsyncMock()
    with patch("app.core.deps.async_session", return_value=db), patch(
        "engine.agent_executor.AgentExecutor", return_value=inst
    ) as cls, patch(
        "app.services.inline_run.prepare", AsyncMock(return_value=_parts())
    ), patch(
        "app.services.inline_run.after", AsyncMock()
    ), patch(
        "engine.llm_router.LLMRouter"
    ), patch(
        "app.services.inline_run.settle", settle
    ):
        ok, entry = await batch._run_one(_agent(), run_as, "hello")
    assert ok
    ex = db.added[0]
    assert isinstance(ex, Execution)
    assert (ex.subject_id, ex.subject_type) == ("cust-7", "end_user")
    assert ex.status == ExecutionStatus.COMPLETED
    assert entry["execution_id"] == str(ex.id)
    assert entry["cost"] == 0.04
    assert cls.call_args.kwargs["cost_limit"] == 0.5
    assert settle.await_args.args[2] == "k1"


@pytest.mark.asyncio
async def test_settle_writes_usage_and_debits_the_key():
    from app.services import inline_run

    user = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        tokens_used_this_month=10,
        cost_used_this_month=1.0,
    )
    db = Db()
    db.get = AsyncMock(return_value=user)
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    ex = _row(user=user)
    inline_run.record_result(ex, _result(), "a2a")
    with patch("app.services.execution_hooks.record_terminal", AsyncMock()) as hook:
        await inline_run.settle(db, ex, api_key_id=uuid.uuid4())
    kinds = {type(o).__name__ for o in db.added}
    assert kinds == {"UsageRecord"}
    assert user.tokens_used_this_month == 170
    assert user.cost_used_this_month == pytest.approx(1.012)
    assert db.execute.await_count == 1
    assert db.commits == 1
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_a2a_runs_get_the_moderation_gate_and_refuse_pipelines():
    from app.routers import a2a

    agent, user = _agent(is_published=True), _user()
    db = Db(spent=0.1, obj=agent)
    inst = MagicMock()
    inst.invoke = AsyncMock(return_value=_result())
    parts = _parts()
    parts["moderation"].gate = "gate"
    after = AsyncMock()
    with patch(
        "app.core.deps._authenticate_via_api_key", AsyncMock(return_value=user)
    ), patch("engine.agent_executor.AgentExecutor", return_value=inst) as cls, patch(
        "app.services.inline_run.prepare", AsyncMock(return_value=parts)
    ), patch(
        "app.services.inline_run.after", after
    ), patch(
        "engine.llm_router.LLMRouter"
    ), patch(
        "app.services.inline_run.settle", AsyncMock()
    ):
        resp = await a2a.invoke_agent(agent.id, _request({"message": "go"}), db=db)
        assert resp.status_code == 200
        assert cls.call_args.kwargs["moderation_gate"] == "gate"
        after.assert_awaited_once()

        pipeline = _agent(is_published=True, model_config_={"mode": "pipeline"})
        resp = await a2a.invoke_agent(
            pipeline.id, _request({"message": "go"}), db=Db(spent=0.0, obj=pipeline)
        )
        assert resp.status_code == 400
