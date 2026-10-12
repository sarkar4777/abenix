"""A run whose runtime pod stopped and that no pod took over fails with WORKER_STOPPED and a plain reason, never staying running."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.updates: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt):
        from sqlalchemy.dialects import postgresql

        compiled = stmt.compile(dialect=postgresql.dialect())
        if str(compiled).startswith("UPDATE"):
            self.updates.append(compiled.params)
            return _Result([])
        return _Result(self.rows)

    async def commit(self):
        pass

    def add(self, obj):
        pass


@pytest.mark.asyncio
async def test_a_run_whose_worker_stopped_fails_with_a_plain_reason(monkeypatch):
    from app.core import scheduler

    monkeypatch.setenv("WORKER_GONE_SECONDS", "300")
    now = datetime.now(timezone.utc)
    gone = uuid.uuid4()
    old = uuid.uuid4()
    rows = [
        # a pod held it and its lease ran out ten minutes ago
        (
            gone,
            None,
            uuid.uuid4(),
            None,
            now - timedelta(minutes=12),
            "rt-1",
            now - timedelta(minutes=10),
        ),
        # never claimed by a pod, just old
        (old, None, uuid.uuid4(), None, now - timedelta(minutes=30), None, None),
    ]
    db = _Db(rows)

    @asynccontextmanager
    async def _lock(key):
        yield True

    async def _waiting(ids):
        return set()

    with patch.object(scheduler, "advisory_lock", _lock), patch(
        "app.core.deps.async_session", lambda: db
    ), patch("app.core.hitl.waiting_execution_ids", _waiting):
        out = await scheduler.sweep_stale_executions()
    assert out == {"swept": 2}
    codes = {u.get("failure_code") for u in db.updates}
    assert codes == {"WORKER_STOPPED", "STALE_SWEEP"}
    stopped = next(u for u in db.updates if u.get("failure_code") == "WORKER_STOPPED")
    assert stopped["error_message"] == scheduler.WORKER_STOPPED_MESSAGE
    assert gone in stopped["id_1"]


def test_only_a_pod_held_run_with_a_long_lapsed_lease_counts_as_stopped():
    from app.core import scheduler

    now = datetime.now(timezone.utc)
    cut = now - timedelta(seconds=300)
    row = lambda runner, lease: (1, 2, 3, 4, now, runner, lease)  # noqa: E731
    assert scheduler.worker_stopped(row("rt", now - timedelta(minutes=6)), cut)
    assert not scheduler.worker_stopped(row("rt", now - timedelta(minutes=2)), cut)
    assert not scheduler.worker_stopped(row(None, now - timedelta(minutes=6)), cut)
    assert not scheduler.worker_stopped(row("rt", None), cut)


def test_the_failure_code_reads_back_from_the_message():
    from app.core import scheduler
    from app.core.failure_codes import classify_exception

    assert classify_exception(scheduler.WORKER_STOPPED_MESSAGE) == "WORKER_STOPPED"
