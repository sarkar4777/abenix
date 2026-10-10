"""A kill switch set while a pod sat idle is honoured on the very next call."""

from __future__ import annotations

import asyncio
import time

from engine import governance


def test_idle_snapshot_is_refreshed_before_use(monkeypatch):
    reads = []

    async def fake_read():
        reads.append(1)
        return [], [("t1", "tool", "calculator", "wrong rounding")], []

    monkeypatch.setattr(governance, "_read_db", fake_read)
    governance._load([], [], [])
    # loaded long ago, as on a pod nobody has called for a minute
    monkeypatch.setattr(governance, "_loaded_at", time.monotonic() - 60)
    asyncio.run(governance.ensure_fresh())
    assert reads == [1]
    assert governance.stopped("t1", "tool", "calculator") is not None


def test_recent_snapshot_is_served_without_waiting(monkeypatch):
    reads = []

    async def fake_read():
        reads.append(1)
        return [], [], []

    monkeypatch.setattr(governance, "_read_db", fake_read)
    monkeypatch.setattr(governance, "_loaded_at", time.monotonic() - 1)
    asyncio.run(governance.ensure_fresh())
    assert reads == []


def test_a_run_start_reads_a_list_no_older_than_max_age(monkeypatch):
    reads = []

    async def fake_read():
        reads.append(1)
        return [], [("t1", "agent", "a1", "probe")], []

    monkeypatch.setattr(governance, "_read_db", fake_read)
    governance._load([], [], [])
    # two seconds old would normally be served as is
    monkeypatch.setattr(governance, "_loaded_at", time.monotonic() - 2)
    asyncio.run(governance.ensure_fresh(max_age=1.0))
    assert reads == [1]
    assert governance.stopped("t1", "agent", "a1") is not None
