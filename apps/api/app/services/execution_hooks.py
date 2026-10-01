"""Terminal-execution hooks shared by the API execute paths and the queue consumer."""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_ROOT = Path(__file__).resolve().parents[4]
for _p in (_ROOT / "packages" / "db", _ROOT / "apps" / "agent-runtime"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from models.agent import Agent  # noqa: E402
from models.execution import Execution, ExecutionStatus  # noqa: E402

logger = logging.getLogger("abenix.execution_hooks")

TERMINAL_STATUSES = ("completed", "failed")
# How long an execution id stays marked as scored, well past the backlog overlap.
RECORDED_TTL_SECONDS = int(os.environ.get("DRIFT_RECORDED_TTL_SECONDS", "86400"))
BACKLOG_BATCH = int(os.environ.get("DRIFT_SCAN_BATCH", "500"))
WATERMARK_KEY = "drift:backlog:watermark"


def recorded_key(execution_id: Any) -> str:
    return f"drift:recorded:{execution_id}"


def redis_url() -> str:
    try:
        from app.core.config import settings

        return str(settings.redis_url)
    except Exception:
        return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _new_redis() -> Any:
    import redis.asyncio as aioredis

    return aioredis.from_url(redis_url(), decode_responses=True)


@contextlib.asynccontextmanager
async def _redis_client(client: Any) -> AsyncIterator[Any]:
    if client is not None:
        yield client
        return
    r = _new_redis()
    try:
        yield r
    finally:
        with contextlib.suppress(Exception):
            await r.aclose()


@contextlib.asynccontextmanager
async def _session(db_or_factory: Any) -> AsyncIterator[AsyncSession]:
    if hasattr(db_or_factory, "execute"):
        yield db_or_factory
        return
    async with db_or_factory() as db:
        yield db


def _status_of(execution: Any) -> str:
    s = execution.status
    return str(getattr(s, "value", s) or "").lower()


async def drift_enabled(agent: Any, redis: Any = None) -> bool:
    """Three-level toggle, most specific wins: agent config, tenant Redis key, env."""
    if agent is not None:
        cfg = agent.model_config_ or {}
        if cfg.get("drift_detection") is False:
            return False
    if agent is not None and getattr(agent, "tenant_id", None):
        try:
            async with _redis_client(redis) as r:
                raw = await r.get(f"drift:config:enabled:{agent.tenant_id}")
            if raw is not None:
                return raw.strip().lower() not in ("0", "false", "no", "off")
        except Exception:
            pass
    env = (os.environ.get("DRIFT_DETECTION_ENABLED", "true") or "").strip().lower()
    return env not in ("0", "false", "no", "off")


async def persist_drift_alerts(
    db: AsyncSession,
    drift_alerts: list[Any],
    agent: Any,
    execution_id: str,
) -> None:
    """One drift_alerts row per metric that crossed a threshold."""
    if not drift_alerts:
        return
    from models.drift_alert import DriftAlert as DriftAlertRow

    for a in drift_alerts:
        try:
            db.add(
                DriftAlertRow(
                    tenant_id=agent.tenant_id,
                    agent_id=agent.id,
                    execution_id=uuid.UUID(str(execution_id)) if execution_id else None,
                    severity=a.severity,
                    metric=a.metric_name,
                    baseline_value=a.baseline_value,
                    current_value=a.current_value,
                    deviation_pct=a.deviation_pct,
                    acknowledged=False,
                )
            )
        except Exception:
            continue
    try:
        await db.commit()
    except Exception:
        await db.rollback()


def execution_metrics(execution: Any) -> dict[str, Any]:
    """The record_execution kwargs for one terminal row."""
    node_results = (
        execution.node_results if isinstance(execution.node_results, dict) else {}
    )
    tool_calls = execution.tool_calls if isinstance(execution.tool_calls, list) else []
    input_tokens = execution.input_tokens
    output_tokens = execution.output_tokens
    cost = execution.cost
    tool_failures = sum(
        1 for tc in tool_calls if isinstance(tc, dict) and tc.get("is_error")
    )
    total_tool_calls = len(tool_calls)
    if node_results:
        # Pipelines carry their counters per node, the row only has duration
        n_in = n_out = n_fail = n_calls = 0
        n_cost = 0.0
        for nr in node_results.values():
            o = nr.get("output") if isinstance(nr, dict) else None
            if not isinstance(o, dict):
                continue
            n_in += int(o.get("input_tokens", 0) or 0)
            n_out += int(o.get("output_tokens", 0) or 0)
            n_cost += float(o.get("cost", 0) or 0)
            n_calls += int(o.get("tool_calls_count", 1) or 1)
            if nr.get("status") == "failed":
                n_fail += 1
        if input_tokens is None:
            input_tokens = n_in
        if output_tokens is None:
            output_tokens = n_out
        if cost is None:
            cost = n_cost
        tool_failures, total_tool_calls = n_fail, max(n_calls, 1)
    duration = execution.duration_ms
    if duration is None and execution.started_at and execution.completed_at:
        duration = int(
            (execution.completed_at - execution.started_at).total_seconds() * 1000
        )
    confidence = execution.confidence_score
    return {
        "agent_id": str(execution.agent_id),
        "duration_ms": int(duration or 0),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost": float(cost or 0),
        "confidence": float(confidence) if confidence is not None else 1.0,
        "output_length": len(execution.output_message or ""),
        "tool_failures": int(tool_failures),
        "total_tool_calls": int(total_tool_calls),
    }


def _new_detector() -> Any:
    from engine.drift_detection import DriftDetector

    return DriftDetector(redis_url=redis_url())


async def _claim(r: Any, execution_id: Any) -> bool:
    return bool(
        await r.set(recorded_key(execution_id), "1", nx=True, ex=RECORDED_TTL_SECONDS)
    )


async def _record(
    db: AsyncSession, execution: Any, *, detector: Any = None, redis: Any = None
) -> tuple[bool, list[Any]]:
    if _status_of(execution) not in TERMINAL_STATUSES or execution.agent_id is None:
        return False, []
    agent = (
        await db.execute(select(Agent).where(Agent.id == execution.agent_id))
    ).scalar_one_or_none()
    if agent is None:
        return False, []
    async with _redis_client(redis) as r:
        if not await drift_enabled(agent, redis=r):
            return False, []
        if not await _claim(r, execution.id):
            return False, []
        try:
            det = detector if detector is not None else _new_detector()
            alerts = await det.record_execution(**execution_metrics(execution))
        except Exception as exc:
            # Drop the claim so the backlog scan retries this one
            with contextlib.suppress(Exception):
                await r.delete(recorded_key(execution.id))
            logger.warning("drift record failed for %s: %s", execution.id, exc)
            return False, []
    await persist_drift_alerts(db, alerts, agent, str(execution.id))
    return True, alerts


async def record_terminal(
    db_or_session_factory: Any,
    execution_row: Any,
    *,
    detector: Any = None,
    redis: Any = None,
) -> list[Any]:
    """Score one finished execution for drift. Idempotent per execution id."""
    async with _session(db_or_session_factory) as db:
        _, alerts = await _record(db, execution_row, detector=detector, redis=redis)
    return alerts


async def record_terminal_by_id(
    session_factory: Any, execution_id: Any, **kw: Any
) -> list[Any]:
    """Same as record_terminal for callers that only hold the id."""
    async with _session(session_factory) as db:
        row = (
            await db.execute(
                select(Execution).where(Execution.id == uuid.UUID(str(execution_id)))
            )
        ).scalar_one_or_none()
        if row is None:
            return []
        _, alerts = await _record(db, row, **kw)
    return alerts


async def scan_backlog(
    session_factory: Any,
    *,
    interval_seconds: int,
    limit: int = BACKLOG_BATCH,
    redis: Any = None,
    detector: Any = None,
    now: datetime | None = None,
) -> int:
    """Record terminal executions the inline hooks missed since the last scan."""
    now = now or datetime.now(timezone.utc)
    recorded = 0
    async with _redis_client(redis) as r:
        since: datetime | None = None
        with contextlib.suppress(Exception):
            raw = await r.get(WATERMARK_KEY)
            if raw:
                since = datetime.fromisoformat(raw)
        if since is None:
            since = now - timedelta(seconds=2 * interval_seconds)
        # One interval of overlap, the per-execution claim makes it harmless
        since = since - timedelta(seconds=interval_seconds)
        det = detector if detector is not None else _new_detector()
        watermark = now
        async with _session(session_factory) as db:
            rows = (
                (
                    await db.execute(
                        select(Execution)
                        .where(
                            Execution.status.in_(
                                [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]
                            ),
                            Execution.completed_at.isnot(None),
                            Execution.completed_at >= since,
                            Execution.completed_at <= now,
                        )
                        .order_by(Execution.completed_at)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                ok, _ = await _record(db, row, detector=det, redis=r)
                recorded += int(ok)
            # A full batch means more is waiting, pick up from the last row
            if len(rows) >= limit and rows[-1].completed_at:
                watermark = rows[-1].completed_at
        with contextlib.suppress(Exception):
            await r.set(WATERMARK_KEY, watermark.isoformat())
        if detector is None:
            with contextlib.suppress(Exception):
                pool = getattr(det, "_pool", None)
                if pool is not None:
                    await pool.aclose()
    return recorded
