"""signal_history reads bucketed history for an asset's signals from TimescaleDB."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from engine.agent_executor import list_tool_classes
from engine.tools import signal_history as S


def test_declared_and_registered():
    assert "signal_history" in list_tool_classes()
    fields = S.SignalHistoryTool.config_fields
    assert fields and not any(f.required for f in fields)
    assert S.SignalHistoryTool.input_schema["required"] == ["signals"]


def test_step_and_source_follow_the_range():
    assert S.pick_step(3600, 300, None) == 30
    assert S.pick_source(30, 3600) == "telemetry_samples"
    assert S.pick_step(7 * 86400, 300, None) == 3600
    assert S.pick_source(3600, 7 * 86400) == "telemetry_samples_1h"
    assert S.pick_step(3600, 300, 5) == 30


def test_relative_times():
    now = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    assert S.parse_time("-15m", now, now) == now - timedelta(minutes=15)
    assert S.parse_time("now", now - timedelta(hours=1), now) == now
    assert S.parse_time(None, now - timedelta(hours=1), now) == now - timedelta(hours=1)


def test_summary_points_at_the_peak():
    pts = [
        {"t": "a", "avg": 10.0, "min": 9.0, "max": 11.0, "n": 2},
        {"t": "b", "avg": 30.0, "min": 20.0, "max": 40.0, "n": 2},
    ]
    s = S.summarise(pts)
    assert (
        s["max"] == 40.0
        and s["max_at"] == "b"
        and s["mean"] == 20.0
        and s["samples"] == 4
    )


def test_plain_errors_without_history_or_arguments(monkeypatch):
    monkeypatch.delenv("TSDB_URL", raising=False)
    tool = S.SignalHistoryTool(tenant_id="11111111-1111-1111-1111-111111111111")
    r = asyncio.run(tool.execute({"group": "g", "node": "n"}))
    assert r.is_error and "signal" in r.content
    r = asyncio.run(tool.execute({"group": "g", "node": "n", "signals": ["p"]}))
    assert r.is_error and "TSDB_URL" in r.content
    r = asyncio.run(
        tool.execute({"group": "g", "node": "n", "signals": ["p"], "from": "-40d"})
    )
    assert r.is_error and "30 days" in r.content
