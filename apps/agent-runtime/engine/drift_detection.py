"""Drift Detection — monitors agent behavior for deviations from baseline."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, fields
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Metrics compared on every execution, in the order they are reported.
METRIC_NAMES: tuple[str, ...] = (
    "duration_ms",
    "input_tokens",
    "output_tokens",
    "cost",
    "confidence",
    "output_length",
    "tool_failure_rate",
)

# Smallest sigma we accept per metric. Keeps rounding noise from firing
# without an absolute floor that would mute 0..1 metrics or small costs.
METRIC_EPS: dict[str, float] = {
    "duration_ms": 50.0,
    "input_tokens": 20.0,
    "output_tokens": 20.0,
    "cost": 0.0005,
    "confidence": 0.02,
    "output_length": 20.0,
    "tool_failure_rate": 0.02,
}

# Relative floor on sigma as a fraction of the baseline mean.
RELATIVE_SIGMA_FLOOR = 0.10

# How many recorded samples between baseline refreshes.
DEFAULT_REFRESH_EVERY = 10
# Blend weight for the fresh window when refreshing from Redis.
DEFAULT_EMA_ALPHA = 0.3
# Prior window the DB path averages over.
DEFAULT_DB_WINDOW_DAYS = 7
MIN_BASELINE_SAMPLES = 10


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
    captured_at: float = 0.0
    source: str = ""  # "redis" | "db" | "ema"

    def avg_of(self, metric: str) -> float:
        if metric == "tool_failure_rate":
            return self.tool_failure_rate
        return float(getattr(self, f"avg_{metric}"))

    def std_of(self, metric: str) -> float:
        return float(getattr(self, f"std_{metric}"))

    def set_metric(self, metric: str, avg: float, std: float) -> None:
        if metric == "tool_failure_rate":
            self.tool_failure_rate = avg
        else:
            setattr(self, f"avg_{metric}", avg)
        setattr(self, f"std_{metric}", std)

    def to_json(self) -> str:
        return json.dumps({f.name: getattr(self, f.name) for f in fields(self)})

    @classmethod
    def from_json(cls, raw: str) -> "BaselineMetrics":
        data = json.loads(raw)
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


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


def _refresh_counter_key(agent_id: str) -> str:
    return f"drift:baseline:since_refresh:{agent_id}"


def effective_sigma(metric: str, sigma: float, baseline_value: float) -> float:
    """Sigma floored relative to the baseline, never by an absolute unit."""
    eps = METRIC_EPS.get(metric, 1e-9)
    return max(float(sigma), RELATIVE_SIGMA_FLOOR * abs(baseline_value), eps)


def _avg_std(vals: list[float]) -> tuple[float, float]:
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    avg = sum(vals) / n
    var = sum((v - avg) ** 2 for v in vals) / n
    return avg, math.sqrt(var)


def blend_baselines(
    old: BaselineMetrics, fresh: BaselineMetrics, alpha: float
) -> BaselineMetrics:
    """Exponential moving average of two baselines, weight alpha on fresh."""
    alpha = max(0.0, min(1.0, alpha))
    out = BaselineMetrics(
        sample_count=fresh.sample_count,
        captured_at=time.time(),
        source="ema",
    )
    for m in METRIC_NAMES:
        avg = (1 - alpha) * old.avg_of(m) + alpha * fresh.avg_of(m)
        std = (1 - alpha) * old.std_of(m) + alpha * fresh.std_of(m)
        out.set_metric(m, avg, std)
    return out


class DriftDetector:
    """Tracks agent execution metrics and detects drift from baseline.

    The baseline is rolling. Every `refresh_every` recorded samples it is
    recomputed: from the executions table over the prior `db_window_days`
    when a DB url is available, otherwise from the Redis recent window
    blended into the old baseline with an EMA.
    """

    def __init__(
        self,
        redis_url: str,
        warning_threshold: float = 2.0,
        critical_threshold: float = 3.0,
        db_url: str | None = None,
        refresh_every: int = DEFAULT_REFRESH_EVERY,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
        db_window_days: int = DEFAULT_DB_WINDOW_DAYS,
    ):
        self._redis_url = redis_url
        self._warning_threshold = warning_threshold
        self._critical_threshold = critical_threshold
        self._db_url = (
            db_url if db_url is not None else os.environ.get("DATABASE_URL", "")
        )
        self._refresh_every = max(1, int(refresh_every))
        self._ema_alpha = ema_alpha
        self._db_window_days = max(1, int(db_window_days))
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

        tool_failure_rate = tool_failures / max(total_tool_calls, 1)
        metric = json.dumps(
            {
                "duration_ms": duration_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": cost,
                "confidence": confidence,
                "output_length": output_length,
                "tool_failure_rate": tool_failure_rate,
                "timestamp": time.time(),
            }
        )
        key = _recent_key(agent_id)
        pipe = r.pipeline()
        pipe.lpush(key, metric)
        pipe.ltrim(key, 0, 99)  # Keep last 100
        pipe.expire(key, 86400 * 7)  # 7 days
        pipe.incr(_refresh_counter_key(agent_id))
        pipe.expire(_refresh_counter_key(agent_id), 86400 * 30)
        res = await pipe.execute()
        since_refresh = int(res[3] or 0) if len(res) > 3 else 0

        baseline = await self.get_baseline(agent_id)
        if baseline.sample_count == 0:
            window_len = await r.llen(key)
            if window_len >= MIN_BASELINE_SAMPLES:
                baseline = await self.capture_baseline(agent_id)
                await r.set(_refresh_counter_key(agent_id), 0)
        elif since_refresh >= self._refresh_every:
            baseline = await self.refresh_baseline(agent_id, baseline)
            await r.set(_refresh_counter_key(agent_id), 0)
        if baseline.sample_count < MIN_BASELINE_SAMPLES:
            return []  # Not enough data for baseline

        return self._check_drift(
            agent_id,
            baseline,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            confidence=confidence,
            output_length=output_length,
            tool_failure_rate=tool_failure_rate,
        )

    async def _window_baseline(self, agent_id: str) -> BaselineMetrics:
        """Baseline computed from the Redis recent window, not stored."""
        r = await self._get_redis()
        raw_entries = await r.lrange(_recent_key(agent_id), 0, -1)
        if not raw_entries:
            return BaselineMetrics()
        entries = [json.loads(e) for e in raw_entries]
        baseline = BaselineMetrics(
            sample_count=len(entries), captured_at=time.time(), source="redis"
        )
        for m in METRIC_NAMES:
            avg, std = _avg_std([float(e.get(m, 0) or 0) for e in entries])
            baseline.set_metric(m, avg, std)
        return baseline

    async def _store_baseline(self, agent_id: str, baseline: BaselineMetrics) -> None:
        r = await self._get_redis()
        await r.set(_baseline_key(agent_id), baseline.to_json(), ex=86400 * 30)

    async def capture_baseline(self, agent_id: str) -> BaselineMetrics:
        """Capture a baseline from the Redis recent window and store it."""
        baseline = await self._window_baseline(agent_id)
        if baseline.sample_count == 0:
            return baseline
        await self._store_baseline(agent_id, baseline)
        return baseline

    async def refresh_baseline(
        self, agent_id: str, current: BaselineMetrics | None = None
    ) -> BaselineMetrics:
        """Recompute the rolling baseline. DB window first, Redis EMA second."""
        current = current or await self.get_baseline(agent_id)
        fresh = await self._baseline_from_db(agent_id)
        if fresh is None or fresh.sample_count < MIN_BASELINE_SAMPLES:
            window = await self._window_baseline(agent_id)
            if window.sample_count == 0:
                return current
            fresh = (
                blend_baselines(current, window, self._ema_alpha)
                if current.sample_count
                else window
            )
        await self._store_baseline(agent_id, fresh)
        return fresh

    async def _baseline_from_db(self, agent_id: str) -> BaselineMetrics | None:
        """Mean and population std dev over completed executions in the prior
        window. tool_failure_rate is not on the executions table so it keeps
        the Redis window value. Returns None when the DB path is unusable."""
        if not self._db_url:
            return None
        try:
            import asyncpg

            from engine.healing import _to_asyncpg_dsn
        except ImportError:
            return None
        try:
            agent_uuid = UUID(str(agent_id))
        except ValueError:
            return None
        conn = None
        try:
            clean, kwargs = _to_asyncpg_dsn(self._db_url)
            conn = await asyncpg.connect(clean, **kwargs)
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n,
                       AVG(duration_ms) AS avg_duration_ms,
                       STDDEV_POP(duration_ms) AS std_duration_ms,
                       AVG(input_tokens) AS avg_input_tokens,
                       STDDEV_POP(input_tokens) AS std_input_tokens,
                       AVG(output_tokens) AS avg_output_tokens,
                       STDDEV_POP(output_tokens) AS std_output_tokens,
                       AVG(cost) AS avg_cost,
                       STDDEV_POP(cost) AS std_cost,
                       AVG(confidence_score) AS avg_confidence,
                       STDDEV_POP(confidence_score) AS std_confidence,
                       AVG(LENGTH(COALESCE(output_message, ''))) AS avg_output_length,
                       STDDEV_POP(LENGTH(COALESCE(output_message, '')))
                           AS std_output_length
                FROM executions
                WHERE agent_id = $1
                  AND LOWER(status::text) = 'completed'
                  AND created_at >= NOW() - ($2::int * INTERVAL '1 day')
                """,
                agent_uuid,
                self._db_window_days,
            )
        except Exception as e:
            logger.debug("drift baseline db path unavailable: %s", e)
            return None
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
        if not row or int(row["n"] or 0) < MIN_BASELINE_SAMPLES:
            return None

        def _f(key: str) -> float:
            v = row[key]
            return float(v) if v is not None else 0.0

        baseline = BaselineMetrics(
            sample_count=int(row["n"]), captured_at=time.time(), source="db"
        )
        for m in METRIC_NAMES:
            if m == "tool_failure_rate":
                continue
            baseline.set_metric(m, _f(f"avg_{m}"), _f(f"std_{m}"))
        window = await self._window_baseline(agent_id)
        baseline.set_metric(
            "tool_failure_rate",
            window.tool_failure_rate,
            window.std_tool_failure_rate,
        )
        return baseline

    async def get_baseline(self, agent_id: str) -> BaselineMetrics:
        """Get the stored baseline for an agent."""
        r = await self._get_redis()
        raw = await r.get(_baseline_key(agent_id))
        if not raw:
            return BaselineMetrics()
        try:
            return BaselineMetrics.from_json(raw)
        except Exception:
            return BaselineMetrics()

    def _check_drift(
        self,
        agent_id: str,
        baseline: BaselineMetrics,
        **current_metrics: Any,
    ) -> list[DriftAlert]:
        """Compare each current metric against its baseline and fire"""
        alerts = []

        for metric_name in METRIC_NAMES:
            baseline_value = baseline.avg_of(metric_name)
            sigma = baseline.std_of(metric_name)
            current_value = float(current_metrics.get(metric_name, 0) or 0)
            if baseline_value == 0 and current_value == 0:
                continue
            signed_diff = current_value - baseline_value
            abs_diff = abs(signed_diff)
            eff_sigma = effective_sigma(metric_name, sigma, baseline_value)
            sigmas = abs_diff / eff_sigma
            # Signed percent — negative means the metric dropped.
            sign = 1.0 if signed_diff >= 0 else -1.0
            denom = max(abs(baseline_value), METRIC_EPS.get(metric_name, 1e-9))
            deviation_pct = sign * (abs_diff / denom) * 100.0

            severity: str | None = None
            if sigmas >= self._critical_threshold:
                severity = "critical"
            elif sigmas >= self._warning_threshold:
                severity = "warning"

            if severity:
                arrow = "↑" if sign > 0 else "↓"
                alerts.append(
                    DriftAlert(
                        agent_id=agent_id,
                        metric_name=metric_name,
                        baseline_value=baseline_value,
                        current_value=current_value,
                        deviation_pct=round(deviation_pct, 1),
                        severity=severity,
                        message=f"{severity.capitalize()} drift: {metric_name} {arrow} "
                        f"{current_value:.4g} vs baseline {baseline_value:.4g} "
                        f"({sigmas:.1f}σ, {deviation_pct:+.1f}%)",
                    )
                )

        return alerts
