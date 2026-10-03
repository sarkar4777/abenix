"""Re-embed a knowledge collection with another embedding model.

Every current document is re-extracted from storage and re-chunked with the
collection's chunk settings (falling back to the chunk text already indexed
when the file is gone), embedded with the target model, and staged. Nothing
live changes until every document is staged. Then the swap runs: pgvector
collections replace their chunks and flip `embedding_model` in one
transaction, Pinecone collections upsert over the same ids, drop the stale
tail, and flip the model. Queries read `embedding_model`, so they move to the
new vectors at the flip.

Progress lives in Redis under `kb_reembed:<kb_id>` for the API to report.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import struct
import tempfile
from datetime import datetime, timezone
from typing import Any, Callable

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp

logger = logging.getLogger(__name__)

STATUS_TTL = 7 * 24 * 3600
EMBED_BATCH = 100


def status_key(kb_id: str) -> str:
    return f"kb_reembed:{kb_id}"


def _redis():
    import redis

    url = (
        os.environ.get("REDIS_URL")
        or os.environ.get("CELERY_RESULT_BACKEND")
        or os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    )
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=3)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Progress:
    def __init__(self, kb_id: str, base: dict[str, Any]) -> None:
        self.kb_id = kb_id
        self.state = dict(base)
        try:
            self.r = _redis()
        except Exception:
            self.r = None

    def update(self, **kw: Any) -> None:
        self.state.update(kw)
        if self.r is None:
            return
        try:
            self.r.set(status_key(self.kb_id), json.dumps(self.state), ex=STATUS_TTL)
        except Exception as e:
            logger.debug("re-embed progress write failed: %s", e)


class ReembedError(Exception):
    pass


def _pack(vec: list[float]) -> str:
    return base64.b64encode(struct.pack(f"{len(vec)}f", *vec)).decode("ascii")


def _unpack(blob: str) -> list[float]:
    raw = base64.b64decode(blob)
    return list(struct.unpack(f"{len(raw) // 4}f", raw))


def _stored_chunks_pgvector(
    cur: Any, doc_id: str
) -> tuple[list[str], list[int | None]]:
    cur.execute(
        "SELECT content, metadata FROM chunks WHERE document_id = %s ORDER BY chunk_index",
        (doc_id,),
    )
    rows = cur.fetchall()
    texts = [r[0] for r in rows if r[0]]
    pages = [
        ((r[1] or {}).get("page") if isinstance(r[1], dict) else None)
        for r in rows
        if r[0]
    ]
    return texts, pages


def _stored_chunks_pinecone(
    index: Any, kb_id: str, doc_id: str, count: int
) -> tuple[list[str], list[int | None]]:
    texts: list[str] = []
    pages: list[int | None] = []
    ids = [f"{doc_id}_{i}" for i in range(count)]
    for i in range(0, len(ids), 500):
        resp = index.fetch(ids=ids[i : i + 500], namespace=kb_id)
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
                texts.append(meta["text"])
                pages.append(meta.get("page"))
    return texts, pages


def _stage_loose_vectors(
    index: Any, kb_id: str, doc_ids: set[str], new_model: str, spool: Any
) -> int:
    """Vectors with no documents row (knowledge_store writes these) get the new model too."""
    try:
        ids = [
            vid
            for page in index.list(namespace=kb_id)
            for vid in (page if isinstance(page, (list, tuple)) else [page])
            if vid.rsplit("_", 1)[0] not in doc_ids
        ]
    except Exception as e:
        # pod-based indexes cannot list ids
        logger.warning("re-embed: cannot list namespace %s (%s)", kb_id, e)
        return -1
    staged = 0
    for i in range(0, len(ids), 100):
        part = ids[i : i + 100]
        resp = index.fetch(ids=part, namespace=kb_id)
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
        for (vid, meta), vec in zip(rows, embedded):
            spool.write(json.dumps({"id": vid, "m": meta, "v": _pack(vec)}) + "\n")
            staged += 1
    return staged


def _document_chunks(
    doc: dict[str, Any],
    kb: dict[str, Any],
    stored: Callable[[], tuple[list[str], list[int | None]]],
) -> tuple[list[str], list[int | None], str]:
    """Re-extract and re-chunk the file; fall back to the indexed chunk text."""
    tmp = None
    try:
        local, tmp = dp._local_path(doc["storage_url"] or "", doc["file_type"] or "")
        blocks, _method, _quality = dp._extract_blocks(local, doc["file_type"] or "")
        if blocks:
            chunks, pages = dp._chunk_blocks(
                blocks, kb["chunk_size"] or 1000, kb["chunk_overlap"] or 200
            )
            if chunks:
                return chunks, pages, "file"
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
    chunks, pages = stored()
    return chunks, pages, "indexed"


def _ready_documents(cur: Any, kb_id: str) -> list[dict[str, Any]]:
    cur.execute(
        "SELECT id::text, filename, file_type, storage_url, chunk_count "
        "FROM documents WHERE kb_id = %s AND status IN ('READY', 'DEGRADED') "
        "ORDER BY created_at",
        (kb_id,),
    )
    return [
        {
            "id": r[0],
            "filename": r[1],
            "file_type": r[2],
            "storage_url": r[3],
            "chunk_count": r[4] or 0,
        }
        for r in cur.fetchall()
    ]


def reembed_collection(
    *, kb_id: str, new_model: str, job_id: str, progress: _Progress | None = None
) -> dict[str, Any]:
    import embedding_models as em
    import psycopg2

    progress = progress or _Progress(kb_id, {"job_id": job_id, "kb_id": kb_id})
    if not em.is_supported(new_model):
        err = (
            f"{new_model} is not a supported embedding model "
            f"({', '.join(em.SUPPORTED)})"
        )
        progress.update(status="failed", error=err, finished_at=_now())
        return {"status": "failed", "kb_id": kb_id, "job_id": job_id, "error": err}

    url = dp._sync_db_url()
    lock_conn = psycopg2.connect(url)
    lock_conn.autocommit = True
    conn = psycopg2.connect(url)
    prior_status = None
    try:
        with lock_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s))", (f"kb_reembed:{kb_id}",)
            )
            if not cur.fetchone()[0]:
                progress.update(
                    status="skipped",
                    error="another re-embed of this collection is running",
                    finished_at=_now(),
                )
                return {"status": "skipped", "kb_id": kb_id, "job_id": job_id}

        cur = conn.cursor()
        cur.execute(
            "SELECT vector_backend, embedding_model, chunk_size, chunk_overlap, status "
            "FROM knowledge_collections WHERE id = %s",
            (kb_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ReembedError("knowledge base not found")
        kb = {
            "backend": row[0] or "pinecone",
            "model": row[1],
            "chunk_size": row[2],
            "chunk_overlap": row[3],
        }
        prior_status = row[4]
        docs = _ready_documents(cur, kb_id)
        progress.update(
            status="running",
            from_model=kb["model"],
            to_model=new_model,
            backend=kb["backend"],
            documents_total=len(docs),
            documents_done=0,
            chunks=0,
            started_at=_now(),
            error=None,
        )
        cur.execute(
            "UPDATE knowledge_collections SET status = 'PROCESSING' WHERE id = %s",
            (kb_id,),
        )
        conn.commit()

        index = None
        if kb["backend"] != "pgvector":
            if not dp.PINECONE_API_KEY:
                raise ReembedError(
                    "this collection stores vectors in Pinecone but PINECONE_API_KEY is not set"
                )
            from pinecone import Pinecone

            index = Pinecone(api_key=dp.PINECONE_API_KEY).Index(dp.PINECONE_INDEX_NAME)

        if index is None:
            cur.execute(
                "CREATE TEMP TABLE IF NOT EXISTS reembed_stage ("
                "document_id uuid, chunk_index int, content text, metadata jsonb, "
                "embedding vector(1536)) ON COMMIT PRESERVE ROWS"
            )
            cur.execute("TRUNCATE reembed_stage")
        spool = tempfile.NamedTemporaryFile(
            "w+", delete=False, suffix=".reembed", encoding="utf-8"
        )
        counts: dict[str, int] = {}
        sources = {"file": 0, "indexed": 0}
        total_chunks = 0
        try:

            def stage(doc: dict[str, Any]) -> None:
                nonlocal total_chunks

                def stored() -> tuple[list[str], list[int | None]]:
                    if index is None:
                        return _stored_chunks_pgvector(cur, doc["id"])
                    return _stored_chunks_pinecone(
                        index, kb_id, doc["id"], doc["chunk_count"]
                    )

                chunks, pages, source = _document_chunks(doc, kb, stored)
                if not chunks:
                    raise ReembedError(
                        f"no text available for document {doc['filename']} ({doc['id']})"
                    )
                sources[source] += 1
                for b in range(0, len(chunks), EMBED_BATCH):
                    part = chunks[b : b + EMBED_BATCH]
                    vectors, _real = dp._embed_chunks(part, new_model, strict=True)
                    if len(vectors) != len(part):
                        raise ReembedError("embedding provider returned a short batch")
                    for j, (text, vec) in enumerate(zip(part, vectors)):
                        i = b + j
                        if index is None:
                            meta = dp._chunk_meta(doc["filename"], i, text, pages)
                            cur.execute(
                                "INSERT INTO reembed_stage VALUES (%s, %s, %s, %s::jsonb, %s::vector)",
                                (
                                    doc["id"],
                                    i,
                                    text,
                                    json.dumps(meta),
                                    "[" + ",".join(f"{x:.7f}" for x in vec) + "]",
                                ),
                            )
                        else:
                            v = dp._pinecone_vector(
                                kb_id, doc["id"], doc["filename"], i, text, vec, pages
                            )
                            spool.write(
                                json.dumps(
                                    {
                                        "id": v["id"],
                                        "m": v["metadata"],
                                        "v": _pack(v["values"]),
                                    }
                                )
                                + "\n"
                            )
                counts[doc["id"]] = len(chunks)
                total_chunks += len(chunks)
                conn.commit()
                progress.update(documents_done=len(counts), chunks=total_chunks)

            for doc in docs:
                stage(doc)
            # documents that finished ingesting while we worked
            for _ in range(3):
                late = [
                    d for d in _ready_documents(cur, kb_id) if d["id"] not in counts
                ]
                if not late:
                    break
                docs.extend(late)
                progress.update(documents_total=len(docs))
                for doc in late:
                    stage(doc)
            loose = 0
            if index is not None:
                loose = _stage_loose_vectors(
                    index, kb_id, set(counts), new_model, spool
                )
                progress.update(
                    loose_vectors=loose,
                    warning=(
                        "the index cannot list ids, so vectors stored without a "
                        "document (knowledge_store) keep the old model"
                        if loose < 0
                        else None
                    ),
                )
            cur.execute(
                "SELECT 1 FROM knowledge_collections WHERE id = %s FOR UPDATE", (kb_id,)
            )
            staged = list(counts)

            if index is None:
                cur.execute(
                    "DELETE FROM chunks WHERE collection_id = %s "
                    "AND document_id = ANY(%s::uuid[])",
                    (kb_id, staged),
                )
                cur.execute(
                    "INSERT INTO chunks (id, collection_id, document_id, chunk_index, "
                    "content, metadata, embedding) SELECT gen_random_uuid(), %s, "
                    "document_id, chunk_index, content, metadata, embedding FROM reembed_stage",
                    (kb_id,),
                )
            else:
                spool.flush()
                spool.seek(0)
                batch: list[dict[str, Any]] = []
                for line in spool:
                    rec = json.loads(line)
                    batch.append(
                        {
                            "id": rec["id"],
                            "values": _unpack(rec["v"]),
                            "metadata": rec["m"],
                        }
                    )
                    if len(batch) >= 100:
                        index.upsert(vectors=batch, namespace=kb_id)
                        batch = []
                if batch:
                    index.upsert(vectors=batch, namespace=kb_id)
                for doc in docs:
                    stale = [
                        f"{doc['id']}_{i}"
                        for i in range(counts[doc["id"]], doc["chunk_count"])
                    ]
                    for i in range(0, len(stale), 1000):
                        index.delete(ids=stale[i : i + 1000], namespace=kb_id)
                # pgvector rows of a Pinecone collection are ingest fallbacks nothing queries
                cur.execute(
                    "DELETE FROM chunks WHERE collection_id = %s "
                    "AND document_id = ANY(%s::uuid[])",
                    (kb_id, staged),
                )

            for doc_id, n_chunks in counts.items():
                cur.execute(
                    "UPDATE documents SET chunk_count = %s, status = 'READY', "
                    "error_message = NULL WHERE id = %s",
                    (n_chunks, doc_id),
                )
            cur.execute(
                "UPDATE knowledge_collections SET embedding_model = %s, status = 'READY', "
                "doc_count = (SELECT count(*) FROM documents WHERE kb_id = %s "
                "AND status IN ('READY', 'DEGRADED')) WHERE id = %s",
                (new_model, kb_id, kb_id),
            )
            conn.commit()
        finally:
            spool.close()
            try:
                os.unlink(spool.name)
            except OSError:
                pass
            if index is None:
                try:
                    conn.rollback()
                    cur.execute("DROP TABLE IF EXISTS reembed_stage")
                    conn.commit()
                except Exception:
                    conn.rollback()

        _invalidate_search_cache(kb_id)
        result = {
            "status": "completed",
            "kb_id": kb_id,
            "job_id": job_id,
            "from_model": kb["model"],
            "to_model": new_model,
            "documents": len(docs),
            "chunks": total_chunks,
            "from_file": sources["file"],
            "from_indexed_text": sources["indexed"],
            "loose_vectors": loose,
        }
        progress.update(
            status="completed",
            finished_at=_now(),
            from_file=sources["file"],
            from_indexed_text=sources["indexed"],
        )
        logger.info("kb_reembed done %s", result)
        return result
    except Exception as e:
        conn.rollback()
        if prior_status is not None:
            try:
                with conn.cursor() as c2:
                    c2.execute(
                        "UPDATE knowledge_collections SET status = %s WHERE id = %s",
                        (prior_status, kb_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
        logger.exception("kb_reembed failed kb=%s", kb_id)
        progress.update(status="failed", error=str(e)[:500], finished_at=_now())
        return {"status": "failed", "kb_id": kb_id, "job_id": job_id, "error": str(e)}
    finally:
        conn.close()
        lock_conn.close()


def _invalidate_search_cache(kb_id: str) -> None:
    try:
        import psycopg2

        conn = psycopg2.connect(dp._sync_db_url())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id::text FROM knowledge_collections WHERE id = %s",
                    (kb_id,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return
        r = _redis()
        for key in r.scan_iter(match=f"kbsearch:{row[0]}:*", count=200):
            r.delete(key)
    except Exception as e:
        logger.debug("search cache invalidation after re-embed failed: %s", e)


@celery_app.task(
    name="worker.tasks.kb_reembed.run",
    bind=True,
    max_retries=0,
    soft_time_limit=int(os.environ.get("KB_REEMBED_SOFT_LIMIT", "20700")),
    time_limit=int(os.environ.get("KB_REEMBED_TIME_LIMIT", "21600")),
)
def run(self: Any, *, kb_id: str, new_model: str, job_id: str) -> dict:
    return reembed_collection(kb_id=kb_id, new_model=new_model, job_id=job_id)


__all__ = ["run", "reembed_collection", "status_key"]
