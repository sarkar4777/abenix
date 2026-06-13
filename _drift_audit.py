"""Drift audit harness.

Drives the production DriftDetector against the running redis with two scenarios:
  1. Seed 10 baseline executions -> capture baseline.
  2. Send 50 SHIFTED inputs (3x baseline duration/tokens). Expect alerts (P0 if not).
  3. Reset agent, seed baseline, send 50 IDENTICAL inputs. Expect zero alerts (P0 if false-positives).
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "apps", "agent-runtime"))

from engine.drift_detection import DriftDetector  # noqa: E402

REDIS_URL = "redis://localhost:6379/0"


async def reset(agent_id: str) -> None:
    import redis.asyncio as aioredis

    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    await r.delete(f"drift:baseline:{agent_id}")
    await r.delete(f"drift:recent:{agent_id}")
    await r.aclose()


async def seed_baseline(det: DriftDetector, agent_id: str, n: int = 12) -> None:
    for _ in range(n):
        await det.record_execution(
            agent_id=agent_id,
            duration_ms=1000,
            input_tokens=500,
            output_tokens=200,
            cost=0.01,
            confidence=0.9,
            output_length=800,
            tool_failures=0,
            total_tool_calls=1,
        )
    await det.capture_baseline(agent_id)


async def scenario_shifted(det: DriftDetector, agent_id: str, n: int = 50) -> dict:
    """Send 50 shifted executions. Tally alerts."""
    tally = {"total_alerts": 0, "executions_with_alerts": 0, "metrics_seen": set()}
    for _ in range(n):
        alerts = await det.record_execution(
            agent_id=agent_id,
            duration_ms=5000,   # 5x baseline
            input_tokens=2500,  # 5x
            output_tokens=1000, # 5x
            cost=0.05,          # 5x
            confidence=0.5,     # large drop
            output_length=4000, # 5x
            tool_failures=1,
            total_tool_calls=1,
        )
        if alerts:
            tally["executions_with_alerts"] += 1
            tally["total_alerts"] += len(alerts)
            for a in alerts:
                tally["metrics_seen"].add(a.metric_name)
    tally["metrics_seen"] = sorted(tally["metrics_seen"])
    return tally


async def scenario_identical(det: DriftDetector, agent_id: str, n: int = 50) -> dict:
    """Send 50 identical-to-baseline executions. Tally false positives."""
    tally = {"total_alerts": 0, "executions_with_alerts": 0, "metrics_seen": set(), "sample_alerts": []}
    for _ in range(n):
        alerts = await det.record_execution(
            agent_id=agent_id,
            duration_ms=1000,
            input_tokens=500,
            output_tokens=200,
            cost=0.01,
            confidence=0.9,
            output_length=800,
            tool_failures=0,
            total_tool_calls=1,
        )
        if alerts:
            tally["executions_with_alerts"] += 1
            tally["total_alerts"] += len(alerts)
            for a in alerts:
                tally["metrics_seen"].add(a.metric_name)
                if len(tally["sample_alerts"]) < 3:
                    tally["sample_alerts"].append(a.message)
    tally["metrics_seen"] = sorted(tally["metrics_seen"])
    return tally


async def main():
    det = DriftDetector(redis_url=REDIS_URL)

    # Scenario 1: SHIFTED
    agent_a = f"audit-shift-{uuid.uuid4().hex[:8]}"
    await reset(agent_a)
    await seed_baseline(det, agent_a)
    b = await det.get_baseline(agent_a)
    print(f"[shift] baseline n={b.sample_count} avg_dur={b.avg_duration_ms:.1f} std_dur={b.std_duration_ms:.3f}")
    t1 = await scenario_shifted(det, agent_a)
    print(f"[shift] {t1}")

    # Scenario 2: IDENTICAL
    agent_b = f"audit-ident-{uuid.uuid4().hex[:8]}"
    await reset(agent_b)
    await seed_baseline(det, agent_b)
    b2 = await det.get_baseline(agent_b)
    print(f"[ident] baseline n={b2.sample_count} avg_dur={b2.avg_duration_ms:.1f} std_dur={b2.std_duration_ms:.3f}")
    t2 = await scenario_identical(det, agent_b)
    print(f"[ident] {t2}")

    # Verdict
    print("---")
    print(f"REAL_SHIFT_DETECTED: {t1['total_alerts'] > 0}")
    print(f"NO_FALSE_POSITIVE: {t2['total_alerts'] == 0}")
    print(f"PER_FEATURE_BREAKDOWN: {len(t1['metrics_seen'])} metrics: {t1['metrics_seen']}")


if __name__ == "__main__":
    asyncio.run(main())
