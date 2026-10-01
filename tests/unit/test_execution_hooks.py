"""Terminal hook: records completed and failed rows, honours toggles, dedupes, backlog."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import execution_hooks as hooks
from engine.drift_detection import DriftAlert
from models.drift_alert import DriftAlert as DriftAlertRow
from models.execution import Execution, ExecutionStatus


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.closed = False

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = str(value)
        return True

    async def delete(self, key):
        self.kv.pop(key, None)

    async def aclose(self):
        self.closed = True


class FakeSession:
    """Answers the Agent lookup and the Execution selects the hook issues."""

    def __init__(self, agent, executions=()) -> None:
        self.agent = agent
        self.executions = list(executions)
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is not None and entity.__name__ == "Agent":
            return SimpleNamespace(scalar_one_or_none=lambda: self.agent)
        rows = self.executions
        return SimpleNamespace(
            scalar_one_or_none=lambda: rows[0] if rows else None,
            scalars=lambda: SimpleNamespace(all=lambda: rows),
        )

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _factory(session):
    @asynccontextmanager
    async def _open():
        yield session

    return _open


def _agent(cfg=None, tenant_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), model_config_=cfg or {}
    )


def _execution(agent, status=ExecutionStatus.COMPLETED, **overrides):
    now = datetime.now(timezone.utc)
    base = dict(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        user_id=uuid.uuid4(),
        input_message="hi",
        status=status,
        output_message="x" * 120,
        input_tokens=100,
        output_tokens=50,
        cost=0.01,
        duration_ms=1200,
        confidence_score=0.8,
        tool_calls=[{"name": "a", "is_error": True}, {"name": "b"}],
        started_at=now - timedelta(seconds=2),
        completed_at=now,
    )
    base.update(overrides)
    return Execution(**base)


def _detector(alerts=None, raises=None):
    if raises is not None:
        return SimpleNamespace(record_execution=AsyncMock(side_effect=raises))
    return SimpleNamespace(record_execution=AsyncMock(return_value=alerts or []))


@pytest.mark.asyncio
async def test_records_completed_execution_from_row():
    agent = _agent()
    ex = _execution(agent)
    det = _detector()
    alerts = await hooks.record_terminal(
        FakeSession(agent), ex, detector=det, redis=FakeRedis()
    )
    assert alerts == []
    det.record_execution.assert_awaited_once()
    kw = det.record_execution.await_args.kwargs
    assert kw["agent_id"] == str(agent.id)
    assert kw["duration_ms"] == 1200
    assert kw["input_tokens"] == 100
    assert kw["output_tokens"] == 50
    assert kw["cost"] == pytest.approx(0.01)
    assert kw["confidence"] == pytest.approx(0.8)
    assert kw["output_length"] == 120
    assert kw["tool_failures"] == 1
    assert kw["total_tool_calls"] == 2


@pytest.mark.asyncio
async def test_records_failed_execution():
    agent = _agent()
    ex = _execution(agent, status=ExecutionStatus.FAILED, output_message=None)
    det = _detector()
    await hooks.record_terminal(FakeSession(agent), ex, detector=det, redis=FakeRedis())
    det.record_execution.assert_awaited_once()
    assert det.record_execution.await_args.kwargs["output_length"] == 0


@pytest.mark.asyncio
async def test_running_execution_is_not_recorded():
    agent = _agent()
    ex = _execution(agent, status=ExecutionStatus.RUNNING)
    det = _detector()
    await hooks.record_terminal(FakeSession(agent), ex, detector=det, redis=FakeRedis())
    det.record_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_counters_come_from_node_results():
    agent = _agent()
    ex = _execution(
        agent,
        input_tokens=None,
        output_tokens=None,
        cost=None,
        confidence_score=None,
        tool_calls=None,
        node_results={
            "n1": {
                "status": "completed",
                "output": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost": 0.002,
                    "tool_calls_count": 2,
                },
            },
            "n2": {"status": "failed", "output": {"input_tokens": 1}},
            "n3": {"status": "completed", "output": "plain text"},
        },
    )
    det = _detector()
    await hooks.record_terminal(FakeSession(agent), ex, detector=det, redis=FakeRedis())
    kw = det.record_execution.await_args.kwargs
    assert kw["input_tokens"] == 11
    assert kw["output_tokens"] == 5
    assert kw["cost"] == pytest.approx(0.002)
    assert kw["confidence"] == 1.0
    assert kw["tool_failures"] == 1
    assert kw["total_tool_calls"] == 3


def test_duration_falls_back_to_timestamps():
    agent = _agent()
    ex = _execution(agent, duration_ms=None)
    assert hooks.execution_metrics(ex)["duration_ms"] == pytest.approx(2000, abs=5)


@pytest.mark.asyncio
async def test_agent_toggle_off_skips():
    agent = _agent(cfg={"drift_detection": False})
    det = _detector()
    await hooks.record_terminal(
        FakeSession(agent), _execution(agent), detector=det, redis=FakeRedis()
    )
    det.record_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_toggle_off_skips():
    agent = _agent()
    r = FakeRedis()
    r.kv[f"drift:config:enabled:{agent.tenant_id}"] = "0"
    det = _detector()
    await hooks.record_terminal(
        FakeSession(agent), _execution(agent), detector=det, redis=r
    )
    det.record_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_env_toggle_off_skips(monkeypatch):
    monkeypatch.setenv("DRIFT_DETECTION_ENABLED", "false")
    agent = _agent()
    det = _detector()
    await hooks.record_terminal(
        FakeSession(agent), _execution(agent), detector=det, redis=FakeRedis()
    )
    det.record_execution.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_toggle_beats_env(monkeypatch):
    monkeypatch.setenv("DRIFT_DETECTION_ENABLED", "false")
    agent = _agent()
    r = FakeRedis()
    r.kv[f"drift:config:enabled:{agent.tenant_id}"] = "1"
    det = _detector()
    await hooks.record_terminal(
        FakeSession(agent), _execution(agent), detector=det, redis=r
    )
    det.record_execution.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_execution_is_recorded_once():
    agent = _agent()
    ex = _execution(agent)
    r = FakeRedis()
    det = _detector()
    await hooks.record_terminal(FakeSession(agent), ex, detector=det, redis=r)
    await hooks.record_terminal(FakeSession(agent), ex, detector=det, redis=r)
    assert det.record_execution.await_count == 1
    assert hooks.recorded_key(ex.id) in r.kv


@pytest.mark.asyncio
async def test_detector_failure_drops_the_claim():
    agent = _agent()
    ex = _execution(agent)
    r = FakeRedis()
    alerts = await hooks.record_terminal(
        FakeSession(agent),
        ex,
        detector=_detector(raises=RuntimeError("redis down")),
        redis=r,
    )
    assert alerts == []
    assert hooks.recorded_key(ex.id) not in r.kv


@pytest.mark.asyncio
async def test_alerts_are_persisted_as_rows():
    agent = _agent()
    ex = _execution(agent)
    alert = DriftAlert(
        agent_id=str(agent.id),
        metric_name="cost",
        baseline_value=0.01,
        current_value=0.05,
        deviation_pct=400.0,
        severity="critical",
        message="m",
    )
    session = FakeSession(agent)
    out = await hooks.record_terminal(
        session, ex, detector=_detector(alerts=[alert]), redis=FakeRedis()
    )
    assert out == [alert]
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, DriftAlertRow)
    assert row.metric == "cost"
    assert row.severity == "critical"
    assert row.execution_id == ex.id
    assert row.agent_id == agent.id
    assert session.commits == 1


@pytest.mark.asyncio
async def test_accepts_session_factory_and_id():
    agent = _agent()
    ex = _execution(agent)
    det = _detector()
    session = FakeSession(agent, executions=[ex])
    await hooks.record_terminal_by_id(
        _factory(session), str(ex.id), detector=det, redis=FakeRedis()
    )
    det.record_execution.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_terminal_with_factory():
    agent = _agent()
    det = _detector()
    await hooks.record_terminal(
        _factory(FakeSession(agent)), _execution(agent), detector=det, redis=FakeRedis()
    )
    det.record_execution.assert_awaited_once()


@pytest.mark.asyncio
async def test_backlog_scan_records_missed_rows_and_moves_watermark():
    agent = _agent()
    now = datetime.now(timezone.utc)
    scored = _execution(agent, completed_at=now - timedelta(minutes=3))
    missed = _execution(agent, completed_at=now - timedelta(minutes=1))
    r = FakeRedis()
    r.kv[hooks.recorded_key(scored.id)] = "1"
    det = _detector()
    n = await hooks.scan_backlog(
        _factory(FakeSession(agent, executions=[scored, missed])),
        interval_seconds=300,
        redis=r,
        detector=det,
        now=now,
    )
    assert n == 1
    det.record_execution.assert_awaited_once()
    assert r.kv[hooks.WATERMARK_KEY] == now.isoformat()
    assert hooks.recorded_key(missed.id) in r.kv


@pytest.mark.asyncio
async def test_backlog_full_batch_keeps_watermark_at_last_row():
    agent = _agent()
    now = datetime.now(timezone.utc)
    rows = [
        _execution(agent, completed_at=now - timedelta(minutes=4)),
        _execution(agent, completed_at=now - timedelta(minutes=2)),
    ]
    r = FakeRedis()
    n = await hooks.scan_backlog(
        _factory(FakeSession(agent, executions=rows)),
        interval_seconds=300,
        limit=2,
        redis=r,
        detector=_detector(),
        now=now,
    )
    assert n == 2
    assert r.kv[hooks.WATERMARK_KEY] == rows[-1].completed_at.isoformat()
