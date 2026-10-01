"""write_trigger_outcome: stamps last_status / last_run_at, notifies on failure."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.dml import Update

from app.routers import triggers


class FakeSession:
    def __init__(self, rowcount=1, owner_row=None) -> None:
        self.statements: list = []
        self.rowcount = rowcount
        self.owner_row = owner_row
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        if isinstance(stmt, Update):
            return SimpleNamespace(rowcount=self.rowcount)
        return SimpleNamespace(first=lambda: self.owner_row)

    async def commit(self):
        self.commits += 1


def _factory(session):
    @asynccontextmanager
    async def _open():
        yield session

    return _open


def _compiled(stmt):
    c = stmt.compile(dialect=postgresql.dialect())
    return str(c), c.params


def test_status_mapping():
    assert triggers.trigger_outcome_status("completed") == "completed"
    assert triggers.trigger_outcome_status("COMPLETED") == "completed"
    assert triggers.trigger_outcome_status("failed") == "failed"
    assert triggers.trigger_outcome_status(None) == "failed"


@pytest.mark.asyncio
async def test_no_trigger_id_is_a_noop():
    session = FakeSession()
    ok = await triggers.write_trigger_outcome(
        _factory(session), str(uuid.uuid4()), "completed", None
    )
    assert ok is False
    assert session.statements == []


@pytest.mark.asyncio
async def test_bad_trigger_id_is_a_noop():
    session = FakeSession()
    ok = await triggers.write_trigger_outcome(
        _factory(session), str(uuid.uuid4()), "completed", None, trigger_id="nope"
    )
    assert ok is False
    assert session.statements == []


@pytest.mark.asyncio
async def test_completed_writes_status_and_run_time():
    tid = uuid.uuid4()
    session = FakeSession()
    with patch.object(triggers, "_notify_trigger_failure", AsyncMock()) as notify:
        ok = await triggers.write_trigger_outcome(
            _factory(session), str(uuid.uuid4()), "completed", None, trigger_id=str(tid)
        )
    assert ok is True
    assert len(session.statements) == 1
    sql, params = _compiled(session.statements[0])
    assert sql.startswith("UPDATE agent_triggers SET")
    assert "last_status" in sql and "last_run_at" in sql
    assert params["last_status"] == "completed"
    assert params["last_run_at"] is not None
    assert tid in params.values()
    assert session.commits == 1
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_writes_status_and_notifies_owner():
    tid = uuid.uuid4()
    owner = uuid.uuid4()
    tenant = uuid.uuid4()
    exec_id = str(uuid.uuid4())
    session = FakeSession(owner_row=(owner, tenant))
    with patch.object(triggers, "_notify_trigger_failure", AsyncMock()) as notify:
        ok = await triggers.write_trigger_outcome(
            _factory(session), exec_id, "failed", "boom", trigger_id=str(tid)
        )
    assert ok is True
    _, params = _compiled(session.statements[0])
    assert params["last_status"] == "failed"
    notify.assert_awaited_once()
    kw = notify.await_args.kwargs
    assert kw["trigger_id"] == str(tid)
    assert kw["execution_id"] == exec_id
    assert kw["user_id"] == owner
    assert kw["tenant_id"] == tenant
    assert kw["error"] == "boom"
    assert session.commits == 2


@pytest.mark.asyncio
async def test_unknown_trigger_returns_false_without_notice():
    session = FakeSession(rowcount=0)
    with patch.object(triggers, "_notify_trigger_failure", AsyncMock()) as notify:
        ok = await triggers.write_trigger_outcome(
            _factory(session),
            str(uuid.uuid4()),
            "failed",
            "boom",
            trigger_id=str(uuid.uuid4()),
        )
    assert ok is False
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_queue_payload_carries_trigger_id():
    """The consumer can only write the outcome if dispatch puts the id on the wire."""
    from app.core.config import settings

    tid = str(uuid.uuid4())
    agent = SimpleNamespace(id=uuid.uuid4(), model_config_={}, runtime_pool="default")
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
    execution = SimpleNamespace(id=uuid.uuid4(), tenant_id=user.tenant_id)
    backend = SimpleNamespace(submit=AsyncMock())
    with patch.object(settings, "scaling_exec_remote", True), patch(
        "engine.queue_backend.get_queue_backend", return_value=backend
    ):
        _, dispatched = await triggers.dispatch_execution(
            AsyncMock(),
            agent=agent,
            user=user,
            message="go",
            context={},
            trigger_id=tid,
            execution=execution,
        )
    assert dispatched is True
    backend.submit.assert_awaited_once()
    payload = backend.submit.await_args.args[1]
    assert payload["trigger_id"] == tid
    assert payload["execution_id"] == str(execution.id)
