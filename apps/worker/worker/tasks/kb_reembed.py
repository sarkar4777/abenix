"""Re-embed a knowledge collection with another embedding model, for any size.

A job works in slices. Each slice stages whole documents, one small transaction
per embedding batch, into rows or a Pinecone namespace that no query reads, then
hands over to the next slice, so no task limit bounds the corpus. Pausing, a
crash or a provider outage loses at most the document in hand. The flip is one
row update on the collection, so queries move in one step however many chunks
there are. Old vectors are removed in batches after it.

State lives in kb_reembed_jobs, the API and the scheduler read it there.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any, Callable

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp

logger = logging.getLogger(__name__)

EMBED_BATCH = 100
DELETE_BATCH = int(os.environ.get("KB_REEMBED_DELETE_BATCH", "5000"))
DOCUMENT_BATCH = 20
SLICE_SECONDS = int(os.environ.get("KB_REEMBED_SLICE_SECONDS", "600"))
TASK_NAME = "worker.tasks.kb_reembed.run"
# metadata the pipeline writes itself, anything else came from the document's owner
_OWN_KEYS = {
    "filename",
    "chunk_index",
    "text_preview",
    "page",
    "kb_id",
    "doc_id",
    "text",
}


class ReembedError(Exception):
    pass


class _Hold(Exception):
    """Stop this slice and leave the job in the given state."""

    def __init__(self, status: str, message: str | None = None) -> None:
        super().__init__(message or status)
        self.status = status
        self.message = message


def _carried(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items() if k not in _OWN_KEYS}


def _stored_chunks_pgvector(
    cur: Any, kb_id: str, doc_id: str, generation: int
) -> tuple[list[str], list[int | None], dict[str, Any]]:
    cur.execute(
        "SELECT content, metadata FROM chunks WHERE collection_id = %s "
        "AND document_id = %s AND embedding_generation = %s ORDER BY chunk_index",
        (kb_id, doc_id, generation),
    )
    rows = [r for r in cur.fetchall() if r[0]]
    pages = [(r[1] or {}).get("page") if isinstance(r[1], dict) else None for r in rows]
    return [r[0] for r in rows], pages, _carried(rows[0][1]) if rows else {}


def _stored_chunks_pinecone(
    index: Any, namespace: str, doc_id: str, count: int
) -> tuple[list[str], list[int | None], dict[str, Any]]:
    texts: list[str] = []
    pages: list[int | None] = []
    carried: dict[str, Any] = {}
    ids = [f"{doc_id}_{i}" for i in range(count)]
    for i in range(0, len(ids), 500):
        resp = index.fetch(ids=ids[i : i + 500], namespace=namespace)
        vectors = getattr(resp, "vectors", None) or (
            resp.get("vectors", {}) if isinstance(resp, dict) else {}
        )
        for vid in ids[i : i + 500]:
            v = vectors.get(vid)
            if v is None:
                continue
            meta = getattr(v, "metadata", None) or (
                v.get("metadata", {}) if isinstance(v, dict) else {}
            )
            if meta.get("text"):
                carried = carried or _carried(meta)
                texts.append(meta["text"])
                pages.append(meta.get("page"))
    return texts, pages, carried


def _stage_loose_vectors(
    index: Any, source_ns: str, target_ns: str, doc_ids: set[str], new_model: str
) -> int:
    """Vectors with no documents row (knowledge_store writes these) get the new model too."""
    try:
        ids = [
            vid
            for page in index.list(namespace=source_ns)
            for vid in (page if isinstance(page, (list, tuple)) else [page])
            if vid.rsplit("_", 1)[0] not in doc_ids
        ]
    except Exception as e:
        # pod-based indexes cannot list ids
        logger.warning("re-embed: cannot list namespace %s (%s)", source_ns, e)
        return -1
    staged = 0
    for i in range(0, len(ids), EMBED_BATCH):
        part = ids[i : i + EMBED_BATCH]
        resp = index.fetch(ids=part, namespace=source_ns)
        vectors = getattr(resp, "vectors", None) or (
            resp.get("vectors", {}) if isinstance(resp, dict) else {}
        )
        rows = []
        for vid in part:
            v = vectors.get(vid)
            meta = (getattr(v, "metadata", None) or {}) if v is not None else {}
            if meta.get("text"):
                rows.append((vid, dict(meta)))
        if not rows:
            continue
        embedded, _real = dp._embed_chunks(
            [m["text"] for _vid, m in rows], new_model, strict=True
        )
        index.upsert(
            vectors=[
                {"id": vid, "values": vec, "metadata": meta}
                for (vid, meta), vec in zip(rows, embedded)
            ],
            namespace=target_ns,
        )
        staged += len(rows)
    return staged


def _document_chunks(
    doc: dict[str, Any],
    kb: dict[str, Any],
    stored: Callable[[], tuple[list[str], list[int | None], dict[str, Any]]],
) -> tuple[list[str], list[int | None], dict[str, Any], str]:
    """Re-extract and re-chunk the file, or fall back to the indexed chunk text."""
    tmp = None
    try:
        local, tmp = dp._local_path(doc["storage_url"] or "", doc["file_type"] or "")
        blocks, _method, _quality = dp._extract_blocks(local, doc["file_type"] or "")
        if blocks:
            chunks, pages = dp._chunk_blocks(
                blocks, kb["chunk_size"] or 1000, kb["chunk_overlap"] or 200
            )
            if chunks:
                return chunks, pages, stored()[2], "file"
    except Exception as e:
        logger.info(
            "re-embed: %s not re-extractable (%s), using indexed text", doc["id"], e
        )
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    chunks, pages, carried = stored()
    return chunks, pages, carried, "indexed"


_DOC_COLUMNS = "d.id::text, d.filename, d.file_type, d.storage_url, d.chunk_count"


def _doc(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "filename": row[1],
        "file_type": row[2],
        "storage_url": row[3],
        "chunk_count": row[4] or 0,
    }


def _next_documents(cur: Any, kb_id: str, job_id: str, limit: int) -> list[dict]:
    """Documents with nothing staged yet, so one that arrives mid job is picked up too."""
    cur.execute(
        f"SELECT {_DOC_COLUMNS} FROM documents d "
        "WHERE d.kb_id = %s AND d.status IN ('READY', 'DEGRADED') "
        "AND NOT EXISTS (SELECT 1 FROM kb_reembed_documents s "
        "WHERE s.job_id = %s AND s.document_id = d.id) "
        "ORDER BY d.created_at, d.id LIMIT %s",
        (kb_id, job_id, limit),
    )
    return [_doc(r) for r in cur.fetchall()]


class _Job:
    """One slice of work, holding the connection it commits on."""

    def __init__(self, conn: Any, row: dict[str, Any], kb: dict[str, Any]) -> None:
        self.conn = conn
        self.cur = conn.cursor()
        self.row = row
        self.kb = kb
        self.id = row["id"]
        self.kb_id = row["kb_id"]
        self.target = row["target_generation"]
        self.source = kb["generation"]
        self.index: Any = None
        if kb["backend"] != "pgvector":
            if not dp.PINECONE_API_KEY:
                raise ReembedError(
                    "this collection stores vectors in Pinecone but PINECONE_API_KEY is not set"
                )
            self.index = _pinecone_index()

    def beat(self, **columns: Any) -> None:
        sets = ["heartbeat_at = now()", "updated_at = now()"]
        sets += [f"{k} = %s" for k in columns]
        self.cur.execute(
            f"UPDATE kb_reembed_jobs SET {', '.join(sets)} WHERE id = %s",
            (*columns.values(), self.id),
        )
        self.conn.commit()

    def requested_status(self) -> str:
        self.cur.execute("SELECT status FROM kb_reembed_jobs WHERE id = %s", (self.id,))
        row = self.cur.fetchone()
        self.conn.commit()
        return row[0] if row else "cancelled"

    def namespace(self, generation: int) -> str:
        from engine.knowledge.kb_state import pinecone_namespace

        return pinecone_namespace(self.kb_id, generation)

    def _spend_check(self, part: list[str]) -> float:
        import embedding_models as em
        import knowledge_quota as kq

        from worker.tasks import kb_quota

        tokens, usd = em.estimated_cost(self.row["to_model"], part)
        try:
            kb_quota.enforce(self.cur, self.row["tenant_id"], add_embedding_usd=usd)
        except kq.KnowledgeQuotaExceeded as e:
            self.conn.rollback()
            raise _Hold("paused", e.message) from e
        kb_quota.record_spend(
            self.cur, self.row["tenant_id"], embedding_usd=usd, embedding_tokens=tokens
        )
        self.conn.commit()
        return usd

    def _write_rows(
        self,
        doc: dict[str, Any],
        start: int,
        part: list[str],
        vectors: list[list[float]],
        pages: list[int | None],
        carried: dict[str, Any],
    ) -> None:
        if self.index is not None:
            batch = []
            for j, (text, vec) in enumerate(zip(part, vectors)):
                v = dp._pinecone_vector(
                    self.kb_id,
                    doc["id"],
                    doc["filename"],
                    start + j,
                    text,
                    vec,
                    pages,
                )
                v["metadata"] = {**carried, **v["metadata"]}
                batch.append(v)
            self.index.upsert(vectors=batch, namespace=self.namespace(self.target))
            return
        from psycopg2.extras import execute_values

        rows = []
        for j, (text, vec) in enumerate(zip(part, vectors)):
            i = start + j
            meta = {**carried, **dp._chunk_meta(doc["filename"], i, text, pages)}
            rows.append(
                (
                    str(uuid.uuid4()),
                    self.kb_id,
                    doc["id"],
                    i,
                    text,
                    json.dumps(meta),
                    "[" + ",".join(f"{x:.7f}" for x in vec) + "]",
                    self.target,
                    self.kb["dedicated"],
                )
            )
        execute_values(
            self.cur,
            "INSERT INTO chunks (id, collection_id, document_id, chunk_index, "
            "content, metadata, embedding, embedding_generation, dedicated_index) "
            "VALUES %s",
            rows,
            template="(%s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s, %s)",
        )

    def stage(self, doc: dict[str, Any]) -> None:
        def stored() -> tuple[list[str], list[int | None], dict[str, Any]]:
            if self.index is None:
                return _stored_chunks_pgvector(
                    self.cur, self.kb_id, doc["id"], self.source
                )
            return _stored_chunks_pinecone(
                self.index, self.namespace(self.source), doc["id"], doc["chunk_count"]
            )

        chunks, pages, carried, source = _document_chunks(doc, self.kb, stored)
        # a document starts over after a crash, what it staged earlier goes first
        if self.index is None:
            self.cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND document_id = %s "
                "AND embedding_generation = %s",
                (self.kb_id, doc["id"], self.target),
            )
        self.conn.commit()
        for b in range(0, len(chunks), EMBED_BATCH):
            part = chunks[b : b + EMBED_BATCH]
            self._spend_check(part)
            vectors, _real = dp._embed_chunks(part, self.row["to_model"], strict=True)
            if len(vectors) != len(part):
                raise ReembedError("embedding provider returned a short batch")
            self._write_rows(doc, b, part, vectors, pages, carried)
            self.conn.commit()
        if self.index is not None:
            stale = [f"{doc['id']}_{i}" for i in range(len(chunks), doc["chunk_count"])]
            for i in range(0, len(stale), 1000):
                self.index.delete(
                    ids=stale[i : i + 1000], namespace=self.namespace(self.target)
                )
        self.cur.execute(
            "INSERT INTO kb_reembed_documents (job_id, document_id, chunk_count, source) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (job_id, document_id) DO UPDATE "
            "SET chunk_count = EXCLUDED.chunk_count, source = EXCLUDED.source",
            (self.id, doc["id"], len(chunks), source),
        )
        self.cur.execute(
            "UPDATE kb_reembed_jobs SET documents_done = "
            "(SELECT count(*) FROM kb_reembed_documents WHERE job_id = %s), "
            "chunks_done = (SELECT COALESCE(sum(chunk_count), 0) "
            "FROM kb_reembed_documents WHERE job_id = %s), "
            f"{'from_file' if source == 'file' else 'from_indexed_text'} = "
            f"{'from_file' if source == 'file' else 'from_indexed_text'} + 1, "
            "heartbeat_at = now(), updated_at = now() WHERE id = %s",
            (self.id, self.id, self.id),
        )
        self.conn.commit()

    def stage_until(self, deadline: float) -> bool:
        """True once every document is staged, False when the slice ran out."""
        from psycopg2.errors import ForeignKeyViolation

        while True:
            status = self.requested_status()
            if status != "running":
                raise _Hold("paused" if status == "pausing" else status)
            docs = _next_documents(self.cur, self.kb_id, self.id, DOCUMENT_BATCH)
            self.conn.commit()
            if not docs:
                return True
            for doc in docs:
                try:
                    self.stage(doc)
                except ForeignKeyViolation:
                    # deleted while being staged, the next pass no longer lists it
                    self.conn.rollback()
                    continue
                if time.monotonic() >= deadline:
                    return False
                if self.requested_status() != "running":
                    break

    def flip(self) -> bool:
        """One row update moves queries across, False when a document arrived first."""
        if self.index is not None:
            self.cur.execute(
                "SELECT document_id::text FROM kb_reembed_documents WHERE job_id = %s",
                (self.id,),
            )
            done = {r[0] for r in self.cur.fetchall()}
            self.conn.commit()
            loose = _stage_loose_vectors(
                self.index,
                self.namespace(self.source),
                self.namespace(self.target),
                done,
                self.row["to_model"],
            )
            if loose < 0:
                logger.warning(
                    "re-embed %s: the index cannot list ids, vectors stored without "
                    "a document keep the old model and leave with the old namespace",
                    self.id,
                )
        self.cur.execute(
            "SELECT 1 FROM knowledge_collections WHERE id = %s FOR UPDATE",
            (self.kb_id,),
        )
        if _next_documents(self.cur, self.kb_id, self.id, 1):
            self.conn.rollback()
            return False
        self.cur.execute(
            "UPDATE knowledge_collections SET embedding_model = %s, "
            "embedding_generation = %s, status = 'READY' WHERE id = %s",
            (self.row["to_model"], self.target, self.kb_id),
        )
        self.cur.execute(
            "UPDATE kb_reembed_jobs SET status = 'cleaning', flipped_at = now(), "
            "heartbeat_at = now(), updated_at = now() WHERE id = %s",
            (self.id,),
        )
        self.conn.commit()
        _invalidate_search_cache(self.cur, self.kb_id)
        self.conn.commit()
        return True

    def clean_until(self, deadline: float) -> bool:
        """Batched removal of everything the flip left behind, safe to repeat."""
        while True:
            self.cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND id IN ("
                "SELECT id FROM chunks WHERE collection_id = %s "
                "AND embedding_generation <> %s LIMIT %s)",
                (self.kb_id, self.kb_id, self.target, DELETE_BATCH),
            )
            removed = self.cur.rowcount
            self.beat()
            if not removed:
                break
            if time.monotonic() >= deadline:
                return False
        if self.index is not None:
            # pgvector rows of a Pinecone collection are ingest fallbacks nothing queries
            self.index.delete(delete_all=True, namespace=self.namespace(self.source))
        while True:
            self.cur.execute(
                "WITH part AS (SELECT s.document_id, s.chunk_count "
                "FROM kb_reembed_documents s WHERE s.job_id = %s LIMIT 1000), "
                "upd AS (UPDATE documents d SET chunk_count = part.chunk_count, "
                "status = 'READY', error_message = NULL FROM part "
                "WHERE d.id = part.document_id) "
                "DELETE FROM kb_reembed_documents s USING part "
                "WHERE s.job_id = %s AND s.document_id = part.document_id",
                (self.id, self.id),
            )
            removed = self.cur.rowcount
            self.beat()
            if not removed:
                break
            if time.monotonic() >= deadline:
                return False
        self.cur.execute(
            "UPDATE knowledge_collections SET doc_count = (SELECT count(*) "
            "FROM documents WHERE kb_id = %s AND status IN ('READY', 'DEGRADED')) "
            "WHERE id = %s",
            (self.kb_id, self.kb_id),
        )
        self.beat(status="completed", finished_at=_utcnow())
        return True

    def discard_until(self, deadline: float) -> bool:
        """A cancelled job takes its staged rows with it, the collection never moved."""
        while True:
            self.cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND id IN ("
                "SELECT id FROM chunks WHERE collection_id = %s "
                "AND embedding_generation = %s LIMIT %s)",
                (self.kb_id, self.kb_id, self.target, DELETE_BATCH),
            )
            removed = self.cur.rowcount
            self.beat()
            if not removed:
                break
            if time.monotonic() >= deadline:
                return False
        if self.index is not None:
            self.index.delete(delete_all=True, namespace=self.namespace(self.target))
        self.cur.execute(
            "DELETE FROM kb_reembed_documents WHERE job_id = %s", (self.id,)
        )
        self.beat(status="cancelled", finished_at=_utcnow())
        return True


def _utcnow() -> Any:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _pinecone_index() -> Any:
    from pinecone import Pinecone

    return Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)


def _load(cur: Any, job_id: str) -> tuple[dict | None, dict | None]:
    cur.execute(
        "SELECT id::text, tenant_id::text, kb_id::text, to_model, status, "
        "target_generation FROM kb_reembed_jobs WHERE id = %s",
        (job_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None, None
    job = dict(
        zip(
            ("id", "tenant_id", "kb_id", "to_model", "status", "target_generation"), row
        )
    )
    cur.execute(
        "SELECT vector_backend, embedding_model, chunk_size, chunk_overlap, "
        "embedding_generation, deleted_at, index_mode <> 'shared' "
        "FROM knowledge_collections WHERE id = %s",
        (job["kb_id"],),
    )
    k = cur.fetchone()
    if k is None or k[5] is not None:
        return job, None
    return job, {
        "backend": k[0] or "pinecone",
        "model": k[1],
        "chunk_size": k[2],
        "chunk_overlap": k[3],
        "generation": k[4] or 0,
        "dedicated": bool(k[6]),
    }


def _again(job_id: str) -> None:
    celery_app.send_task(TASK_NAME, kwargs={"job_id": job_id}, queue="documents")


def reembed_slice(
    job_id: str,
    slice_seconds: float | None = None,
    requeue: Callable[[str], None] = _again,
) -> dict[str, Any]:
    """Run the job until its slice is spent, then hand over to the next one."""
    import embedding_models as em
    import psycopg2

    url = dp._sync_db_url()
    lock_conn = psycopg2.connect(url)
    lock_conn.autocommit = True
    conn = psycopg2.connect(url)
    deadline = time.monotonic() + (
        SLICE_SECONDS if slice_seconds is None else slice_seconds
    )
    try:
        cur = conn.cursor()
        job, kb = _load(cur, job_id)
        conn.commit()
        if job is None:
            return {"status": "missing", "job_id": job_id}
        with lock_conn.cursor() as lc:
            lc.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))",
                (f"kb_reembed:{job['kb_id']}",),
            )
            if not lc.fetchone()[0]:
                return {"status": "skipped", "job_id": job_id}
        status = job["status"]
        if status in ("completed", "cancelled", "paused", "failed"):
            return {"status": status, "job_id": job_id}
        if kb is None:
            cur.execute(
                "UPDATE kb_reembed_jobs SET status = 'cancelled', finished_at = now(), "
                "error = 'the collection was deleted' WHERE id = %s",
                (job_id,),
            )
            conn.commit()
            return {"status": "cancelled", "job_id": job_id}
        if not em.is_supported(job["to_model"]):
            err = (
                f"{job['to_model']} is not a supported embedding model "
                f"({', '.join(em.SUPPORTED)})"
            )
            cur.execute(
                "UPDATE kb_reembed_jobs SET status = 'failed', error = %s, "
                "finished_at = now() WHERE id = %s",
                (err, job_id),
            )
            conn.commit()
            return {"status": "failed", "job_id": job_id, "error": err}
        worker = _Job(conn, job, kb)
        try:
            if status == "cancelling":
                done = worker.discard_until(deadline)
            elif status == "cleaning":
                done = worker.clean_until(deadline)
            else:
                cur.execute(
                    "UPDATE kb_reembed_jobs SET status = 'running', error = NULL, "
                    "started_at = COALESCE(started_at, now()), heartbeat_at = now(), "
                    "documents_total = (SELECT count(*) FROM documents d "
                    "WHERE d.kb_id = %s AND d.status IN ('READY', 'DEGRADED')) "
                    "WHERE id = %s AND status IN ('queued', 'running', 'flipping')",
                    (job["kb_id"], job_id),
                )
                conn.commit()
                done = False
                staged = worker.stage_until(deadline)
                if staged and worker.flip():
                    done = worker.clean_until(deadline)
        except _Hold as hold:
            conn.rollback()
            if hold.status == "cancelling":
                requeue(job_id)
            else:
                worker.beat(status=hold.status, error=hold.message)
            return {"status": hold.status, "job_id": job_id, "error": hold.message}
        if not done:
            requeue(job_id)
            return {"status": "continuing", "job_id": job_id}
        return {
            "status": worker.requested_status(),
            "job_id": job_id,
            "kb_id": job["kb_id"],
            "to_model": job["to_model"],
        }
    except Exception as e:
        conn.rollback()
        logger.exception("kb_reembed failed job=%s", job_id)
        # staged work stays, resuming carries on from the last finished document
        with conn.cursor() as c2:
            c2.execute(
                "UPDATE kb_reembed_jobs SET status = 'failed', error = %s, "
                "heartbeat_at = now(), updated_at = now() "
                "WHERE id = %s AND status NOT IN ('completed', 'cancelled')",
                (str(e)[:500], job_id),
            )
        conn.commit()
        return {"status": "failed", "job_id": job_id, "error": str(e)}
    finally:
        conn.close()
        lock_conn.close()


def _invalidate_search_cache(cur: Any, kb_id: str) -> None:
    try:
        from worker.tasks.kb_quota import tenant_of

        tenant = tenant_of(cur, kb_id)
        if not tenant:
            return
        import redis

        url = (
            os.environ.get("REDIS_URL")
            or os.environ.get("CELERY_RESULT_BACKEND")
            or os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
        )
        r = redis.Redis.from_url(url, socket_timeout=3)
        for key in r.scan_iter(match=f"kbsearch:{tenant}:*", count=200):
            r.delete(key)
    except Exception as e:
        logger.debug("search cache invalidation after re-embed failed: %s", e)


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    max_retries=0,
    soft_time_limit=int(os.environ.get("KB_REEMBED_SOFT_LIMIT", "3300")),
    time_limit=int(os.environ.get("KB_REEMBED_TIME_LIMIT", "3600")),
)
def run(self: Any, *, job_id: str) -> dict:
    return reembed_slice(job_id)


__all__ = ["run", "reembed_slice", "TASK_NAME"]
