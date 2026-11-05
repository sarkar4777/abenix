"""Enqueue side of the pinecone vacuum, re-embed lives in services/kb_lifecycle.py."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

QUEUE = "documents"


def _send(name: str, kwargs: dict[str, Any] | None = None, task_id: str | None = None):
    from celery import Celery

    app = Celery(broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1"))
    return app.send_task(name, kwargs=kwargs or {}, queue=QUEUE, task_id=task_id)


async def _redis():
    import redis.asyncio as aioredis

    from app.core.config import settings

    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def enqueue_pinecone_vacuum() -> bool:
    """Enqueue at most once per 20 hours across replicas."""
    try:
        r = await _redis()
        if not await r.set("pinecone_vacuum:enqueued", "1", nx=True, ex=72000):
            return False
    except Exception as e:
        logger.warning("pinecone vacuum dedupe unavailable: %s", e)
    await asyncio.to_thread(_send, "worker.tasks.pinecone_vacuum.run")
    return True


__all__ = ["enqueue_pinecone_vacuum"]
