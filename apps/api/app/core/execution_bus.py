"""Execution event bus — Redis pub/sub with a bounded replay log."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_EVENT_TTL_SECONDS = 3600  # 1h — long enough for a UI to reconnect
_LOG_MAX_LEN = 500         # cap replay log so a chatty executor can't OOM Redis

_pool: aioredis.Redis | None = None


async def _redis() -> aioredis.Redis | None:
    global _pool
    try:
        if _pool is None:
            _pool = aioredis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        await _pool.ping()
        return _pool
    except Exception as e:
        logger.warning("execution_bus: Redis unavailable (%s)", e)
        _pool = None
        return None


def _channel(execution_id: str) -> str:
    return f"exec:events:{execution_id}"


def _log_key(execution_id: str) -> str:
    return f"exec:events:{execution_id}:log"


async def publish_event(execution_id: str, event: dict[str, Any]) -> None:
    """Publish one event. Safe to call from any async context."""
    r = await _redis()
    if r is None:
        return
    payload = json.dumps(event, default=str)
    try:
        pipe = r.pipeline()
        pipe.publish(_channel(execution_id), payload)
        pipe.rpush(_log_key(execution_id), payload)
        pipe.ltrim(_log_key(execution_id), -_LOG_MAX_LEN, -1)
        pipe.expire(_log_key(execution_id), _EVENT_TTL_SECONDS)
        await pipe.execute()
    except Exception as e:
        logger.warning("execution_bus.publish_event failed: %s", e)


async def subscribe_events(
    execution_id: str,
    *,
    include_replay: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Yield events for an execution. Yields replayed events first (if"""
    r = await _redis()
    if r is None:
        return

    # 1. Replay
    if include_replay:
        try:
            backlog = await r.lrange(_log_key(execution_id), 0, -1)
            for raw in backlog:
                try:
                    yield json.loads(raw)
                except Exception:
                    continue
        except Exception as e:
            logger.debug("execution_bus replay failed: %s", e)

    # 2. Live subscription
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(_channel(execution_id))
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            raw = msg.get("data")
            if not raw:
                continue
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            yield evt
            # Terminal — the consumer has signalled end-of-stream.
            if evt.get("event") in ("done", "error"):
                return
    finally:
        try:
            await pubsub.unsubscribe(_channel(execution_id))
            await pubsub.close()
        except Exception:
            pass


__all__ = ["publish_event", "subscribe_events"]
