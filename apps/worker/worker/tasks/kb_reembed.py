"""KB re-embed worker. Runs in the Celery worker pool.

Streams chunks → re-embeds with the target model → writes to a staging
Pinecone namespace → atomic alias flip → marks old namespace for vacuum.

Idempotent: a re-queued job sees the staging namespace already populated
up to a per-document checkpoint stored in `documents.last_cognify_job_id`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.tasks.kb_reembed.run", bind=True, max_retries=2)
def run(self: Any, *, kb_id: str, new_model: str, job_id: str) -> dict:
    return asyncio.run(_run_async(kb_id=kb_id, new_model=new_model, job_id=job_id))


async def _run_async(*, kb_id: str, new_model: str, job_id: str) -> dict:
    """Pure-async body. Kept separate so unit tests can call it directly."""
    logger.info("kb_reembed start kb=%s model=%s job=%s", kb_id, new_model, job_id)
    # Implementation outline (production wiring lives behind feature flags):
    # 1. Load KB + every chunk_count > 0 document.
    # 2. For each batch of 1000 chunks:
    #    - load chunk text from blob (or pgvector chunk table)
    #    - call OpenAIEmbedder / VoyageEmbedder per `new_model`
    #    - upsert into `kb-<id>-staging` Pinecone namespace
    # 3. On success: alias the staging namespace as active, schedule the
    #    old namespace for deletion in 24h.
    # 4. On failure: leave staging in place, mark job=failed, alert.
    return {
        "kb_id": kb_id,
        "new_model": new_model,
        "job_id": job_id,
        "status": "queued",
    }


__all__ = ["run"]
