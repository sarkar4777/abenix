"""device_state reads the latest values the telemetry ingest keeps in Redis."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from engine.agent_executor import list_tool_classes
from engine.tools.device_state import DeviceStateTool
from telemetry_fakes import FakeRedis

T = "tenant-1"


def _seed(r: FakeRedis, online: str = "1") -> None:
    now = int(time.time() * 1000)

    async def go():
        await r.hset(
            f"tel:{T}:groundwork:ipc-ex1:",
            mapping={
                "_online": online,
                "_last_seen": str(now),
                "_seq_gaps": "1",
                "m:Node/Uptime_s": json.dumps(
                    {"v": 5, "t": "Int64", "ts": now, "q": "good"}
                ),
            },
        )
        await r.sadd(f"tel:{T}:nodedevs:groundwork:ipc-ex1", "", "engine", "safety")
        await r.hset(
            f"tel:{T}:groundwork:ipc-ex1:engine",
            mapping={
                "_online": "1",
                "m:Engine/Speed_rpm": json.dumps(
                    {"v": 1450.5, "t": "Double", "ts": now, "q": "good"}
                ),
                "m:Engine/Old_C": json.dumps(
                    {"v": 80, "t": "Float", "ts": now - 120_000, "q": "good"}
                ),
            },
        )
        await r.hset(
            f"tel:{T}:groundwork:ipc-ex1:safety",
            mapping={
                "_online": "1",
                "m:Safety/Hold": json.dumps(
                    {"v": False, "t": "Boolean", "ts": now, "q": "good"}
                ),
            },
        )

    asyncio.run(go())


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: r)
    return r


def _run(args):
    return asyncio.run(DeviceStateTool(tenant_id=T).execute(args))


def test_declared_and_registered():
    assert "device_state" in list_tool_classes()
    fields = DeviceStateTool.config_fields
    assert fields and not any(f.required for f in fields)
    props = DeviceStateTool.input_schema["properties"]
    assert "required" not in DeviceStateTool.input_schema
    assert {"asset", "assets", "where", "group", "node"} <= set(props)
    assert DeviceStateTool.risk_tier == "low"


def test_reads_a_whole_machine(redis):
    _seed(redis)
    res = _run({"group": "groundwork", "node": "ipc-ex1"})
    doc = json.loads(res.content)
    assert not res.is_error and doc["found"] and doc["online"] and doc["seq_gaps"] == 1
    devices = {d["device"]: d for d in doc["devices"]}
    assert set(devices) == {"engine", "safety"}
    rows = {m["name"]: m for m in devices["engine"]["metrics"]}
    assert (
        rows["Engine/Speed_rpm"]["value"] == 1450.5
        and rows["Engine/Speed_rpm"]["quality"] == "good"
    )
    assert rows["Engine/Old_C"]["quality"] == "stale", "older than the stale window"


def test_one_device_and_a_metrics_filter(redis):
    _seed(redis)
    doc = json.loads(
        _run(
            {
                "group": "groundwork",
                "node": "ipc-ex1",
                "device": "engine",
                "metrics": ["Engine/Speed*"],
            }
        ).content
    )
    assert [d["device"] for d in doc["devices"]] == ["engine"]
    assert [m["name"] for m in doc["devices"][0]["metrics"]] == ["Engine/Speed_rpm"]
    doc = json.loads(
        _run({"group": "groundwork", "node": "ipc-ex1", "metrics": "Safety/"}).content
    )
    names = [m["name"] for d in doc["devices"] for m in d["metrics"]]
    assert names == ["Safety/Hold"]


def test_offline_machine_reads_as_stale(redis):
    _seed(redis, online="0")
    doc = json.loads(_run({"group": "groundwork", "node": "ipc-ex1"}).content)
    assert doc["online"] is False
    assert all(m["quality"] == "stale" for d in doc["devices"] for m in d["metrics"])
    assert all(d["online"] is False for d in doc["devices"])


def test_unknown_machine_and_missing_arguments(redis):
    res = _run({"group": "groundwork", "node": "nope"})
    assert not res.is_error and json.loads(res.content)["found"] is False
    assert _run({"group": "groundwork"}).is_error
