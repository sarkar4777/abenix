"""Meetings, OracleNet and governance replay honour the agent spend caps."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.agent_budget import BUDGET_EXCEEDED


class _R:
    def __init__(self, obj=None, row=None):
        self.obj, self.row = obj, row

    def scalar_one_or_none(self):
        return self.obj

    def scalars(self):
        return self

    def first(self):
        return self.row if self.row is not None else self.obj


class Db:
    """Answers the spend queries with a fixed total and anything else with `obj`."""

    def __init__(self, spent=0.0, obj=None, get=None):
        self.spent, self.obj, self.get_obj = spent, obj, get
        self.added, self.commits = [], 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "billed_agent_id" in sql:
            return _R(row=(0, 0))
        if "SUM(cost)" in sql:
            return _R(row=(self.spent, self.spent))
        return _R(obj=self.obj)

    async def get(self, model, key):
        return self.get_obj

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    async def close(self):
        return None


def _agent(**kw):
    base = dict(
        id=uuid.uuid4(),
        name="Meeting Rep",
        daily_cost_limit=1.0,
        daily_budget_usd=None,
        per_execution_cost_limit=0.25,
        model_config_={},
        system_prompt="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        token_monthly_allowance=None,
        cost_monthly_limit=None,
        quota_reset_at=None,
        role=SimpleNamespace(value="admin"),
    )


def _body(resp):
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_budget_gate_answers_429_with_the_code():
    from app.core.budget_gate import budget_error, per_run_cost_limit

    agent = _agent()
    resp = await budget_error(Db(spent=1.5), agent, uuid.uuid4())
    assert resp.status_code == 429
    err = _body(resp)["error"]
    assert err["error_code"] == BUDGET_EXCEEDED
    assert err["message"].startswith("Meeting Rep has reached its daily spending limit")
    assert await budget_error(Db(spent=0.5), agent, uuid.uuid4()) is None
    assert per_run_cost_limit(agent) == 0.25
    assert per_run_cost_limit(agent, 0.1) == 0.1
    assert per_run_cost_limit(_agent(per_execution_cost_limit=None)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["start", "redispatch"])
async def test_meeting_start_and_redispatch_refuse_over_budget(route):
    from app.routers import meetings

    m = SimpleNamespace(
        id=uuid.uuid4(),
        status="authorized",
        scope_allow=["pricing"],
        agent_id=None,
        started_at=None,
        ended_at=None,
    )
    db = Db(spent=2.0)
    with patch.object(meetings, "_load", AsyncMock(return_value=m)), patch.object(
        meetings, "_meeting_agent", AsyncMock(return_value=_agent())
    ), patch.object(meetings.asyncio, "create_task") as spawn:
        fn = meetings.start_meeting if route == "start" else meetings.redispatch_bot
        resp = await fn(str(m.id), {}, user=_user(), db=db)
    assert resp.status_code == 429
    assert _body(resp)["error"]["error_code"] == BUDGET_EXCEEDED
    assert m.status == "authorized"
    assert db.commits == 0
    spawn.assert_not_called()


def test_meeting_done_event_records_spend_and_the_budget_stop():
    from app.routers import meetings
    from models.execution import ExecutionStatus

    ex = SimpleNamespace(status=ExecutionStatus.RUNNING)
    meetings._record_meeting_done(
        ex,
        {
            "cost": 0.31,
            "input_tokens": 100,
            "output_tokens": 20,
            "duration_ms": 900,
            "error": "This run stopped at its per-run budget of $0.25",
            "failure_code": BUDGET_EXCEEDED,
        },
    )
    assert ex.status == ExecutionStatus.FAILED
    assert ex.failure_code == BUDGET_EXCEEDED
    assert ex.cost == 0.31 and ex.input_tokens == 100
    ok = SimpleNamespace(status=ExecutionStatus.RUNNING)
    meetings._record_meeting_done(ok, {"cost": 0.1, "input_tokens": 1})
    assert ok.status == ExecutionStatus.RUNNING and ok.cost == 0.1


@pytest.mark.asyncio
async def test_meeting_bot_does_not_start_over_budget(monkeypatch):
    from app.routers import meetings
    from engine.tools import _meeting_session

    decisions = []

    async def record(mid, kind, text, detail=None):
        decisions.append((kind, text))

    monkeypatch.setattr(_meeting_session, "append_decision", record)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/x")
    agent = _agent()
    db = Db(spent=3.0, obj=agent)

    class Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False

    engine = MagicMock(dispose=AsyncMock())
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", lambda *a, **k: engine
    )
    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.async_sessionmaker", lambda *a, **k: Session
    )
    m = SimpleNamespace(id=uuid.uuid4(), agent_id=agent.id)
    await meetings._run_meeting_agent(m, _user(), {})
    assert decisions and decisions[-1][0] == "leave"
    assert "daily spending limit" in decisions[-1][1]
    assert db.added == []
    engine.dispose.assert_awaited()


@pytest.mark.asyncio
async def test_oraclenet_refuses_over_budget_and_passes_the_run_cap():
    from app.routers import oraclenet
    from app.schemas.oraclenet import AnalyzeRequest

    agent = _agent(
        name="OracleNet",
        model_config_={"pipeline_config": {"nodes": [{"id": "a"}]}, "tools": []},
    )
    body = AnalyzeRequest(decision_prompt="Should we enter the Nordic market in 2027?")
    resp = await oraclenet.analyze_decision(body, user=_user(), db=Db(2.0, agent))
    assert resp.status_code == 429
    assert _body(resp)["error"]["error_code"] == BUDGET_EXCEEDED

    db = Db(0.0, agent)
    with patch(
        "app.routers.agents._stream_pipeline_execution", MagicMock()
    ) as stream, patch.object(oraclenet, "async_session", MagicMock()):
        resp = await oraclenet.analyze_decision(body, user=_user(), db=db)
        async for _ in resp.body_iterator:
            break
    assert len(db.added) == 1
    assert stream.call_args.kwargs["cost_limit"] == 0.25


@pytest.mark.asyncio
async def test_governance_replay_refuses_over_budget():
    from app.routers import governance

    agent = _agent(name="Pricer")
    ex = SimpleNamespace(
        id=uuid.uuid4(),
        agent_id=agent.id,
        provenance={},
        input_message="hi",
    )
    db = Db(spent=5.0, obj=ex, get=agent)
    resp = await governance.replay_run(
        ex.id,
        governance.ReplayBody(mode="current"),
        request=MagicMock(),
        user=_user(),
        db=db,
    )
    assert resp.status_code == 429
    assert (
        "Pricer has reached its daily spending limit" in _body(resp)["error"]["message"]
    )
    assert db.added == []


@pytest.mark.asyncio
async def test_invoke_agent_surfaces_a_429_plainly():
    from engine.tools import invoke_agent

    resp = MagicMock()
    resp.json.return_value = {
        "error": {
            "message": "Bot has reached its daily spending limit",
            "error_code": BUDGET_EXCEEDED,
        }
    }
    assert invoke_agent._error_body(resp)["error_code"] == BUDGET_EXCEEDED
    bad = MagicMock()
    bad.json.side_effect = ValueError("not json")
    assert invoke_agent._error_body(bad) == {}
