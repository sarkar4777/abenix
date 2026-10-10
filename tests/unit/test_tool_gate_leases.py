"""Tool concurrency slots are leases: a release frees one, and one never released frees itself."""

from __future__ import annotations

import asyncio

from app.core import tool_gate


class FakeRedis:
    def __init__(self):
        self.z: dict[str, dict[str, float]] = {}

    async def zremrangebyscore(self, key, lo, hi):
        hi = float(hi)
        self.z[key] = {m: s for m, s in self.z.get(key, {}).items() if s > hi}

    async def zadd(self, key, mapping):
        self.z.setdefault(key, {}).update(mapping)

    async def expire(self, key, ttl):
        return True

    async def zcard(self, key):
        return len(self.z.get(key, {}))

    async def zrem(self, key, member):
        self.z.get(key, {}).pop(member, None)


def test_cap_is_enforced_and_release_frees_a_slot():
    r = FakeRedis()

    async def go():
        assert await tool_gate._sem_acquire(r, "k", 2, 60, "a")
        assert await tool_gate._sem_acquire(r, "k", 2, 60, "b")
        assert not await tool_gate._sem_acquire(r, "k", 2, 60, "c")
        await tool_gate._sem_release(r, "k", "a")
        assert await tool_gate._sem_acquire(r, "k", 2, 60, "c")
        assert await tool_gate._sem_count(r, "k") == 2

    asyncio.run(go())


def test_a_lease_never_released_expires(monkeypatch):
    r = FakeRedis()
    now = [1000.0]
    monkeypatch.setattr(tool_gate.time, "time", lambda: now[0])

    async def go():
        assert await tool_gate._sem_acquire(r, "k", 1, 30, "lost")
        assert not await tool_gate._sem_acquire(r, "k", 1, 30, "next")
        now[0] += 31
        assert await tool_gate._sem_acquire(r, "k", 1, 30, "next")

    asyncio.run(go())


def test_a_rejected_acquire_leaves_no_lease_behind():
    r = FakeRedis()

    async def go():
        await tool_gate._sem_acquire(r, "k", 1, 60, "a")
        await tool_gate._sem_acquire(r, "k", 1, 60, "b")
        assert set(r.z["k"]) == {"a"}

    asyncio.run(go())
