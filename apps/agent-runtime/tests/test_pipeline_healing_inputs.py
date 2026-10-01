"""Pipeline Surgeon inputs: last good sample and traceback reach capture_failure."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from types import SimpleNamespace

import pytest

from engine import healing
from engine.pipeline import PipelineExecutor, PipelineNode
from engine.tools.base import BaseTool, ToolRegistry, ToolResult

DB_URL = "postgresql://t:t@localhost/t"


class EchoTool(BaseTool):
    name = "fetch"
    description = "Echo arguments"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(content=json.dumps(arguments))


class RaisingTool(BaseTool):
    name = "fetch"
    description = "Raises"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        raise ValueError("upstream schema changed")


class ErrorTool(BaseTool):
    name = "fetch"
    description = "Reports an error"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(content="rate limited by provider", is_error=True)


class FakeConn:
    def __init__(self) -> None:
        self.inserts: list[tuple] = []

    async def fetchrow(self, sql: str, *args):
        if sql.lstrip().startswith("SELECT COUNT"):
            return {"c": 0}
        self.inserts.append(args)
        return {"id": "diff-1"}

    async def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self, broken: bool = False) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}
        self.broken = broken

    async def set(self, key, value, ex=None):
        if self.broken:
            raise ConnectionError("redis down")
        self.store[key] = (value, ex)

    async def get(self, key):
        if self.broken:
            raise ConnectionError("redis down")
        hit = self.store.get(key)
        return hit[0] if hit else None


async def _drain() -> None:
    while healing._INFLIGHT:
        await asyncio.gather(*list(healing._INFLIGHT), return_exceptions=True)


def _executor(tool: BaseTool, pipeline_id: str, tenant_id: str) -> PipelineExecutor:
    reg = ToolRegistry()
    reg.register(tool)
    return PipelineExecutor(
        reg, db_url=DB_URL, agent_id=pipeline_id, tenant_id=tenant_id
    )


@pytest.fixture
def no_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setattr(healing, "_redis_pool", None)
    healing._success_fallback.clear()
    yield
    healing._success_fallback.clear()


@pytest.fixture
def fake_asyncpg(monkeypatch):
    conn = FakeConn()

    async def connect(*_a, **_k):
        return conn

    monkeypatch.setitem(sys.modules, "asyncpg", SimpleNamespace(connect=connect))
    return conn


async def test_success_then_raise_yields_expected_sample_and_traceback(
    no_redis, fake_asyncpg
):
    pid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    nodes = [PipelineNode(id="fetch", tool_name="fetch", arguments={"total": 42})]

    ok = await _executor(EchoTool(), pid, tid).execute(
        nodes, {"__execution_id": str(uuid.uuid4())}
    )
    assert ok.status == "completed"
    await _drain()
    assert await healing.last_success(pid, "fetch") == {"total": 42}

    bad = await _executor(RaisingTool(), pid, tid).execute(
        nodes, {"__execution_id": str(uuid.uuid4())}
    )
    assert bad.status == "failed"
    await _drain()

    assert len(fake_asyncpg.inserts) == 1
    row = fake_asyncpg.inserts[0]
    # positional order of the INSERT: $7 error_class, $9 traceback, $10 expected_shape, $12 expected_sample
    assert row[6] == "ValueError"
    assert row[8] and "ValueError" in row[8] and "upstream schema changed" in row[8]
    assert json.loads(row[9]) == {"total": "int"}
    assert json.loads(row[11]) == {"total": 42}


async def test_tool_reported_error_passes_error_text_as_traceback(
    no_redis, fake_asyncpg
):
    pid, tid = str(uuid.uuid4()), str(uuid.uuid4())
    nodes = [PipelineNode(id="fetch", tool_name="fetch", arguments={"n": 1})]
    await _executor(ErrorTool(), pid, tid).execute(
        nodes, {"__execution_id": str(uuid.uuid4())}
    )
    await _drain()
    row = fake_asyncpg.inserts[0]
    assert row[6] == "tool_error"
    assert row[8] == "rate limited by provider"
    # no prior success, so no expected sample
    assert row[9] is None and row[11] is None


async def test_remember_success_redacts_and_caps_the_sample(no_redis):
    pid = str(uuid.uuid4())
    await healing.remember_success(pid, "n", {"email": "bob@example.com", "n": 1})
    got = await healing.last_success(pid, "n")
    assert got["n"] == 1 and "bob@example.com" not in got["email"]

    await healing.remember_success(pid, "big", {"blob": "x" * 10_000})
    big = await healing.last_success(pid, "big")
    assert (
        big["_truncated"] is True and big["_orig_size"] > healing._SUCCESS_SAMPLE_BYTES
    )
    assert len(big["_preview"]) <= healing._SUCCESS_SAMPLE_BYTES + 3


async def test_remember_success_uses_redis_with_seven_day_ttl(monkeypatch):
    fake = FakeRedis()

    async def _redis():
        return fake

    monkeypatch.setattr(healing, "_get_redis", _redis)
    healing._success_fallback.clear()
    pid = str(uuid.uuid4())
    await healing.remember_success(pid, "n", {"a": 1})
    key = healing._success_key(pid, "n")
    assert fake.store[key][1] == 7 * 24 * 3600
    assert json.loads(fake.store[key][0]) == {"a": 1}
    assert await healing.last_success(pid, "n") == {"a": 1}
    assert not healing._success_fallback


async def test_broken_redis_degrades_to_process_store(monkeypatch):
    fake = FakeRedis(broken=True)

    async def _redis():
        return fake

    monkeypatch.setattr(healing, "_get_redis", _redis)
    healing._success_fallback.clear()
    pid = str(uuid.uuid4())
    await healing.remember_success(pid, "n", {"a": 1})
    assert await healing.last_success(pid, "n") == {"a": 1}
    healing._success_fallback.clear()


def test_exception_from_result_only_for_raised_classes():
    assert healing.exception_from_result("tool_error", "x") is None
    assert healing.exception_from_result("timeout", "x") is None
    assert healing.exception_from_result(None, "x") is None
    exc = healing.exception_from_result("KeyError", "missing")
    assert isinstance(exc, KeyError)
    tb = healing.safe_traceback(healing.exception_from_result("ConnectError", "boom"))
    assert tb.startswith("ConnectError: boom")
