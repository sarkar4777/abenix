"""Postgres and Redis reachability, exported as abenix_health_check for the PostgresDown and RedisDown alerts."""

from __future__ import annotations

import asyncio
import logging
import os

from prometheus_client import REGISTRY, Gauge
from sqlalchemy import text

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0


def _interval() -> float:
    try:
        return max(
            5.0, float(os.environ.get("DEPENDENCY_PROBE_INTERVAL_SECONDS", "30"))
        )
    except ValueError:
        return 30.0


def _gauge() -> Gauge:
    try:
        # mostrecent: with several uvicorn workers the latest probe wins, a dead worker's file never pins it
        return Gauge(
            "abenix_health_check",
            "1 when the API reached the component on its last probe, 0 when it did not",
            ["component"],
            multiprocess_mode="mostrecent",
        )
    except ValueError:
        return REGISTRY._names_to_collectors["abenix_health_check"]  # type: ignore[return-value]


health_check = _gauge()


async def probe_postgres() -> bool:
    from app.core.deps import engine

    async def _ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), PROBE_TIMEOUT_SECONDS)
        return True
    except Exception:
        return False


async def probe_redis() -> bool:
    import redis.asyncio as aioredis

    from app.core.config import settings

    client = aioredis.from_url(
        settings.redis_url,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
    )
    try:
        await asyncio.wait_for(client.ping(), PROBE_TIMEOUT_SECONDS)
        return True
    except Exception:
        return False
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


def record(component: str, ok: bool) -> None:
    health_check.labels(component=component).set(1 if ok else 0)


async def probe_once() -> dict[str, bool]:
    postgres_ok, redis_ok = await asyncio.gather(probe_postgres(), probe_redis())
    record("postgres", postgres_ok)
    record("redis", redis_ok)
    return {"postgres": postgres_ok, "redis": redis_ok}


_task: asyncio.Task | None = None


async def _loop() -> None:
    while True:
        try:
            result = await probe_once()
            down = [name for name, ok in result.items() if not ok]
            if down:
                logger.warning("dependency probe failed: %s", ", ".join(down))
        except Exception:
            logger.exception("dependency probe crashed")
        await asyncio.sleep(_interval())


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
