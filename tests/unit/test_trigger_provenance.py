"""Every run records what started it, and the lists can filter on it."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.core import run_origin
from app.routers import executions as E
from app.routers import triggers as T
from models.execution import Execution, ExecutionStatus
from models.user import UserRole


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class _Res:
    def scalar(self):
        return 0

    def all(self):
        return []

    def scalars(self):
        return self


class _DB:
    def __init__(self):
        self.sql: list[str] = []

    async def execute(self, stmt, params=None):
        self.sql.append(_sql(stmt))
        return _Res()

    async def scalar(self, stmt):
        await self.execute(stmt)
        return 0


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.ADMIN)


LIST = dict(
    agent_id=None,
    search="",
    sort="newest",
    limit=20,
    offset=0,
    status=None,
    since=None,
)


# run_origin helpers


def test_stamp_sets_all_three_and_never_overwrites():
    ex = SimpleNamespace(trigger_kind=None, trigger_id=None, trigger_name=None)
    tid = uuid.uuid4()
    run_origin.stamp(ex, "schedule", trigger_id=str(tid), name="Nightly report")
    assert ex.trigger_kind == "schedule"
    assert ex.trigger_id == tid
    assert ex.trigger_name == "Nightly report"
    run_origin.stamp(ex, "chat", trigger_id=uuid.uuid4(), name="other")
    assert (ex.trigger_kind, ex.trigger_id, ex.trigger_name) == (
        "schedule",
        tid,
        "Nightly report",
    )


def test_stamp_ignores_a_bad_trigger_id_and_trims_the_name():
    ex = SimpleNamespace(trigger_kind=None, trigger_id=None, trigger_name=None)
    run_origin.stamp(ex, "webhook", trigger_id="not-a-uuid", name="x" * 400)
    assert ex.trigger_id is None
    assert len(ex.trigger_name) == run_origin.NAME_MAX


def test_execute_kinds():
    fe = run_origin.for_execute
    assert fe(api_key=True, source="chat", conversation_id="c") == "api"
    assert fe(api_key=False, source="chat", conversation_id=None) == "chat"
    assert fe(api_key=False, source=None, conversation_id="c") == "chat"
    assert fe(api_key=False, source="playground", conversation_id=None) == "playground"
    # a browser cannot claim to be a schedule
    assert fe(api_key=False, source="schedule", conversation_id=None) == "manual"
    assert run_origin.caller_kind(SimpleNamespace(_api_key_scopes=["x"])) == "api"
    assert run_origin.caller_kind(SimpleNamespace(), "builder") == "builder"


def test_started_by_reads_as_words():
    assert run_origin.started_by("schedule", "Nightly") == "Schedule: Nightly"
    assert run_origin.started_by("chat", None) == "Chat"
    assert run_origin.started_by(None, "x") is None
    assert run_origin.started_by("something_new", None) == "Something new"


def test_event_origin_tells_source_watch_from_other_events():
    sub = {"name": "Ops hook"}
    assert run_origin.event_origin(
        sub, {"type": "source.changed", "data": {"name": "EU AI Act"}}
    ) == ("source_watch", "EU AI Act")
    assert run_origin.event_origin(sub, {"type": "execution.failed", "data": {}}) == (
        "event",
        "Ops hook",
    )
    assert run_origin.event_origin({}, {"type": "eval.completed"}) == (
        "event",
        "eval.completed",
    )


def test_request_origin_comes_from_state():
    req = SimpleNamespace(state=SimpleNamespace(run_origin={"kind": "eval"}))
    assert run_origin.from_request(req) == {"kind": "eval"}
    assert run_origin.from_request(SimpleNamespace()) is None
    assert run_origin.from_request(SimpleNamespace(state=SimpleNamespace())) is None


def test_model_has_the_columns_with_set_null():
    cols = Execution.__table__.c
    assert cols.trigger_kind.nullable and cols.trigger_name.nullable
    fk = next(iter(cols.trigger_id.foreign_keys))
    assert fk.column.table.name == "agent_triggers"
    assert fk.ondelete == "SET NULL"


# executions API


def test_serializer_exposes_the_origin():
    tid = uuid.uuid4()
    e = Execution(
        id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        input_message="hi",
        status=ExecutionStatus.COMPLETED,
        trigger_id=tid,
        trigger_kind="schedule",
        trigger_name="Nightly",
        created_at=datetime.now(timezone.utc),
    )
    d = E._serialize_execution(e)
    assert d["trigger_id"] == str(tid)
    assert d["trigger_kind"] == "schedule"
    assert d["trigger_name"] == "Nightly"
    assert d["started_by"] == "Schedule: Nightly"


@pytest.mark.asyncio
async def test_list_filters_on_kind_and_unknown():
    db = _DB()
    res = await E.list_executions(
        user=_admin(), db=db, trigger_kind="schedule,unknown", trigger_id=None, **LIST
    )
    assert res.status_code == 200
    rows = [q for q in db.sql if "ORDER BY" in q][-1]
    assert "executions.trigger_kind IN ('schedule')" in rows
    assert "executions.trigger_kind IS NULL" in rows
    assert "flat_rate_billing" in json.loads(res.body)["meta"]


@pytest.mark.asyncio
async def test_list_filters_on_trigger_id():
    db = _DB()
    tid = uuid.uuid4()
    await E.list_executions(
        user=_admin(), db=db, trigger_kind=None, trigger_id=tid, **LIST
    )
    assert any(f"executions.trigger_id = '{tid}'" in q for q in db.sql)


@pytest.mark.asyncio
async def test_list_refuses_an_unknown_kind():
    res = await E.list_executions(
        user=_admin(), db=_DB(), trigger_kind="cron", trigger_id=None, **LIST
    )
    assert res.status_code == 400
    assert "Unknown trigger_kind" in json.loads(res.body)["error"]["message"]


# triggers


@pytest.mark.asyncio
async def test_recent_runs_is_one_ranked_query():
    db = _DB()
    out = await T.recent_runs(db, uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()])
    assert out == {}
    assert len(db.sql) == 1
    assert "row_number() OVER (PARTITION BY executions.trigger_id" in db.sql[0]
    assert "<= 5" in db.sql[0]
    assert await T.recent_runs(_DB(), uuid.uuid4(), []) == {}


def test_run_row_is_small_and_lower_case():
    e = SimpleNamespace(
        id=uuid.uuid4(),
        status=ExecutionStatus.FAILED,
        trigger_kind="manual",
        created_at=datetime.now(timezone.utc),
        duration_ms=10,
        failure_code="BUDGET_EXCEEDED",
    )
    row = T._run_row(e)
    assert row["status"] == "failed"
    assert row["trigger_kind"] == "manual"
    assert set(row) == {
        "id",
        "status",
        "trigger_kind",
        "created_at",
        "duration_ms",
        "failure_code",
    }


class _Session:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


@pytest.mark.asyncio
async def test_dispatch_stamps_the_trigger_on_the_new_run():
    agent = SimpleNamespace(
        id=uuid.uuid4(),
        name="Reporter",
        model_config_={"model": "m"},
        runtime_pool="default",
        status="active",
        daily_cost_limit=None,
        daily_budget_usd=None,
    )
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    tid = uuid.uuid4()
    with (
        patch("engine.agent_budget.check_agent_budget", AsyncMock(return_value=None)),
        patch("engine.risk.draft_needs_release", return_value=False),
        patch.object(T.asyncio, "create_task") as task,
        patch("app.core.config.settings.scaling_exec_remote", False),
    ):
        task.return_value = AsyncMock()
        ex, ok = await T.dispatch_execution(
            _Session(),
            agent=agent,
            user=user,
            message="go",
            context={},
            trigger_id=str(tid),
            trigger_kind="schedule",
            trigger_name="Nightly",
        )
        task.call_args.args[0].close()
    T._BACKGROUND_TASKS.discard(task.return_value)
    assert ok is True
    assert ex.trigger_id == tid
    assert ex.trigger_kind == "schedule"
    assert ex.trigger_name == "Nightly"


@pytest.mark.asyncio
async def test_run_now_records_manual_with_the_trigger_name():
    owner = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.USER, is_active=True
    )
    trig = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=owner.tenant_id,
        agent_id=uuid.uuid4(),
        created_by=owner.id,
        name="nightly",
        default_message="m",
        default_context={},
        run_count=0,
        last_run_at=None,
        last_status=None,
        is_active=True,
    )
    results = [trig, SimpleNamespace(id=trig.agent_id, name="Reporter"), owner]

    class S:
        async def execute(self, stmt):
            v = results.pop(0)
            return SimpleNamespace(scalar_one_or_none=lambda: v)

        async def commit(self):
            pass

    dispatch = AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), True))
    with (
        patch.object(T, "check_trigger_eligibility", AsyncMock(return_value=None)),
        patch.object(T, "trigger_stopped", AsyncMock(return_value=None)),
        patch.object(T, "dispatch_execution", dispatch),
    ):
        resp = await T.run_trigger_now(trig.id, owner, S())
    assert resp.status_code == 202
    kw = dispatch.await_args.kwargs
    assert kw["trigger_kind"] == "manual"
    assert kw["trigger_name"] == "nightly"


@pytest.mark.asyncio
async def test_event_run_records_source_watch():
    from app.services import events

    agent = SimpleNamespace(id=uuid.uuid4())
    owner = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    results = [agent, owner]

    class S:
        async def execute(self, stmt):
            v = results.pop(0)
            return SimpleNamespace(scalar_one_or_none=lambda: v)

    @asynccontextmanager
    async def session():
        yield S()

    dispatch = AsyncMock(return_value=(SimpleNamespace(id=uuid.uuid4()), True))
    sub = {
        "name": "Reg watch",
        "created_by": owner.id,
        "target": {"agent_id": str(agent.id)},
    }
    env = {"type": "source.changed", "data": {"name": "EU AI Act"}}
    with (
        patch("app.core.deps.async_session", session),
        patch("app.routers.triggers.dispatch_execution", dispatch),
    ):
        ok, _, _, _ = await events._deliver_run(sub, env)
    assert ok
    kw = dispatch.await_args.kwargs
    assert kw["trigger_kind"] == "source_watch"
    assert kw["trigger_name"] == "EU AI Act"


# billing mode for cost labels


@pytest.mark.asyncio
async def test_billing_mode_says_subscription_when_active():
    from app.routers import analytics as A

    for active, label in ((True, "Claude subscription"), (False, None)):
        with patch.object(
            A, "_subscription_state", AsyncMock(return_value={"active": active})
        ):
            res = await A.get_billing_mode(user=_admin(), db=_DB())
        data = json.loads(res.body)["data"]
        assert data["flat_rate_billing"] is active
        assert data["label"] == label
