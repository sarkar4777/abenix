"""Enqueue side of KB re-embedding and the pinecone vacuum.

The work runs in the Celery worker (apps/worker/worker/tasks/kb_reembed.py
and pinecone_vacuum.py) on the `documents` queue, which the general worker
consumes. Re-embed progress is read back from Redis under
`kb_reembed:<kb_id>`, the key the worker writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

QUEUE = "documents"
STATUS_TTL = 7 * 24 * 3600
ACTIVE = ("queued", "running")


def status_key(kb_id: uuid.UUID | str) -> str:
    return f"kb_reembed:{kb_id}"


def _send(name: str, kwargs: dict[str, Any] | None = None, task_id: str | None = None):
    from celery import Celery

    app = Celery(broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/1"))
    return app.send_task(name, kwargs=kwargs or {}, queue=QUEUE, task_id=task_id)


async def _redis():
    import redis.asyncio as aioredis

    from app.core.config import settings

    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def get_status(kb_id: uuid.UUID) -> dict[str, Any] | None:
    try:
        r = await _redis()
        raw = await r.get(status_key(kb_id))
    except Exception as e:
        logger.warning("re-embed status read failed: %s", e)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def enqueue_reembed(
    *, kb_id: uuid.UUID, new_model: str, from_model: str | None = None
) -> uuid.UUID:
    job_id = uuid.uuid4()
    await asyncio.to_thread(
        _send,
        "worker.tasks.kb_reembed.run",
        {"kb_id": str(kb_id), "new_model": new_model, "job_id": str(job_id)},
        str(job_id),
    )
    state = {
        "job_id": str(job_id),
        "kb_id": str(kb_id),
        "status": "queued",
        "from_model": from_model,
        "to_model": new_model,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        r = await _redis()
        await r.set(status_key(kb_id), json.dumps(state), ex=STATUS_TTL)
    except Exception as e:
        logger.warning("re-embed status write failed: %s", e)
    logger.info("queued re-embed kb=%s job=%s model=%s", kb_id, job_id, new_model)
    return job_id


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


__all__ = [
    "enqueue_reembed",
    "enqueue_pinecone_vacuum",
    "get_status",
    "status_key",
    "ACTIVE",
]
