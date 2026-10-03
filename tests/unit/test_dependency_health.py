"""The PostgresDown and RedisDown alerts read a gauge the API really exports."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from prometheus_client import REGISTRY, generate_latest

from app.core import dependency_health

RULES = (
    Path(__file__).resolve().parents[2]
    / "infra/helm/abenix/templates/prometheus-rules.yaml"
)


def _value(component: str) -> float | None:
    return REGISTRY.get_sample_value("abenix_health_check", {"component": component})


def test_probe_records_up_and_down(monkeypatch):
    async def up():
        return True

    async def down():
        return False

    monkeypatch.setattr(dependency_health, "probe_postgres", up)
    monkeypatch.setattr(dependency_health, "probe_redis", down)
    result = asyncio.run(dependency_health.probe_once())
    assert result == {"postgres": True, "redis": False}
    assert _value("postgres") == 1.0
    assert _value("redis") == 0.0

    monkeypatch.setattr(dependency_health, "probe_postgres", down)
    asyncio.run(dependency_health.probe_once())
    assert _value("postgres") == 0.0


def test_unreachable_redis_reports_false(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(dependency_health, "PROBE_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    assert asyncio.run(dependency_health.probe_redis()) is False


def test_alert_rules_use_the_exported_metric():
    text = RULES.read_text()
    for alert, component in (("PostgresDown", "postgres"), ("RedisDown", "redis")):
        block = text.split(f"alert: {alert}", 1)[1].split("- alert:", 1)[0]
        expr = re.search(r"expr:\s*(.+)", block).group(1)
        assert f'abenix_health_check{{component="{component}"}} == 0' in expr
    assert b"abenix_health_check" in generate_latest()


def test_loop_starts_and_stops(monkeypatch):
    calls = []

    async def fake_probe():
        calls.append(1)
        return {"postgres": True, "redis": True}

    monkeypatch.setattr(dependency_health, "probe_once", fake_probe)

    async def run():
        dependency_health.start()
        await asyncio.sleep(0.05)
        await dependency_health.stop()

    asyncio.run(run())
    assert calls
    assert dependency_health._task is None
