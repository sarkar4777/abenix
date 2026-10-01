"""Drift detector: relative sigma floor and rolling baseline refresh."""

from __future__ import annotations

import json

import pytest

from engine.drift_detection import (
    METRIC_EPS,
    BaselineMetrics,
    DriftDetector,
    blend_baselines,
    effective_sigma,
)


class FakePipeline:
    def __init__(self, store: "FakeRedis") -> None:
        self._store = store
        self._ops: list[tuple] = []

    def lpush(self, key, value):
        self._ops.append(("lpush", key, value))

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))

    def incr(self, key):
        self._ops.append(("incr", key))

    async def execute(self):
        out = []
        for op in self._ops:
            name = op[0]
            if name == "lpush":
                out.append(await self._store.lpush(op[1], op[2]))
            elif name == "ltrim":
                out.append(await self._store.ltrim(op[1], op[2], op[3]))
            elif name == "expire":
                out.append(True)
            elif name == "incr":
                out.append(await self._store.incr(op[1]))
        self._ops = []
        return out


class FakeRedis:
    """Just enough of redis.asyncio for DriftDetector."""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.kv: dict[str, str] = {}

    def pipeline(self):
        return FakePipeline(self)

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]
        return True

    async def llen(self, key):
        return len(self.lists.get(key, []))

    async def lrange(self, key, start, end):
        vals = self.lists.get(key, [])
        return vals if end == -1 else vals[start : end + 1]

    async def incr(self, key):
        v = int(self.kv.get(key, "0")) + 1
        self.kv[key] = str(v)
        return v

    async def set(self, key, value, ex=None):
        self.kv[key] = str(value)
        return True

    async def get(self, key):
        return self.kv.get(key)


def _detector(fake: FakeRedis, **kw) -> DriftDetector:
    d = DriftDetector(redis_url="redis://unused", db_url="", **kw)
    d._pool = fake  # type: ignore[assignment]
    return d


def _baseline(**overrides) -> BaselineMetrics:
    b = BaselineMetrics(sample_count=20)
    for k, v in overrides.items():
        setattr(b, k, v)
    return b


def test_effective_sigma_has_no_absolute_unit_floor():
    assert effective_sigma("confidence", 0.01, 0.9) == pytest.approx(0.09)
    assert effective_sigma("cost", 0.0001, 0.002) == pytest.approx(0.0005)
    assert effective_sigma("tool_failure_rate", 0.0, 0.0) == METRIC_EPS[
        "tool_failure_rate"
    ]
    # Big metrics keep the larger of std and 10% of baseline.
    assert effective_sigma("duration_ms", 400.0, 1000.0) == 400.0
    assert effective_sigma("duration_ms", 10.0, 1000.0) == 100.0


def test_zero_to_one_metric_can_alert():
    d = _detector(FakeRedis())
    b = _baseline(avg_confidence=0.9, std_confidence=0.01)
    alerts = d._check_drift("a1", b, confidence=0.5)
    by_metric = {a.metric_name: a for a in alerts}
    assert "confidence" in by_metric
    assert by_metric["confidence"].severity == "critical"
    assert by_metric["confidence"].deviation_pct == pytest.approx(-44.4, abs=0.1)


def test_tool_failure_rate_jump_alerts():
    d = _detector(FakeRedis())
    b = _baseline(tool_failure_rate=0.0, std_tool_failure_rate=0.0)
    alerts = d._check_drift("a1", b, tool_failure_rate=0.5)
    assert [a.metric_name for a in alerts] == ["tool_failure_rate"]
    assert alerts[0].severity == "critical"


def test_small_dollar_cost_can_alert():
    d = _detector(FakeRedis())
    b = _baseline(avg_cost=0.01, std_cost=0.001)
    alerts = d._check_drift("a1", b, cost=0.03)
    assert [a.metric_name for a in alerts] == ["cost"]


def test_rounding_noise_does_not_alert():
    d = _detector(FakeRedis())
    b = _baseline(avg_duration_ms=1000.0, std_duration_ms=5.0)
    assert d._check_drift("a1", b, duration_ms=1050) == []


def test_blend_is_ema():
    old = _baseline(avg_duration_ms=100.0, std_duration_ms=10.0)
    fresh = _baseline(avg_duration_ms=200.0, std_duration_ms=20.0)
    out = blend_baselines(old, fresh, 0.3)
    assert out.avg_duration_ms == pytest.approx(130.0)
    assert out.std_duration_ms == pytest.approx(13.0)
    assert out.source == "ema"


async def _record(d: DriftDetector, agent: str, duration: int, n: int):
    out = []
    for _ in range(n):
        out.append(
            await d.record_execution(
                agent_id=agent,
                duration_ms=duration,
                input_tokens=100,
                output_tokens=50,
                cost=0.001,
                confidence=0.9,
                output_length=400,
                tool_failures=0,
                total_tool_calls=2,
            )
        )
    return out


@pytest.mark.asyncio
async def test_baseline_is_captured_then_refreshed():
    fake = FakeRedis()
    d = _detector(fake, refresh_every=10, ema_alpha=0.5)

    # Nine samples: no baseline yet, nothing fires.
    first = await _record(d, "agent-1", 100, 9)
    assert all(a == [] for a in first)
    assert (await d.get_baseline("agent-1")).sample_count == 0

    # Tenth sample captures the baseline from the window.
    await _record(d, "agent-1", 100, 1)
    b0 = await d.get_baseline("agent-1")
    assert b0.sample_count == 10
    assert b0.avg_duration_ms == pytest.approx(100.0)
    assert b0.source == "redis"

    # A regime shift fires alerts and, after refresh_every samples, moves
    # the baseline instead of freezing it forever.
    shifted = await _record(d, "agent-1", 1000, 10)
    assert any(a.metric_name == "duration_ms" for a in shifted[0])
    b1 = await d.get_baseline("agent-1")
    assert b1.source == "ema"
    assert b1.avg_duration_ms > 100.0
    assert b1.captured_at >= b0.captured_at
    assert fake.kv["drift:baseline:since_refresh:agent-1"] == "0"

    # Keep shifting and the baseline converges on the new level.
    await _record(d, "agent-1", 1000, 10)
    b2 = await d.get_baseline("agent-1")
    assert b2.avg_duration_ms > b1.avg_duration_ms


@pytest.mark.asyncio
async def test_db_path_is_preferred_when_available(monkeypatch):
    fake = FakeRedis()
    d = _detector(fake, refresh_every=10)
    await _record(d, "agent-2", 100, 10)

    db_baseline = _baseline(avg_duration_ms=5000.0, std_duration_ms=100.0)
    db_baseline.sample_count = 50
    db_baseline.source = "db"

    async def fake_db(agent_id):
        return db_baseline

    monkeypatch.setattr(d, "_baseline_from_db", fake_db)
    await _record(d, "agent-2", 100, 10)
    b = await d.get_baseline("agent-2")
    assert b.source == "db"
    assert b.avg_duration_ms == 5000.0
    assert b.sample_count == 50


def test_baseline_roundtrip_ignores_unknown_keys():
    raw = json.dumps({"avg_cost": 0.5, "sample_count": 12, "bogus": 1})
    b = BaselineMetrics.from_json(raw)
    assert b.avg_cost == 0.5 and b.sample_count == 12
    assert BaselineMetrics.from_json(b.to_json()).avg_cost == 0.5
