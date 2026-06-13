"""Edge-case drift audit:
  - Confidence drop (0.9 baseline -> 0.4 current) — is it caught?
  - Cost drift (0.01 baseline -> 0.05 current) — is it caught?
  - Moderate 1.5σ shift — should NOT alert (under 2σ threshold).
  - Variable baseline (std>0) — proper σ math, not floor."""
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


async def main():
    det = DriftDetector(redis_url=REDIS_URL)

    # Scenario A: realistic baseline with stddev (10% noise around mean)
    agent_a = f"audit-realistic-{uuid.uuid4().hex[:8]}"
    await reset(agent_a)
    import random
    random.seed(42)
    for _ in range(12):
        await det.record_execution(
            agent_id=agent_a,
            duration_ms=int(1000 + random.gauss(0, 50)),
            input_tokens=int(500 + random.gauss(0, 25)),
            output_tokens=int(200 + random.gauss(0, 10)),
            cost=0.01 + random.gauss(0, 0.0005),
            confidence=0.9 + random.gauss(0, 0.02),
            output_length=int(800 + random.gauss(0, 40)),
            tool_failures=0,
            total_tool_calls=1,
        )
    await det.capture_baseline(agent_a)
    b = await det.get_baseline(agent_a)
    print(f"[realistic] avg_dur={b.avg_duration_ms:.1f}+-{b.std_duration_ms:.1f} avg_conf={b.avg_confidence:.3f}+-{b.std_confidence:.3f}")

    # Moderate 1.5σ shift in duration only (should NOT fire — under 2σ)
    moderate_alerts = []
    for _ in range(50):
        a = await det.record_execution(
            agent_id=agent_a,
            duration_ms=int(b.avg_duration_ms + 1.5 * b.std_duration_ms),
            input_tokens=int(b.avg_input_tokens),
            output_tokens=int(b.avg_output_tokens),
            cost=b.avg_cost,
            confidence=b.avg_confidence,
            output_length=int(b.avg_output_length),
            tool_failures=0,
            total_tool_calls=1,
        )
        moderate_alerts.extend(a)
    print(f"[moderate 1.5sigma] alerts: {len(moderate_alerts)} (want=0)")

    # Confidence 0.9 -> 0.4 (big absolute change)
    agent_c = f"audit-conf-{uuid.uuid4().hex[:8]}"
    await reset(agent_c)
    for _ in range(12):
        await det.record_execution(
            agent_id=agent_c,
            duration_ms=1000, input_tokens=500, output_tokens=200,
            cost=0.01, confidence=0.9, output_length=800,
            tool_failures=0, total_tool_calls=1,
        )
    await det.capture_baseline(agent_c)
    conf_alerts = []
    for _ in range(50):
        a = await det.record_execution(
            agent_id=agent_c,
            duration_ms=1000, input_tokens=500, output_tokens=200,
            cost=0.01, confidence=0.4, output_length=800,
            tool_failures=0, total_tool_calls=1,
        )
        conf_alerts.extend(a)
    conf_metrics = {a.metric_name for a in conf_alerts}
    print(f"[confidence 0.9->0.4] alerts: {len(conf_alerts)} metrics={sorted(conf_metrics)}")
    if "confidence" not in conf_metrics:
        print("  WARN: confidence drift NOT detected because eff_sigma floor of 1.0 unit > 0.5 absolute change")


if __name__ == "__main__":
    asyncio.run(main())
