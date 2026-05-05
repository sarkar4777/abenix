"""Argument validation for the v1.1.0 production-tooling palette tools.

These tests run without a live MQTT broker, TSDB, or Redis. They check
that each tool:
  * declares a sane input_schema (required keys present, enums match)
  * rejects bad arguments with is_error=True instead of raising
  * surfaces a "not_configured" / friendly error when an env var is
    missing rather than blowing up the executor

End-to-end tests that hit the real broker / TSDB live in tests/integration/.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from engine.tools.mqtt_publish import MqttPublishTool
from engine.tools.tsdb_query import TsdbQueryTool
from engine.tools.windowed_state import WindowedStateTool
from engine.tools.subscribed_feed import SubscribedFeedTool


# ── mqtt_publish ────────────────────────────────────────────────────


def test_mqtt_publish_declares_required_inputs():
    t = MqttPublishTool()
    assert t.name == "mqtt_publish"
    required = t.input_schema["required"]
    assert "topic" in required
    assert "payload" in required
    qos_enum = t.input_schema["properties"]["qos"]["enum"]
    assert qos_enum == [0, 1, 2]


@pytest.mark.asyncio
async def test_mqtt_publish_rejects_blank_topic():
    t = MqttPublishTool()
    r = await t.execute({"topic": "", "payload": {"x": 1}})
    assert r.is_error is True
    assert "topic" in r.content


@pytest.mark.asyncio
async def test_mqtt_publish_rejects_invalid_qos():
    t = MqttPublishTool()
    r = await t.execute({"topic": "x/y", "payload": {}, "qos": 5})
    assert r.is_error is True
    assert "qos" in r.content


# ── tsdb_query ─────────────────────────────────────────────────────


def test_tsdb_query_aggregations_match_spec():
    """The plan locks the aggregation enum at {none, avg_5m, max_1h, last}."""
    t = TsdbQueryTool()
    enum = t.input_schema["properties"]["aggregation"]["enum"]
    assert set(enum) == {"none", "avg_5m", "max_1h", "last"}


@pytest.mark.asyncio
async def test_tsdb_query_rejects_missing_metric():
    t = TsdbQueryTool()
    r = await t.execute({"metric": "", "since": "2024-01-01T00:00:00Z"})
    assert r.is_error is True
    assert "metric" in r.content


@pytest.mark.asyncio
async def test_tsdb_query_rejects_missing_since():
    t = TsdbQueryTool()
    r = await t.execute({"metric": "vibration", "since": ""})
    assert r.is_error is True
    assert "since" in r.content


@pytest.mark.asyncio
async def test_tsdb_query_rejects_unknown_aggregation():
    t = TsdbQueryTool()
    r = await t.execute(
        {
            "metric": "vibration",
            "since": "2024-01-01T00:00:00Z",
            "aggregation": "bogus",
        }
    )
    assert r.is_error is True
    assert "aggregation" in r.content


@pytest.mark.asyncio
async def test_tsdb_query_rejects_dangerous_table_name():
    t = TsdbQueryTool()
    r = await t.execute(
        {
            "metric": "vibration",
            "since": "2024-01-01T00:00:00Z",
            "table": "metrics; DROP TABLE users",
        }
    )
    assert r.is_error is True


@pytest.mark.asyncio
async def test_tsdb_query_returns_friendly_error_when_url_missing(monkeypatch):
    monkeypatch.delenv("TSDB_URL", raising=False)
    monkeypatch.delenv("TIMESCALE_URL", raising=False)
    t = TsdbQueryTool()
    r = await t.execute({"metric": "vibration", "since": "2024-01-01T00:00:00Z"})
    assert r.is_error is True
    body = json.loads(r.content)
    assert body["status"] == "not_configured"


# ── windowed_state ─────────────────────────────────────────────────


def test_windowed_state_operations_match_spec():
    t = WindowedStateTool()
    enum = t.input_schema["properties"]["operation"]["enum"]
    assert set(enum) == {"append", "query", "count", "pattern_match"}


@pytest.mark.asyncio
async def test_windowed_state_rejects_unknown_operation():
    t = WindowedStateTool()
    r = await t.execute({"operation": "wat", "asset_id": "p1", "name": "vib"})
    assert r.is_error is True


@pytest.mark.asyncio
async def test_windowed_state_rejects_blank_asset_or_name():
    t = WindowedStateTool()
    r = await t.execute({"operation": "append", "asset_id": "", "name": "n"})
    assert r.is_error is True
    r = await t.execute({"operation": "append", "asset_id": "p1", "name": ""})
    assert r.is_error is True


@pytest.mark.asyncio
async def test_windowed_state_pattern_match_requires_seq():
    """pattern_match must reject an empty pattern_seq cleanly. We force
    Redis to a known-bad URL so the connect path fails fast — then the
    arg validation still runs first and short-circuits."""
    # We only get to pattern_seq validation if Redis connects, so use a
    # DummyRedis that no-ops zrange. Simplest: monkey-patch
    # redis.asyncio.from_url to a fake.

    class _FakeRedis:
        async def zrange(self, *_a: Any, **_k: Any):
            return []

        async def aclose(self) -> None:
            return None

    import engine.tools.windowed_state as ws

    original = ws.aioredis if hasattr(ws, "aioredis") else None  # noqa: F841

    def _from_url(*_a: Any, **_k: Any):
        return _FakeRedis()

    # The tool imports redis.asyncio inside execute(); patch sys.modules.
    import sys
    import types

    fake_mod = types.SimpleNamespace(from_url=_from_url)
    parent = types.SimpleNamespace(asyncio=fake_mod)
    sys.modules["redis"] = parent
    sys.modules["redis.asyncio"] = fake_mod

    try:
        t = WindowedStateTool()
        r = await t.execute(
            {
                "operation": "pattern_match",
                "asset_id": "p1",
                "name": "alarms",
                "pattern_seq": [],
            }
        )
        assert r.is_error is True
    finally:
        # restore — pytest runs tests in unpredictable order otherwise.
        sys.modules.pop("redis.asyncio", None)
        sys.modules.pop("redis", None)


# ── subscribed_feed ────────────────────────────────────────────────


def test_subscribed_feed_required_inputs():
    t = SubscribedFeedTool()
    assert t.input_schema["required"] == ["feed_id"]


@pytest.mark.asyncio
async def test_subscribed_feed_rejects_blank_feed_id():
    t = SubscribedFeedTool()
    r = await t.execute({"feed_id": ""})
    assert r.is_error is True


# ── tool_registry registration ─────────────────────────────────────


def test_all_four_tools_register_in_registry():
    """Each tool must be discoverable by name from the registry — the UI
    palette key off this map."""
    from engine.tools.base import ToolRegistry

    reg = ToolRegistry()
    reg.register(MqttPublishTool())
    reg.register(TsdbQueryTool())
    reg.register(WindowedStateTool())
    reg.register(SubscribedFeedTool())

    names = set(reg.names())
    assert {"mqtt_publish", "tsdb_query", "windowed_state", "subscribed_feed"} <= names

    # to_dict must surface input_schema so the LLM sees a valid manifest.
    for name in ("mqtt_publish", "tsdb_query", "windowed_state", "subscribed_feed"):
        d = reg.get(name).to_dict()
        assert d["name"] == name
        assert "input_schema" in d
        assert d["input_schema"]["type"] == "object"
