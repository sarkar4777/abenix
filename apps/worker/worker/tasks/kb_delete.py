"""Delete a tombstoned knowledge collection in the background, in batches.

The API sets deleted_at and answers at once, search stops at that moment. Here
each phase is repeatable, so a crash or a Neo4j outage only delays the end. The
collection row goes last, kb_delete_jobs stays behind as the receipt.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp

logger = logging.getLogger(__name__)

TASK_NAME = "worker.tasks.kb_delete.run"
CHUNK_BATCH = int(os.environ.get("KB_DELETE_CHUNK_BATCH", "5000"))
DOCUMENT_BATCH = int(os.environ.get("KB_DELETE_DOCUMENT_BATCH", "500"))
SLICE_SECONDS = int(os.environ.get("KB_DELETE_SLICE_SECONDS", "600"))
PHASES = ("graph", "vectors", "chunks", "documents", "rows", "collection")
# deleted before anything else that may point at them
_FIRST = ("graph_relationships",)


class GraphUnavailable(Exception):
    pass


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def remove_file(uri: str) -> bool:
    """Every kind of storage URL the platform writes, agent:// has no file behind it."""
    if not uri or uri.startswith("agent://"):
        return False
    from engine.storage import get_storage

    return bool(_run(get_storage().delete(uri)))


def _delete_graph(cur: Any, kb_id: str) -> int:
    from engine.knowledge.graph_writer import delete_kb_graph
    from engine.knowledge.neo4j_client import is_neo4j_available

    async def go() -> tuple[bool, int]:
        if not await is_neo4j_available():
            return False, 0
        return True, int((await delete_kb_graph(kb_id)).get("entities_deleted", 0))

    reachable, deleted = _run(go())
    if reachable:
        return deleted
    cur.execute("SELECT 1 FROM graph_entities WHERE kb_id = %s LIMIT 1", (kb_id,))
    if cur.fetchone():
        raise GraphUnavailable(
            "Neo4j is unreachable and this collection has entities in it, "
            "the delete carries on when it is back"
        )
    return 0


def _delete_vectors(cur: Any, kb_id: str, generation: int) -> None:
    if not dp.PINECONE_API_KEY:
        return
    from engine.knowledge.kb_state import pinecone_namespace
    from pinecone import Pinecone

    cur.execute(
        "SELECT target_generation FROM kb_reembed_jobs WHERE kb_id = %s", (kb_id,)
    )
    generations = {0, generation, *(r[0] for r in cur.fetchall())}
    index = Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)
    for g in sorted(generations):
        try:
            index.delete(delete_all=True, namespace=pinecone_namespace(kb_id, g))
        except Exception as e:
            # an absent namespace raises, the daily vacuum drops any orphan left
            logger.info("kb delete: namespace %s generation %s: %s", kb_id, g, e)


def _references(cur: Any, target: str) -> list[tuple[str, str, bool]]:
    """Foreign keys with no ON DELETE rule, new tables are covered without a change here."""
    cur.execute(
        "SELECT c.conrelid::regclass::text, a.attname, a.attnotnull "
        "FROM pg_constraint c JOIN pg_attribute a "
        "ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
        "WHERE c.contype = 'f' AND c.confdeltype = 'a' "
        "AND c.confrelid = to_regclass(%s) ORDER BY 1",
        (target,),
    )
    return [(r[0], r[1], bool(r[2])) for r in cur.fetchall()]


def delete_document_rows(cur: Any, kb_id: str, ids: list[str]) -> None:
    """Chunks, grants and rows that point at these documents, the caller commits."""
    cur.execute(
        "DELETE FROM chunks WHERE collection_id = %s AND document_id = ANY(%s::uuid[])",
        (kb_id, ids),
    )
    cur.execute(
        "DELETE FROM document_grants WHERE document_id = ANY(%s::uuid[])", (ids,)
    )
    for table in ("cognify_chunks", "cognify_job_documents"):
        cur.execute(f"DELETE FROM {table} WHERE document_id = ANY(%s::uuid[])", (ids,))
    for table, column, required in _references(cur, "documents"):
        if required:
            cur.execute(f"DELETE FROM {table} WHERE {column} = ANY(%s::uuid[])", (ids,))
        else:
            cur.execute(
                f"UPDATE {table} SET {column} = NULL WHERE {column} = ANY(%s::uuid[])",
                (ids,),
            )
    cur.execute("DELETE FROM documents WHERE id = ANY(%s::uuid[])", (ids,))


def live_target_generations(cur: Any, kb_id: str) -> list[int]:
    """A running re-embed staged this document too, it would come back at the flip."""
    cur.execute(
        "SELECT target_generation FROM kb_reembed_jobs WHERE kb_id = %s "
        "AND finished_at IS NULL",
        (kb_id,),
    )
    return [r[0] for r in cur.fetchall()]


def remove_document_vectors(
    kb_id: str,
    doc_id: str,
    count: int,
    generation: int,
    backend: str,
    also: list[int] | tuple[int, ...] = (),
) -> None:
    if backend == "pgvector" or not dp.PINECONE_API_KEY:
        return
    from engine.knowledge.kb_state import pinecone_namespace
    from pinecone import Pinecone

    index = Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)
    for g in sorted({generation, *also}):
        namespace = pinecone_namespace(kb_id, g)
        ids = {f"{doc_id}_{i}" for i in range(count)}
        try:
            for page in index.list(prefix=f"{doc_id}_", namespace=namespace):
                ids.update(page if isinstance(page, (list, tuple)) else [page])
        except Exception as e:
            logger.info("cannot list namespace %s, using the count: %s", namespace, e)
        ordered = sorted(ids)
        for i in range(0, len(ordered), 1000):
            index.delete(ids=ordered[i : i + 1000], namespace=namespace)


def delete_slice(
    job_id: str,
    slice_seconds: float | None = None,
    requeue: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    import psycopg2

    conn = psycopg2.connect(dp._sync_db_url())
    deadline = time.monotonic() + (
        SLICE_SECONDS if slice_seconds is None else slice_seconds
    )
    requeue = requeue or _again
    lock = None
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT kb_id::text, status, phase FROM kb_delete_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:
            return {"status": "missing", "job_id": job_id}
        kb_id, status, phase = row
        if status == "completed":
            return {"status": "completed", "job_id": job_id}
        lock = psycopg2.connect(dp._sync_db_url())
        lock.autocommit = True
        with lock.cursor() as lc:
            lc.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))", (f"kb_delete:{kb_id}",)
            )
            if not lc.fetchone()[0]:
                return {"status": "skipped", "job_id": job_id}

        def beat(**columns: Any) -> None:
            sets = ["heartbeat_at = now()", "updated_at = now()"]
            sets += [
                f"{k} = {k} + %s" if isinstance(v, int) else f"{k} = %s"
                for k, v in columns.items()
            ]
            cur.execute(
                f"UPDATE kb_delete_jobs SET {', '.join(sets)} WHERE id = %s",
                (*columns.values(), job_id),
            )
            conn.commit()

        beat(status="running", error=None)
        start = PHASES.index(phase) if phase in PHASES else 0
        for current in PHASES[start:]:
            beat(phase=current)
            if not _run_phase(conn, cur, kb_id, current, beat, deadline):
                requeue(job_id)
                return {"status": "continuing", "job_id": job_id, "phase": current}
        cur.execute(
            "UPDATE kb_delete_jobs SET status = 'completed', phase = 'done', "
            "finished_at = now(), updated_at = now() WHERE id = %s",
            (job_id,),
        )
        conn.commit()
        return {"status": "completed", "job_id": job_id, "kb_id": kb_id}
    except GraphUnavailable as e:
        conn.rollback()
        with conn.cursor() as c2:
            c2.execute(
                "UPDATE kb_delete_jobs SET status = 'waiting', error = %s, "
                "heartbeat_at = now(), updated_at = now() WHERE id = %s",
                (str(e), job_id),
            )
        conn.commit()
        return {"status": "waiting", "job_id": job_id, "error": str(e)}
    except Exception as e:
        conn.rollback()
        logger.exception("kb delete failed job=%s", job_id)
        with conn.cursor() as c2:
            c2.execute(
                "UPDATE kb_delete_jobs SET status = 'failed', error = %s, "
                "updated_at = now() WHERE id = %s",
                (str(e)[:500], job_id),
            )
        conn.commit()
        return {"status": "failed", "job_id": job_id, "error": str(e)}
    finally:
        conn.close()
        if lock is not None:
            lock.close()


def _run_phase(
    conn: Any, cur: Any, kb_id: str, phase: str, beat: Callable, deadline: float
) -> bool:
    """True when the phase finished, False when the slice ran out first."""
    if phase == "graph":
        beat(entities_deleted=_delete_graph(cur, kb_id))
        return True
    if phase == "vectors":
        cur.execute(
            "SELECT embedding_generation FROM knowledge_collections WHERE id = %s",
            (kb_id,),
        )
        row = cur.fetchone()
        conn.commit()
        _delete_vectors(cur, kb_id, row[0] if row else 0)
        conn.commit()
        return True
    if phase == "chunks":
        while True:
            cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND id IN ("
                "SELECT id FROM chunks WHERE collection_id = %s LIMIT %s)",
                (kb_id, kb_id, CHUNK_BATCH),
            )
            removed = cur.rowcount
            beat(chunks_deleted=removed)
            if removed == 0:
                return True
            if time.monotonic() >= deadline:
                return False
    if phase == "documents":
        while True:
            cur.execute(
                "SELECT id::text, storage_url FROM documents WHERE kb_id = %s LIMIT %s",
                (kb_id, DOCUMENT_BATCH),
            )
            rows = cur.fetchall()
            conn.commit()
            if not rows:
                return True
            files = sum(1 for _i, url in rows if remove_file(url or ""))
            ids = [r[0] for r in rows]
            delete_document_rows(cur, kb_id, ids)
            beat(documents_deleted=len(ids), files_deleted=files)
            if time.monotonic() >= deadline:
                return False
    if phase == "rows":
        refs = sorted(
            _references(cur, "knowledge_collections"),
            key=lambda r: (r[0] not in _FIRST, r[0]),
        )
        for table, column, required in refs:
            if table == "documents":
                continue
            if not required:
                cur.execute(
                    f"UPDATE {table} SET {column} = NULL WHERE {column} = %s", (kb_id,)
                )
                conn.commit()
                continue
            while True:
                cur.execute(
                    f"DELETE FROM {table} WHERE ctid = ANY(ARRAY(SELECT ctid "
                    f"FROM {table} WHERE {column} = %s LIMIT %s))",
                    (kb_id, CHUNK_BATCH),
                )
                removed = cur.rowcount
                beat()
                if removed == 0:
                    break
                if time.monotonic() >= deadline:
                    return False
        return True
    if phase == "collection":
        from chunks_store import dedicated_index_name

        cur.execute("DELETE FROM knowledge_collections WHERE id = %s", (kb_id,))
        cur.execute(f"DROP INDEX IF EXISTS {dedicated_index_name(kb_id)}")
        conn.commit()
        return True
    raise ValueError(f"unknown phase {phase}")


def _again(job_id: str) -> None:
    celery_app.send_task(TASK_NAME, kwargs={"job_id": job_id}, queue="documents")


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    max_retries=0,
    soft_time_limit=int(os.environ.get("KB_DELETE_SOFT_LIMIT", "1500")),
    time_limit=int(os.environ.get("KB_DELETE_TIME_LIMIT", "1800")),
)
def run(self: Any, *, job_id: str) -> dict:
    return delete_slice(job_id)


__all__ = ["run", "delete_slice", "remove_file", "TASK_NAME", "PHASES"]
