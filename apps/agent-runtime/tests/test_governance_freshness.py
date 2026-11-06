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


def test_a_write_during_a_read_is_not_hidden_by_it(monkeypatch):
    rows = [("t1", "medium", {"publish_approvals": {"escalate_after_minutes": 1}})]
    reads = []

    async def fake_read():
        reads.append(1)
        if len(reads) == 1:
            # the policy is saved after this read took its snapshot
            governance.invalidate()
            return [], [], []
        return rows, [], []

    monkeypatch.setattr(governance, "_read_db", fake_read)
    governance._load([], [], [])
    monkeypatch.setattr(governance, "_loaded_at", 0.0)
    asyncio.run(governance.ensure_fresh())
    asyncio.run(governance.ensure_fresh())
    assert reads == [1, 1]
    medium = governance.policy("t1", "medium")["publish_approvals"]
    assert medium["escalate_after_minutes"] == 1


def test_max_age_zero_reads_a_policy_saved_on_another_worker(monkeypatch):
    rows = [("t1", "medium", {"publish_approvals": {"escalate_after_minutes": 1}})]

    async def fake_read():
        return rows, [], []

    monkeypatch.setattr(governance, "_read_db", fake_read)
    governance._load([], [], [])
    # this worker refreshed a moment ago, before the save it never heard about
    monkeypatch.setattr(governance, "_loaded_at", time.monotonic())
    asyncio.run(governance.ensure_fresh(max_age=0))
    medium = governance.policy("t1", "medium")["publish_approvals"]
    assert medium["escalate_after_minutes"] == 1
