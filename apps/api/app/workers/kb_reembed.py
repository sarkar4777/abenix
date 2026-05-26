"""Enqueue a KB re-embed job onto the Celery worker. The actual worker
runs in `apps/worker/worker/tasks/kb_reembed.py` and:

  1. Creates a staging Pinecone namespace `kb-<id>-staging`.
  2. Streams chunks 1000 at a time from /data + Postgres metadata.
  3. Re-embeds each batch with the new model.
  4. Writes to staging while live queries still hit the old namespace.
  5. On completion, atomic pointer swap on `knowledge_collections.embedding_model`
     (already done synchronously) + the Pinecone namespace alias.
  6. Marks old namespace `deletable_at = now + 24h` for rollback safety.

This file is just the enqueue side — picks up the celery app and
fires a task.
"""

from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


async def enqueue_reembed(*, kb_id: uuid.UUID, new_model: str) -> uuid.UUID | None:
    try:
        from worker.celery_app import celery_app
    except Exception:
        logger.warning("celery_app unavailable; re-embed not enqueued (kb=%s)", kb_id)
        return None
    job_id = uuid.uuid4()
    celery_app.send_task(
        "worker.tasks.kb_reembed.run",
        kwargs={
            "kb_id": str(kb_id),
            "new_model": new_model,
            "job_id": str(job_id),
        },
    )
    logger.info("queued re-embed kb=%s job=%s model=%s", kb_id, job_id, new_model)
    return job_id


__all__ = ["enqueue_reembed"]
