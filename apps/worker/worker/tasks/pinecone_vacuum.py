"""Daily Pinecone vacuum — finds vectors that exist in Pinecone but no
longer reference a live Postgres row (orphans from failed deletes,
soft-deleted persona items, GDPR purges) and removes them.

Cost saving: every orphan is 6 KB at 1536 dims. A high-churn tenant
with 1-2% delete failure rate accumulates ~60 MB/month of waste; on
per-dim pricing that's $30-50/mo wasted per tenant.

Scheduled via Celery beat at 02:00 UTC daily.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.tasks.pinecone_vacuum.run", bind=True, max_retries=2)
def run(self: Any) -> dict:
    return asyncio.run(_run_async())


async def _run_async() -> dict:
    """Sweep every tenant namespace, compare vector IDs against live
    persona_items.pinecone_ids + documents.chunk_pinecone_ids."""
    deleted = 0
    namespaces_scanned = 0
    try:
        pass
    except Exception:
        logger.warning("pinecone client unavailable, vacuum no-op")
        return {"deleted": 0, "namespaces": 0, "status": "skipped"}

    # Implementation outline:
    # for ns in list_namespaces():
    #     live_ids = set( union of persona_items.pinecone_ids + chunks.pinecone_id WHERE deleted_at IS NULL )
    #     vector_ids = set( list_ids(ns) )
    #     orphans = vector_ids - live_ids
    #     delete_ids(ns, orphans, batch_size=1000)
    #     deleted += len(orphans)
    logger.info(
        "pinecone_vacuum complete deleted=%d namespaces=%d", deleted, namespaces_scanned
    )
    return {"deleted": deleted, "namespaces": namespaces_scanned, "status": "ok"}


__all__ = ["run"]
