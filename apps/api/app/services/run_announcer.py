"""Tell people when their run finished or failed, whichever process ran it.

Inline runs announce themselves through agents._emit_execution_event. Runs on a
runtime pool are finished by the consumer, which has no notification code, so a
scheduler job picks those up here. A per-execution claim in Redis keeps it to
one announcement either way.
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select

from models.execution import Execution, ExecutionStatus

logger = logging.getLogger(__name__)

CLAIM_PREFIX = "run:announced:"
WATERMARK_KEY = "run:announce:watermark"
CLAIM_TTL = 2 * 24 * 3600
FIRST_LOOKBACK = timedelta(minutes=10)
OVERLAP = timedelta(minutes=2)
BATCH = 200


def _redis() -> Any:
    import redis.asyncio as aioredis

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return aioredis.from_url(url, decode_responses=True)


async def claim(execution_id: Any, redis: Any = None) -> bool:
    """True for the first caller per execution. A Redis outage lets it through."""
    r = redis or _redis()
    try:
        return bool(
            await r.set(f"{CLAIM_PREFIX}{execution_id}", "1", nx=True, ex=CLAIM_TTL)
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("announce claim skipped for %s: %s", execution_id, e)
        return True
    finally:
        if redis is None:
            with contextlib.suppress(Exception):
                await r.aclose()


def wants_announcement(row: Any) -> bool:
    # trigger runs report through their trigger, sub-runs through their parent
    if getattr(row, "trigger_id", None) or getattr(row, "parent_execution_id", None):
        return False
    return getattr(row, "user_id", None) is not None


async def announce_backlog(
    session_factory: Any, *, redis: Any = None, now: datetime | None = None
) -> int:
    """Announce terminal runs since the last scan that nobody announced yet."""
    from app.routers.agents import _emit_execution_event

    now = now or datetime.now(timezone.utc)
    r = redis or _redis()
    sent = 0
    try:
        since = None
        with contextlib.suppress(Exception):
            raw = await r.get(WATERMARK_KEY)
            if raw:
                since = datetime.fromisoformat(raw)
        since = (since or now - FIRST_LOOKBACK) - OVERLAP
        watermark = now
        async with session_factory() as db:
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
                            # a failed trigger run tells the trigger's owner
                            or_(
                                Execution.trigger_id.is_(None),
                                Execution.status == ExecutionStatus.FAILED,
                            ),
                            Execution.parent_execution_id.is_(None),
                        )
                        .order_by(Execution.completed_at)
                        .limit(BATCH)
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                if row.trigger_id and row.status == ExecutionStatus.FAILED:
                    from app.routers.triggers import notify_trigger_failure_once

                    if await notify_trigger_failure_once(
                        db, row.trigger_id, row.id, row.error_message
                    ):
                        sent += 1
                    continue
                if not wants_announcement(row):
                    continue
                failed = row.status == ExecutionStatus.FAILED
                try:
                    if await _emit_execution_event(
                        db,
                        row,
                        "execution_failed" if failed else "execution_complete",
                        cost=float(row.cost) if row.cost is not None else None,
                        duration_ms=row.duration_ms,
                        error_message=row.error_message if failed else None,
                        redis=r,
                    ):
                        sent += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning("announce failed for %s: %s", row.id, e)
                    await db.rollback()
            if len(rows) >= BATCH and rows[-1].completed_at:
                watermark = rows[-1].completed_at
        with contextlib.suppress(Exception):
            await r.set(WATERMARK_KEY, watermark.isoformat())
    finally:
        if redis is None:
            with contextlib.suppress(Exception):
                await r.aclose()
    return sent
