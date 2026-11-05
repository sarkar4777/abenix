"""Build the vector index of a collection that bulk loaded with its index deferred."""

from __future__ import annotations

import logging
import os
from typing import Any

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp

logger = logging.getLogger(__name__)


def build_index(conn: Any, kb_id: str) -> dict[str, Any]:
    """Needs an autocommit connection, CREATE INDEX CONCURRENTLY refuses a transaction."""
    from chunks_store import STATE_SQL, column_base_type, dedicated_hnsw_ddl
    from chunks_store import dedicated_index_name

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (f"kb_index:{kb_id}",),
        )
        if not cur.fetchone()[0]:
            return {"status": "skipped", "kb_id": kb_id, "error": "already building"}
        cur.execute(
            "SELECT index_mode FROM knowledge_collections WHERE id = %s", (kb_id,)
        )
        row = cur.fetchone()
        if not row or row[0] not in ("deferred", "building"):
            return {"status": "skipped", "kb_id": kb_id}
        cur.execute(
            "UPDATE knowledge_collections SET index_mode = 'building' WHERE id = %s",
            (kb_id,),
        )
        cur.execute(STATE_SQL)
        state = cur.fetchone()
        # a parent can not build concurrently, the collection's rows are all in one partition
        cur.execute(
            "SELECT tableoid::regclass::text FROM chunks WHERE collection_id = %s LIMIT 1",
            (kb_id,),
        )
        found = cur.fetchone()
        name = dedicated_index_name(kb_id)
        if not found:
            cur.execute(
                "UPDATE knowledge_collections SET index_mode = 'deferred' WHERE id = %s",
                (kb_id,),
            )
            return {
                "status": "failed",
                "kb_id": kb_id,
                "error": "the collection is empty",
            }
        # unset keeps what the chart sized for this database
        if os.environ.get("KB_INDEX_MAINTENANCE_WORK_MEM"):
            cur.execute(
                "SET maintenance_work_mem = %s",
                (os.environ["KB_INDEX_MAINTENANCE_WORK_MEM"],),
            )
        cur.execute(
            "SET max_parallel_maintenance_workers = %s",
            (int(os.environ.get("KB_INDEX_PARALLEL_WORKERS", "4")),),
        )
        try:
            # a build that died earlier leaves an invalid index that IF NOT EXISTS would keep
            cur.execute(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = %s AND NOT i.indisvalid",
                (name,),
            )
            if cur.fetchone():
                cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            cur.execute(dedicated_hnsw_ddl(kb_id, found[0], column_base_type(state[1])))
        except Exception:
            cur.execute(
                "UPDATE knowledge_collections SET index_mode = 'deferred' WHERE id = %s",
                (kb_id,),
            )
            cur.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            raise
        cur.execute(
            "UPDATE knowledge_collections SET index_mode = 'dedicated' WHERE id = %s",
            (kb_id,),
        )
    return {"status": "built", "kb_id": kb_id, "index": name}


@celery_app.task(
    name="worker.tasks.kb_index.build",
    bind=True,
    max_retries=0,
    soft_time_limit=int(os.environ.get("KB_INDEX_SOFT_LIMIT", "20700")),
    time_limit=int(os.environ.get("KB_INDEX_TIME_LIMIT", "21600")),
)
def build(self: Any, kb_id: str) -> dict[str, Any]:
    import psycopg2

    conn = psycopg2.connect(dp._sync_db_url())
    conn.autocommit = True
    try:
        result = build_index(conn, kb_id)
    finally:
        conn.close()
    logger.info("kb_index %s", result)
    return result
