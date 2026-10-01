"""human_approval gate ids, expiry metadata and the sweeper marker."""

from __future__ import annotations

import asyncio
import json

import pytest

from engine.tools import human_approval as ha


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.expires: dict[str, int] = {}

    async def smembers(self, key):
        return set(self.sets.get(key, set()))

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    async def get(self, key):
        return self.kv.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        if ex:
            self.expires[key] = ex
        return True

    async def delete(self, key):
        self.kv.pop(key, None)

    async def ttl(self, key):
        return self.expires.get(key, -1)

    async def expire(self, key, seconds):
        self.expires[key] = seconds
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(ha, "_redis_pool", r)
    return r


def _tool():
    return ha.HumanApprovalTool(
        execution_id="exec-1", tenant_id="tenant-1", agent_name="deployer"
    )


@pytest.mark.asyncio
async def test_missing_execution_context_is_an_error_not_a_wait(fake_redis):
    tool = ha.HumanApprovalTool(execution_id="", tenant_id="", agent_name="x")
    result = await asyncio.wait_for(tool.execute({"action": "deploy"}), timeout=2)
    assert result.is_error
    assert "execution context" in result.content
    assert fake_redis.sets == {}


@pytest.mark.asyncio
async def test_gate_ids_are_unique_across_gates(fake_redis):
    tool = _tool()
    seen: list[str] = []

    async def approve_whatever():
        # approve each gate as soon as it shows up in the pending set
        while len(seen) < 2:
            for member in list(fake_redis.sets.get("hitl:pending:tenant-1", set())):
                data = json.loads(member)
                gate = data["gate_id"]
                if gate not in seen:
                    seen.append(gate)
                    await ha.submit_approval("exec-1", gate, "approved", reviewer="r")
            await asyncio.sleep(0.01)

    approver = asyncio.create_task(approve_whatever())
    first = await asyncio.wait_for(tool.execute({"action": "a"}), timeout=10)
    second = await asyncio.wait_for(tool.execute({"action": "b"}), timeout=10)
    await approver
    assert not first.is_error and not second.is_error
    assert first.metadata["gate_id"] != second.metadata["gate_id"]
    assert not first.metadata["gate_id"].startswith("gate-1")


@pytest.mark.asyncio
async def test_pending_entry_carries_expiry_and_waiting_marker(fake_redis):
    tool = _tool()
    task = asyncio.create_task(tool.execute({"action": "a", "timeout_seconds": 600}))
    for _ in range(100):
        if fake_redis.sets.get("hitl:pending:tenant-1"):
            break
        await asyncio.sleep(0.01)
    members = fake_redis.sets["hitl:pending:tenant-1"]
    assert len(members) == 1
    entry = json.loads(next(iter(members)))
    assert entry["expires_at"] == pytest.approx(entry["requested_at"] + 600, abs=1)
    assert fake_redis.expires["hitl:pending:tenant-1"] >= 600
    assert fake_redis.kv.get("hitl:waiting:exec-1") == "1"
    assert fake_redis.expires["hitl:waiting:exec-1"] == 600

    await ha.submit_approval(
        "exec-1", entry["gate_id"], "rejected", reviewer="r", comment="no"
    )
    result = await asyncio.wait_for(task, timeout=10)
    assert result.is_error
    assert "hitl:waiting:exec-1" not in fake_redis.kv
    assert fake_redis.sets["hitl:pending:tenant-1"] == set()


@pytest.mark.asyncio
async def test_mark_and_clear_waiting(fake_redis):
    await ha.mark_waiting("exec-9", 120)
    assert fake_redis.kv["hitl:waiting:exec-9"] == "1"
    await ha.clear_waiting("exec-9")
    assert "hitl:waiting:exec-9" not in fake_redis.kv
    await ha.mark_waiting("", 120)
    assert fake_redis.kv == {}
