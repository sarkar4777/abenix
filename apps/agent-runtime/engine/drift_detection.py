"""Drift Detection — monitors agent behavior for deviations from baseline."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from typing import Any

import redis.asyncio as aioredis


@dataclass
class BaselineMetrics:
    avg_duration_ms: float = 0.0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    avg_cost: float = 0.0
    avg_confidence: float = 0.0
    avg_output_length: float = 0.0
    tool_failure_rate: float = 0.0
    sample_count: int = 0
    # Population std dev per metric — used by _check_drift to turn the
    # 2.0/3.0 thresholds into actual σ comparisons.
    std_duration_ms: float = 0.0
    std_input_tokens: float = 0.0
    std_output_tokens: float = 0.0
    std_cost: float = 0.0
    std_confidence: float = 0.0
    std_output_length: float = 0.0
    std_tool_failure_rate: float = 0.0


@dataclass
class DriftAlert:
    agent_id: str
    metric_name: str
    baseline_value: float
    current_value: float
    deviation_pct: float
    severity: str  # "warning" (>2σ) or "critical" (>3σ)
    message: str


def _baseline_key(agent_id: str) -> str:
    return f"drift:baseline:{agent_id}"


def _recent_key(agent_id: str) -> str:
    return f"drift:recent:{agent_id}"


class DriftDetector:
    """Tracks agent execution metrics and detects drift from baseline."""

    def __init__(self, redis_url: str, warning_threshold: float = 2.0, critical_threshold: float = 3.0):
        self._redis_url = redis_url
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._pool: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._pool is None:
            self._pool = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._pool

    async def record_execution(
        self,
        agent_id: str,
        duration_ms: int,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        confidence: float,
        output_length: int,
        tool_failures: int = 0,
        total_tool_calls: int = 0,
    ) -> list[DriftAlert]:
        """Record an execution and check for drift. Returns any alerts."""
        r = await self._get_redis()

        # Store in recent window (last 100 executions)
        metric = json.dumps({
            "duration_ms": duration_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "confidence": confidence,
            "output_length": output_length,
            "tool_failure_rate": tool_failures / max(total_tool_calls, 1),
            "timestamp": time.time(),
        })
        key = _recent_key(agent_id)
        pipe = r.pipeline()
        pipe.lpush(key, metric)
        pipe.ltrim(key, 0, 99)  # Keep last 100
        pipe.expire(key, 86400 * 7)  # 7 days
        await pipe.execute()

        # Check against baseline (auto-capture once the recent window has
        # ≥10 samples and no baseline has been captured yet — otherwise
        # baselines were never established and drift never fired).
        baseline = await self.get_baseline(agent_id)
        if baseline.sample_count == 0:
            window_len = await r.llen(_recent_key(agent_id))
            if window_len >= 10:
                baseline = await self.capture_baseline(agent_id)
        if baseline.sample_count < 10:
            return []  # Not enough data for baseline

        return self._check_drift(
            agent_id, baseline,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            confidence=confidence,
            output_length=output_length,
            tool_failure_rate=tool_failures / max(total_tool_calls, 1),
        )

    async def capture_baseline(self, agent_id: str) -> BaselineMetrics:
        """Capture baseline from the last N executions."""
        r = await self._get_redis()
        raw_entries = await r.lrange(_recent_key(agent_id), 0, -1)

        if not raw_entries:
            return BaselineMetrics()

        entries = [json.loads(e) for e in raw_entries]
        n = len(entries)

        def _avg_std(key: str) -> tuple[float, float]:
            vals = [float(e[key]) for e in entries]
            avg = sum(vals) / n
            var = sum((v - avg) ** 2 for v in vals) / n
            return avg, math.sqrt(var)

        avg_d,   std_d   = _avg_std("duration_ms")
        avg_it,  std_it  = _avg_std("input_tokens")
        avg_ot,  std_ot  = _avg_std("output_tokens")
        avg_c,   std_c   = _avg_std("cost")
        avg_conf,std_conf= _avg_std("confidence")
        avg_ol,  std_ol  = _avg_std("output_length")
        avg_tfr, std_tfr = _avg_std("tool_failure_rate")

        baseline = BaselineMetrics(
            avg_duration_ms=avg_d,   std_duration_ms=std_d,
            avg_input_tokens=avg_it, std_input_tokens=std_it,
            avg_output_tokens=avg_ot,std_output_tokens=std_ot,
            avg_cost=avg_c,          std_cost=std_c,
            avg_confidence=avg_conf, std_confidence=std_conf,
            avg_output_length=avg_ol,std_output_length=std_ol,
            tool_failure_rate=avg_tfr, std_tool_failure_rate=std_tfr,
            sample_count=n,
        )

        # Store baseline
        await r.set(
            _baseline_key(agent_id),
            json.dumps({
                "avg_duration_ms": baseline.avg_duration_ms,
                "std_duration_ms": baseline.std_duration_ms,
                "avg_input_tokens": baseline.avg_input_tokens,
                "std_input_tokens": baseline.std_input_tokens,
                "avg_output_tokens": baseline.avg_output_tokens,
                "std_output_tokens": baseline.std_output_tokens,
                "avg_cost": baseline.avg_cost,
                "std_cost": baseline.std_cost,
                "avg_confidence": baseline.avg_confidence,
                "std_confidence": baseline.std_confidence,
                "avg_output_length": baseline.avg_output_length,
                "std_output_length": baseline.std_output_length,
                "tool_failure_rate": baseline.tool_failure_rate,
                "std_tool_failure_rate": baseline.std_tool_failure_rate,
                "sample_count": baseline.sample_count,
                "captured_at": time.time(),
            }),
            ex=86400 * 30,
        )
        return baseline

    async def get_baseline(self, agent_id: str) -> BaselineMetrics:
        """Get the stored baseline for an agent."""
        r = await self._get_redis()
        raw = await r.get(_baseline_key(agent_id))
        if not raw:
            return BaselineMetrics()

        data = json.loads(raw)
        return BaselineMetrics(**{k: data[k] for k in BaselineMetrics.__dataclass_fields__ if k in data})

    def _check_drift(
        self,
        agent_id: str,
        baseline: BaselineMetrics,
        **current_metrics: float,
    ) -> list[DriftAlert]:
        """Compare each current metric against its baseline and fire"""
        alerts = []

        # (current_key, baseline_avg, baseline_std)
        metric_map = [
            ("duration_ms",        baseline.avg_duration_ms,       baseline.std_duration_ms),
            ("input_tokens",       baseline.avg_input_tokens,      baseline.std_input_tokens),
            ("output_tokens",      baseline.avg_output_tokens,     baseline.std_output_tokens),
            ("cost",               baseline.avg_cost,              baseline.std_cost),
            ("confidence",         baseline.avg_confidence,        baseline.std_confidence),
            ("output_length",      baseline.avg_output_length,     baseline.std_output_length),
            ("tool_failure_rate",  baseline.tool_failure_rate,     baseline.std_tool_failure_rate),
        ]

        for metric_name, baseline_value, sigma in metric_map:
            current_value = float(current_metrics.get(metric_name, 0) or 0)
            if baseline_value == 0 and current_value == 0:
                continue
            signed_diff = current_value - baseline_value
            abs_diff = abs(signed_diff)
            # Effective sigma: never zero, at least 1 unit, and at least 10%
            # of baseline so we don't fire on rounding noise.
            eff_sigma = max(sigma, 1.0, 0.10 * max(abs(baseline_value), 1.0))
            sigmas = abs_diff / eff_sigma
            # Signed percent — negative means metric DECREASED from baseline.
            # Without the sign the UI was showing "+38%" for 4311→2675 which
            # is actually a drop. The label and arrow now match reality.
            sign = 1.0 if signed_diff >= 0 else -1.0
            deviation_pct = sign * (abs_diff / max(abs(baseline_value), 1.0)) * 100.0

            severity: str | None = None
            if sigmas >= self._critical_threshold:
                severity = "critical"
            elif sigmas >= self._warning_threshold:
                severity = "warning"

            if severity:
                arrow = "↑" if sign > 0 else "↓"
                alerts.append(DriftAlert(
                    agent_id=agent_id,
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    current_value=current_value,
                    deviation_pct=round(deviation_pct, 1),
                    severity=severity,
                    message=f"{severity.capitalize()} drift: {metric_name} {arrow} "
                            f"{current_value:.2f} vs baseline {baseline_value:.2f} "
                            f"({sigmas:.1f}σ, {deviation_pct:+.1f}%)",
                ))

        return alerts
