"""DLQ service + replay: one row per execution, replay copies the dispatch shape."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services import dlq as dlq_service
from models.agent import Agent, AgentStatus, AgentType
from models.dead_letter import DeadLetterExecution
from models.execution import Execution, ExecutionStatus


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeSession:
    """Routes select() by the entity being queried, records adds/commits."""

    def __init__(self, *, dlq_rows=(), agents=(), executions=()):
        self.dlq_rows = list(dlq_rows)
        self.agents = list(agents)
        self.executions = list(executions)
        self.added = []
        self.commits = 0

    async def execute(self, stmt):
        desc = stmt.column_descriptions[0]
        entity = desc.get("entity")
        if entity is DeadLetterExecution:
            return _Result(self.dlq_rows)
        if entity is Agent:
            return _Result(self.agents)
        if entity is Execution:
            return _Result(self.executions)
        return _Result([])

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, DeadLetterExecution):
            self.dlq_rows.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()

    @asynccontextmanager
    async def begin_nested(self):
        yield


def _agent(pool="heavy-reasoning", mode=None):
    a = Agent(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        creator_id=uuid.uuid4(),
        name="a",
        description="",
        system_prompt="",
        status=AgentStatus.ACTIVE,
        agent_type=AgentType.CUSTOM,
        model_config_={"model": "claude-sonnet-4-5-20250929", **({"mode": mode} if mode else {})},
    )
    a.runtime_pool = pool
    return a


def _execution(agent, user_id=None):
    return Execution(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        user_id=user_id or uuid.uuid4(),
        input_message="hello",
        status=ExecutionStatus.FAILED,
        model_used="claude-sonnet-4-5-20250929",
    )


@pytest.mark.asyncio
async def test_dead_letter_writes_once_per_execution():
    agent = _agent()
    ex = _execution(agent)
    db = FakeSession(agents=[agent])

    first = await dlq_service.dead_letter(
        db,
        ex,
        reason="boom",
        failure_code="LLM_PROVIDER_ERROR",
        payload={"context": {"k": "v"}, "is_pipeline": False},
    )
    second = await dlq_service.dead_letter(
        db, ex, reason="boom again", failure_code="LLM_PROVIDER_ERROR"
    )

    assert first is second
    assert len([o for o in db.added if isinstance(o, DeadLetterExecution)]) == 1
    assert first.execution_id == ex.id
    assert first.agent_id == agent.id
    assert first.tenant_id == ex.tenant_id
    assert first.failure_code == "LLM_PROVIDER_ERROR"
    assert first.error_message == "boom"
    assert first.original_input["message"] == "hello"
    assert first.original_input["context"] == {"k": "v"}
    assert first.original_input["runtime_pool"] == "heavy-reasoning"
    assert first.original_input["is_pipeline"] is False
    assert first.original_input["user_id"] == str(ex.user_id)


@pytest.mark.asyncio
async def test_dead_letter_accepts_execution_id_and_derives_pipeline_flag():
    agent = _agent(pool="default", mode="pipeline")
    ex = _execution(agent)
    db = FakeSession(agents=[agent], executions=[ex])

    row = await dlq_service.dead_letter(
        db, str(ex.id), reason="x", failure_code="PIPELINE_NODE_FAILED"
    )

    assert row is not None
    assert row.original_input["is_pipeline"] is True
    assert row.original_input["runtime_pool"] == "default"


@pytest.mark.asyncio
async def test_dead_letter_unknown_execution_returns_none():
    db = FakeSession()
    assert (
        await dlq_service.dead_letter(db, uuid.uuid4(), reason="x", failure_code="Y")
        is None
    )


@pytest.mark.asyncio
async def test_replay_copies_pool_pipeline_flag_and_links_parent():
    from app.routers import admin_dlq

    agent = _agent(pool="gpu", mode="pipeline")
    original_exec_id = uuid.uuid4()
    tenant_id = agent.tenant_id
    d = DeadLetterExecution(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        execution_id=original_exec_id,
        agent_id=agent.id,
        failure_code="STALE_SWEEP",
        original_input={
            "message": "run it",
            "context": {"a": 1},
            "runtime_pool": "gpu",
            "is_pipeline": True,
            "model_used": "pipeline",
        },
        replay_count=0,
        resolved=False,
    )
    db = FakeSession(dlq_rows=[d], agents=[agent])
    admin = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, role="admin")

    captured = {}

    async def fake_dispatch(db_, *, agent, user, message, context, trigger_id=None, parent_execution_id=None, execution=None):
        captured.update(
            agent=agent, user=user, message=message, context=context, execution=execution
        )
        return execution, True

    with patch("app.core.acting_subject.subject_columns_for", return_value=(None, None)), patch(
        "app.routers.triggers.dispatch_execution", new=fake_dispatch
    ):
        resp = await admin_dlq.replay_dlq(d.id, user=admin, db=db)

    assert resp.status_code == 200
    new_exec = captured["execution"]
    assert isinstance(new_exec, Execution)
    assert new_exec.parent_execution_id == original_exec_id
    assert new_exec.agent_id == agent.id
    assert new_exec.input_message == "run it"
    assert new_exec.model_used == "pipeline"
    assert new_exec.retry_count == 1
    assert captured["context"] == {"a": 1}
    assert captured["agent"].runtime_pool == "gpu"
    assert d.resolved is True
    assert d.replay_count == 1
    assert d.replay_execution_id == new_exec.id


@pytest.mark.asyncio
async def test_replay_leaves_unresolved_when_dispatch_fails():
    from app.routers import admin_dlq

    agent = _agent()
    d = DeadLetterExecution(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        execution_id=uuid.uuid4(),
        agent_id=agent.id,
        failure_code="INFRA_CRASH",
        original_input={"message": "m", "context": {}},
        replay_count=0,
        resolved=False,
    )
    db = FakeSession(dlq_rows=[d], agents=[agent])
    admin = SimpleNamespace(id=uuid.uuid4(), tenant_id=agent.tenant_id, role="admin")

    async def failing_dispatch(db_, *, execution=None, **kw):
        execution.status = ExecutionStatus.FAILED
        return execution, False

    with patch("app.core.acting_subject.subject_columns_for", return_value=(None, None)), patch(
        "app.routers.triggers.dispatch_execution", new=failing_dispatch
    ):
        resp = await admin_dlq.replay_dlq(d.id, user=admin, db=db)

    assert resp.status_code == 200
    assert d.resolved is False
    assert d.replay_count == 1
    new_exec = next(o for o in db.added if isinstance(o, Execution))
    assert new_exec.status == ExecutionStatus.FAILED


@pytest.mark.asyncio
async def test_dispatch_marks_failed_when_queue_submit_raises():
    from app.routers import triggers

    agent = _agent(pool="default")
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=agent.tenant_id)
    ex = Execution(
        id=uuid.uuid4(),
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        input_message="m",
        status=ExecutionStatus.RUNNING,
    )
    db = FakeSession()
    backend = SimpleNamespace(submit=AsyncMock(side_effect=ConnectionError("nats down")))

    with patch("app.core.config.settings.scaling_exec_remote", True), patch(
        "engine.queue_backend.get_queue_backend", return_value=backend
    ):
        result, dispatched = await triggers.dispatch_execution(
            db, agent=agent, user=user, message="m", context={}, execution=ex
        )

    assert dispatched is False
    assert result.status == ExecutionStatus.FAILED
    assert result.failure_code
    assert "queue submit failed" in result.error_message
    assert db.commits >= 1
