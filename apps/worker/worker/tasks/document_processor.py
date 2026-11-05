"""Celery task: process uploaded documents for RAG.

Pipeline: detect type -> extract text -> chunk -> embed -> store in Pinecone -> update DB.
"""

import hashlib
import io
import json
import logging
import os
import random
import sys
import time
import uuid
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded

from worker import metrics
from worker.celery_app import celery_app

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

logger = logging.getLogger(__name__)

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "agentforge-knowledge")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Default embedding model name. Both the Azure deployment alias and the
# OpenAI direct-API model fall back to this. Override per-environment via
# OPENAI_EMBEDDING_MODEL (OpenAI direct) and AZURE_EMBEDDING_DEPLOYMENT
# (Azure deployment name). A collection's own embedding_model wins over both.
EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536

BATCH_CHUNKS = int(os.environ.get("KB_INGEST_BATCH_CHUNKS", "100"))
EMBED_CONCURRENCY = max(1, int(os.environ.get("KB_EMBED_CONCURRENCY", "4")))
CHUNK_WINDOW_CHARS = int(os.environ.get("KB_CHUNK_WINDOW_CHARS", "262144"))
SLICE_SECONDS = int(os.environ.get("KB_INGEST_SLICE_SECONDS", "600"))
MAX_ATTEMPTS = int(os.environ.get("KB_INGEST_MAX_ATTEMPTS", "5"))
MAX_WAIT_SECONDS = int(os.environ.get("KB_INGEST_MAX_WAIT_SECONDS", "86400"))
INLINE_RETRIES = int(os.environ.get("KB_EMBED_INLINE_RETRIES", "4"))
INLINE_WAIT_MAX = float(os.environ.get("KB_EMBED_INLINE_WAIT_MAX", "60"))
REQUEUE_WAIT_MAX = 900.0


class EmbeddingProviderError(Exception):
    """No usable embedding provider configured (no Azure + no OpenAI key)."""


_AZURE_STRIP_WARNED = False


class EmbeddingProviderCallFailed(EmbeddingProviderError):
    def __init__(self, message: str, cause: Exception) -> None:
        super().__init__(message)
        self.refused = _is_refusal(cause)
        self.retry_after = _retry_after(cause)


def _is_refusal(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    # a 429 can be a passing rate limit, only insufficient_quota means no credits
    return status in (401, 403) or (status == 429 and "insufficient_quota" in str(exc))


def _retry_after(exc: Exception) -> float | None:
    from engine.knowledge.embed_gate import retry_after_seconds

    return retry_after_seconds(exc)


def _is_transient(exc: Exception) -> bool:
    if _is_refusal(exc):
        return False
    status = getattr(exc, "status_code", None)
    if status is None:
        return type(exc).__name__ in ("APIConnectionError", "APITimeoutError")
    return status in (408, 409, 429) or status >= 500


def _call_provider(provider: str, texts: list[str], call):
    """Every provider call waits on the shared gate, and a 429 holds all workers."""
    from engine.knowledge.embed_gate import embed_gate, estimate_tokens

    gate = embed_gate(provider)
    tokens = estimate_tokens(texts)
    attempt = 0
    while True:
        gate.acquire(tokens)
        try:
            return call()
        except Exception as exc:
            if not _is_transient(exc):
                raise
            wait = _retry_after(exc)
            if wait is None:
                wait = random.uniform(0.5, min(INLINE_WAIT_MAX, 2.0 ** (attempt + 1)))
            gate.pause(wait)
            attempt += 1
            # a long wait goes back to the queue, so the worker can read something else
            if attempt > INLINE_RETRIES or wait > INLINE_WAIT_MAX:
                raise


def _normalize_azure_endpoint(raw: str) -> str:
    """Strip the /openai/deployments path the SDK adds itself. Trailing slashes too."""
    if not raw:
        return raw
    s = raw.rstrip("/")
    for suffix in ("/openai/deployments", "/openai"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.rstrip("/")


def _strip_file_scheme(p: str) -> str:
    """Normalise a storage URL to a filesystem path."""
    if p is None:
        return ""
    for prefix in ("file:///", "file://", "file:/"):
        if p.startswith(prefix):
            return (
                "/" + p[len(prefix) :]
                if not p[len(prefix) :].startswith("/")
                else p[len(prefix) :]
            )
    return p


def _sync_db_url() -> str:
    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
    )
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    # asyncpg accepts `?ssl=...` but psycopg2 rejects it
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")
    return sync_url


def _local_path(file_path: str, file_type: str) -> tuple[str, str | None]:
    """A readable local path for a storage URL, plus a temp file to remove afterwards."""
    if not (file_path.startswith("s3://") or file_path.startswith("az://")):
        return _strip_file_scheme(file_path), None
    import asyncio
    import tempfile

    from engine.storage import get_storage

    suffix = f".{file_type}" if file_type else ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    try:
        asyncio.run(get_storage().download_to_file(file_path, tmp.name))
    except Exception:
        os.unlink(tmp.name)
        raise
    return tmp.name, tmp.name


def _extract_text_legacy(file_path: str, file_type: str) -> str:
    path = Path(_strip_file_scheme(file_path))
    ft = file_type.lower()

    if ft in ("pdf", "application/pdf"):
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    if ft in (
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ):
        from docx import Document

        doc = Document(str(path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    return path.read_text(encoding="utf-8", errors="replace")


def _extract_blocks(
    file_path: str, file_type: str
) -> tuple[list[tuple[str, int | None]], str | None, float | None]:
    """(text, page) blocks plus the extraction method and quality the dispatcher picked."""
    import asyncio

    path = _strip_file_scheme(file_path)
    try:
        from engine.knowledge.extractors import extract_document
    except ImportError:
        text = _extract_text_legacy(path, file_type)
        return ([(text, None)] if text.strip() else []), None, None
    blocks, method, quality = asyncio.run(extract_document(path, file_type=file_type))
    out = [(b.text, b.page) for b in blocks if (b.text or "").strip()]
    return out, method, quality


def _extract_text(file_path: str, file_type: str) -> str:
    blocks, _method, _quality = _extract_blocks(file_path, file_type)
    return "\n\n".join(t for t, _p in blocks)


def _chunk_text(
    text: str, chunk_size: int = 1000, chunk_overlap: int = 200
) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _chunk_blocks(
    blocks: list[tuple[str, int | None]], chunk_size: int, chunk_overlap: int
) -> tuple[list[str], list[int | None]]:
    """Chunk page by page when pages are known, so every chunk can cite its page."""
    if not any(p is not None for _t, p in blocks):
        text = "\n\n".join(t for t, _p in blocks)
        chunks = _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return chunks, [None] * len(chunks)
    chunks: list[str] = []
    pages: list[int | None] = []
    for text, page in blocks:
        for c in _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunks.append(c)
            pages.append(page)
    return chunks, pages


def _splitter(chunk_size: int, chunk_overlap: int):
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=["\n\n", "\n", ". ", " ", ""],
    )


def _iter_chunks(
    blocks: Iterable[tuple[str, int | None, bool]],
    chunk_size: int,
    chunk_overlap: int,
    window: int | None = None,
) -> Iterator[tuple[str, int | None]]:
    """Same chunks as _chunk_blocks for a small file, with at most a window of text held."""
    window = window or CHUNK_WINDOW_CHARS
    splitter = _splitter(chunk_size, chunk_overlap)
    buffer = ""
    page: int | None = None

    def drain(final: bool) -> Iterator[tuple[str, int | None]]:
        nonlocal buffer
        parts = splitter.split_text(buffer)
        if not parts:
            buffer = ""
            return
        keep = None if final else parts[-1]
        for part in parts if final else parts[:-1]:
            yield part, page
        if keep is None:
            buffer = ""
        else:
            # a splitter strips the end of the last piece, the next window must follow it exactly
            at = buffer.rfind(keep)
            buffer = buffer[at:] if at >= 0 else keep

    for text, block_page, continued in blocks:
        if continued:
            buffer += text
        elif block_page is None and page is None and buffer:
            buffer += "\n\n" + text
        else:
            yield from drain(True)
            buffer = text
            page = block_page
        while len(buffer) >= window:
            before = len(buffer)
            yield from drain(False)
            if len(buffer) >= before:
                break
    yield from drain(True)


def _copy_field(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\x00", "")
    )


EMBEDDING_DIM = 1536


def _after_provider_failure(
    kb_id: str, doc_id: str, chunks: list[str], exc: Exception, stored_here: int = 0
) -> tuple[list[list[float]], bool, str | None, str]:
    """(vectors, usable, collection model, message for the document) once the provider refused."""
    from local_embeddings import embed_many, embedder_id, is_forced_off

    reason = str(exc)[:300]
    current = _kb_settings(kb_id)[1]
    # one scheme per collection, hash vectors beside provider vectors match nothing
    if current != embedder_id() and (
        is_forced_off() or stored_here > 0 or _collection_has_vectors(kb_id, doc_id)
    ):
        return (
            [],
            False,
            current,
            f"The embedding provider failed and no vectors were stored, so this "
            f"document cannot be searched. Provider said {reason}",
        )
    if current != embedder_id():
        _set_collection_model(kb_id, embedder_id())
    logger.warning(
        "embedding provider failed for collection %s, indexed with %s",
        kb_id,
        embedder_id(),
    )
    return (
        embed_many(chunks),
        True,
        embedder_id(),
        "The embedding provider failed, so this document was indexed with the local "
        "hashing embedder, which matches words and not meaning. Fix the provider "
        f"and re-embed the collection for semantic search. Provider said {reason}",
    )


def _collection_has_vectors(kb_id: str, doc_id: str) -> bool:
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM documents WHERE kb_id = %s AND id <> %s "
                "AND status IN ('READY', 'DEGRADED') AND chunk_count > 0 LIMIT 1",
                (kb_id, doc_id),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def _set_collection_model(kb_id: str, model: str) -> None:
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_collections SET embedding_model = %s WHERE id = %s",
                (model, kb_id),
            )
        conn.commit()
    finally:
        conn.close()


def _local_embeddings_enabled() -> bool:
    """Whether to fall back to the offline embedder. Never raises."""
    try:
        from local_embeddings import is_enabled

        return is_enabled()
    except Exception:  # noqa: BLE001 — a missing module must not break ingest
        return False


def _model_names(model: str | None) -> tuple[str, str, dict]:
    try:
        import embedding_models as em

        return (
            em.provider_model(model),
            em.azure_deployment(model),
            em.request_kwargs(model),
        )
    except ImportError:
        return (
            EMBEDDING_MODEL,
            os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", EMBEDDING_MODEL),
            {},
        )


@metrics.counts_embed_failures
def _embed_chunks(
    chunks: list[str], model: str | None = None, strict: bool = False
) -> tuple[list[list[float]], bool]:
    """Returns (embeddings, used_real_model). Provider selection:
      0. The local hashing embedder when the collection is indexed with it.
      1. Azure OpenAI if AZURE_OPENAI_API_KEY + endpoint are set (preferred —
         that's what the production cluster pays for).
      2. Direct OpenAI fallback if OPENAI_API_KEY is set and Azure errored
         or wasn't configured.
      3. Otherwise raise EmbeddingProviderError so the caller flags failure
         loudly instead of silently storing zero vectors.

    A failing provider call raises EmbeddingProviderCallFailed, the caller picks what follows.

    strict=True (re-embedding) never switches to the local embedder."""
    try:
        from local_embeddings import MODEL_ID as _LOCAL_ID
    except ImportError:
        _LOCAL_ID = "local-hashing-v1"
    if model == _LOCAL_ID:
        from local_embeddings import embed_many

        return embed_many(chunks), True

    openai_model, deployment, extra = _model_names(model)
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    azure_endpoint_raw = os.environ.get("AZURE_OPENAI_ENDPOINT", "") or os.environ.get(
        "AZURE_OPENAI_API_BASE", ""
    )
    azure_endpoint = _normalize_azure_endpoint(azure_endpoint_raw)
    if azure_endpoint != azure_endpoint_raw.rstrip("/"):
        global _AZURE_STRIP_WARNED
        if not _AZURE_STRIP_WARNED:
            logger.warning(
                "AZURE endpoint had /openai/deployments suffix; stripped "
                "defensively. Fix .env or your deploy values to avoid this."
            )
            _AZURE_STRIP_WARNED = True
    if azure_key and azure_endpoint:
        try:
            from openai import AzureOpenAI

            client = AzureOpenAI(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=os.environ.get(
                    "AZURE_OPENAI_API_VERSION", "2024-10-01-preview"
                ),
            )
            client.max_retries = 0
            out: list[list[float]] = []
            for i in range(0, len(chunks), BATCH_CHUNKS):
                batch = chunks[i : i + BATCH_CHUNKS]
                resp = _call_provider(
                    "azure",
                    batch,
                    lambda part=batch: client.embeddings.create(
                        input=part, model=deployment, **extra
                    ),
                )
                out.extend(item.embedding for item in resp.data)
            return out, True
        except Exception as exc:
            # Azure failed live — try OpenAI as a real fallback before giving
            # up. Mirrors the LLM ladder: provider quota or transport issues
            # on one side should never silently nuke the whole feature when
            # the other provider is still reachable.
            if OPENAI_API_KEY:
                logger.warning(
                    "Azure embedding call failed (%s); falling forward to OpenAI",
                    exc,
                )
            else:
                raise EmbeddingProviderCallFailed(str(exc), exc) from exc

    if OPENAI_API_KEY:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=OPENAI_API_KEY)
            # the SDK would sleep on its own and hide the Retry-After from the gate
            client.max_retries = 0
            embeddings: list[list[float]] = []
            for i in range(0, len(chunks), BATCH_CHUNKS):
                batch = chunks[i : i + BATCH_CHUNKS]
                response = _call_provider(
                    "openai",
                    batch,
                    lambda part=batch: client.embeddings.create(
                        model=openai_model, input=part, **extra
                    ),
                )
                for item in response.data:
                    embeddings.append(item.embedding)
            return embeddings, True
        except Exception as exc:
            raise EmbeddingProviderCallFailed(str(exc), exc) from exc

    # Nothing paid is configured. Rather than leave every collection empty on
    # a fresh clone, fall back to the local hashing embedder. It is lexical
    # rather than semantic and says so, but it makes knowledge_search return
    # the chunk that contains the words you typed instead of nothing at all.
    if _local_embeddings_enabled() and not strict:
        from local_embeddings import embed_many

        logger.warning(
            "No embedding provider configured — using the local hashing "
            "embedder (lexical, not semantic). Set OPENAI_API_KEY or "
            "AZURE_OPENAI_API_KEY for real semantic search, and re-ingest: "
            "vectors from the two schemes are not comparable."
        )
        return embed_many(chunks), True

    raise EmbeddingProviderError(
        "No embedding provider configured — set AZURE_OPENAI_API_KEY + "
        "AZURE_OPENAI_ENDPOINT or OPENAI_API_KEY, or set "
        "ABENIX_LOCAL_EMBEDDINGS=1 to use the offline hashing embedder"
    )


def _kb_settings(kb_id: str) -> tuple[str, str | None]:
    """(vector_backend, embedding_model) of the collection."""
    import psycopg2

    try:
        conn = psycopg2.connect(_sync_db_url())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vector_backend, embedding_model FROM knowledge_collections WHERE id = %s",
                    (kb_id,),
                )
                row = cur.fetchone()
                if not row:
                    return "pinecone", None
                return (row[0] or "pinecone"), (row[1] or None)
        finally:
            conn.close()
    except Exception:
        return "pinecone", None


def _kb_generation(kb_id: str) -> int | None:
    """The generation queries read, None when the collection is gone or being deleted."""
    import psycopg2

    try:
        conn = psycopg2.connect(_sync_db_url())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT embedding_generation FROM knowledge_collections "
                    "WHERE id = %s AND deleted_at IS NULL",
                    (kb_id,),
                )
                row = cur.fetchone()
                return int(row[0] or 0) if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("could not read the generation of %s: %s", kb_id, e)
        return 0


def _after_store(kb_id: str, doc_id: str, generation: int) -> None:
    """Drop rows a flip left behind and have a running re-embed take this text again."""
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND document_id = %s "
                "AND embedding_generation < %s",
                (kb_id, doc_id, generation),
            )
            cur.execute(
                "DELETE FROM kb_reembed_documents WHERE document_id = %s", (doc_id,)
            )
        conn.commit()
    finally:
        conn.close()


def _vector_backend_for(kb_id: str) -> str:
    """Return 'pinecone' or 'pgvector' based on the collection setting."""
    return _kb_settings(kb_id)[0]


def _chunk_meta(
    filename: str, i: int, chunk: str, pages: list[int | None] | None
) -> dict:
    meta = {"filename": filename, "chunk_index": i, "text_preview": chunk[:200]}
    if pages and i < len(pages) and pages[i] is not None:
        meta["page"] = pages[i]
    return meta


def _store_vectors_pgvector(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
    pages: list[int | None] | None = None,
    generation: int = 0,
    start: int = 0,
) -> int:
    """COPY a batch, and move the checkpoint in the same transaction."""
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT index_mode FROM knowledge_collections WHERE id = %s", (kb_id,)
            )
            row = cur.fetchone()
            dedicated = "t" if row and row[0] != "shared" else "f"
            lines = io.StringIO()
            for offset, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                i = start + offset
                # Postgres text and jsonb both refuse NUL, and binary files do hold it
                chunk = chunk.replace("\x00", "")
                page = [pages[offset] if pages and offset < len(pages) else None]
                meta = _chunk_meta(filename, 0, chunk, page)
                meta["chunk_index"] = i
                vector = "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
                lines.write(
                    f"{uuid.uuid4()}\t{kb_id}\t{doc_id}\t{i}\t{_copy_field(chunk)}\t"
                    f"{_copy_field(json.dumps(meta))}\t{vector}\t{dedicated}\t{generation}\n"
                )
            lines.seek(0)
            cur.copy_expert(
                "COPY chunks (id, collection_id, document_id, chunk_index, content, "
                "metadata, embedding, dedicated_index, embedding_generation) "
                "FROM STDIN WITH (FORMAT text)",
                lines,
            )
            cur.execute(
                "UPDATE documents SET ingest_checkpoint = %s, chunk_count = %s, "
                "ingest_attempts = 0 WHERE id = %s",
                (start + len(chunks), start + len(chunks), doc_id),
            )
        conn.commit()
        return len(chunks)
    finally:
        conn.close()


def _pinecone_vector(
    kb_id: str,
    doc_id: str,
    filename: str,
    i: int,
    chunk: str,
    embedding: list[float],
    pages: list[int | None] | None = None,
) -> dict:
    meta = {
        "kb_id": kb_id,
        "doc_id": doc_id,
        "filename": filename,
        "chunk_index": i,
        "text": chunk[:8000],
    }
    page = pages.get(i) if isinstance(pages, dict) else None
    if pages and not isinstance(pages, dict) and i < len(pages):
        page = pages[i]
    if page is not None:
        meta["page"] = page
    return {"id": f"{doc_id}_{i}", "values": embedding, "metadata": meta}


def _store_vectors_pinecone(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
    pages: list[int | None] | None = None,
    generation: int = 0,
    start: int = 0,
) -> int:
    from engine.knowledge.kb_state import pinecone_namespace
    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)
    namespace = pinecone_namespace(kb_id, generation)

    vectors = [
        _pinecone_vector(
            kb_id,
            doc_id,
            filename,
            start + i,
            chunk,
            embedding,
            {start + i: pages[i]} if pages and i < len(pages) else None,
        )
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings))
    ]

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=namespace)

    return len(vectors)


def _store_vectors(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
    pages: list[int | None] | None = None,
    backend: str | None = None,
    generation: int = 0,
    start: int = 0,
) -> int:
    """Dispatch to the collection's configured vector backend, with"""
    import logging

    log = logging.getLogger(__name__)
    backend = backend or _vector_backend_for(kb_id)

    if backend == "pgvector":
        try:
            return _store_vectors_pgvector(
                kb_id, doc_id, filename, chunks, embeddings, pages, generation, start
            )
        except Exception as e:
            log.warning(
                "pgvector store failed for kb=%s, falling back to Pinecone: %s",
                kb_id,
                e,
            )
            return _store_vectors_pinecone(
                kb_id, doc_id, filename, chunks, embeddings, pages, generation, start
            )

    # backend == "pinecone" (default for legacy collections).
    try:
        return _store_vectors_pinecone(
            kb_id, doc_id, filename, chunks, embeddings, pages, generation, start
        )
    except Exception as e:
        # Common failure: the Pinecone index doesn't exist in the tenant
        # account (404) or the API key is missing. pgvector is
        # guaranteed to be present on self-hosted installs — fall back
        # rather than lose the document.
        log.warning(
            "Pinecone store failed for kb=%s, falling back to pgvector: %s",
            kb_id,
            e,
        )
        return _store_vectors_pgvector(
            kb_id, doc_id, filename, chunks, embeddings, pages, generation, start
        )


def _update_document_status(
    doc_id: str,
    kb_id: str,
    status: str,
    chunk_count: int = 0,
    error_message: str | None = None,
    extraction_method: str | None = None,
    extraction_quality: float | None = None,
) -> None:
    import psycopg2

    db_status = status.upper()

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET status = %s, chunk_count = %s, error_message = %s, "
                "extraction_method = COALESCE(%s, extraction_method), "
                "extraction_quality = COALESCE(%s, extraction_quality) WHERE id = %s",
                (
                    db_status,
                    chunk_count,
                    error_message,
                    extraction_method,
                    extraction_quality,
                    doc_id,
                ),
            )
            # KB rollup: a single DEGRADED doc taints the whole collection —
            # the operator needs to know vectors are missing somewhere.
            # Once nothing's still PROCESSING, promote to READY.
            cur.execute(
                "SELECT status, COUNT(*) FROM documents WHERE kb_id = %s GROUP BY status",
                (kb_id,),
            )
            counts = {row[0]: row[1] for row in cur.fetchall()}
            ready_count = counts.get("READY", 0) + counts.get("DEGRADED", 0)
            cur.execute(
                "UPDATE knowledge_collections SET doc_count = %s WHERE id = %s",
                (ready_count, kb_id),
            )
            if counts.get("DEGRADED", 0) > 0:
                cur.execute(
                    "UPDATE knowledge_collections SET status = 'DEGRADED' WHERE id = %s",
                    (kb_id,),
                )
            elif counts.get("PROCESSING", 0) == 0:
                cur.execute(
                    "UPDATE knowledge_collections SET status = 'READY' WHERE id = %s",
                    (kb_id,),
                )
            conn.commit()
    finally:
        conn.close()


def _quota_refusal(kb_id: str, model: str | None, chunks: list[str]) -> str | None:
    """Why this document may not be indexed, checked before any money is spent."""
    try:
        import embedding_models as em
        import knowledge_quota as kq

        from worker.tasks import kb_quota

        _tokens, usd = em.estimated_cost(model, chunks)
        kb_quota.enforce_for_kb(kb_id, add_chunks=len(chunks), add_embedding_usd=usd)
    except ImportError:
        return None
    except kq.KnowledgeQuotaExceeded as e:
        return e.message
    except Exception as e:
        logger.warning("knowledge quota check failed for %s: %s", kb_id, e)
    return None


def _record_embedding_spend(kb_id: str, model: str | None, chunks: list[str]) -> None:
    try:
        import embedding_models as em

        from worker.tasks import kb_quota

        tokens, usd = em.estimated_cost(model, chunks)
        kb_quota.record_for_kb(kb_id, embedding_usd=usd, embedding_tokens=tokens)
    except Exception as e:
        logger.warning("embedding spend not recorded for %s: %s", kb_id, e)


@dataclass
class _IngestState:
    status: str
    attempts: int
    checkpoint: int
    fingerprint: str | None
    sha256: str | None


class _WaitForProvider(Exception):
    def __init__(self, cause: EmbeddingProviderCallFailed) -> None:
        super().__init__(str(cause))
        self.cause = cause


class _SettingsMoved(Exception):
    """A re-embed flipped the collection while this document was being stored."""


def _begin_ingest(doc_id: str) -> _IngestState | None:
    """Counted before any work, so a worker the kernel kills still leaves a mark."""
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET ingest_attempts = ingest_attempts + 1 "
                "WHERE id = %s RETURNING status::text, ingest_attempts, "
                "ingest_checkpoint, ingest_fingerprint, content_sha256",
                (doc_id,),
            )
            row = cur.fetchone()
        conn.commit()
        return _IngestState(*row) if row else None
    finally:
        conn.close()


def _forget_attempt(doc_id: str) -> None:
    """Waiting for a provider or another worker is not the document's fault."""
    _doc_update(
        "UPDATE documents SET ingest_attempts = GREATEST(ingest_attempts - 1, 0) "
        "WHERE id = %s",
        (doc_id,),
    )


def _doc_update(sql: str, params: tuple) -> None:
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


class _IngestLock:
    """Redelivery while the first run is alive must not write the same chunks twice."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.conn = None

    def acquire(self) -> bool:
        import psycopg2

        self.conn = psycopg2.connect(_sync_db_url())
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (f"kb_ingest:{self.doc_id}",),
            )
            return bool(cur.fetchone()[0])

    def release(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def _prepare_resume(
    kb_id: str, doc_id: str, start: int, fingerprint: str, generation: int
) -> None:
    """Anything past the checkpoint was never counted, and COPY has no ON CONFLICT."""
    import psycopg2

    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM chunks WHERE collection_id = %s AND document_id = %s "
                "AND embedding_generation = %s AND chunk_index >= %s",
                (kb_id, doc_id, generation, start),
            )
            cur.execute(
                "UPDATE documents SET ingest_checkpoint = %s, chunk_count = %s, "
                "ingest_fingerprint = %s WHERE id = %s",
                (start, start, fingerprint, doc_id),
            )
        conn.commit()
    finally:
        conn.close()


def _mark_checkpoint(doc_id: str, stored: int) -> None:
    _doc_update(
        "UPDATE documents SET ingest_checkpoint = %s, chunk_count = %s, "
        "ingest_attempts = 0 WHERE id = %s",
        (stored, stored, doc_id),
    )


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _content_problem(
    doc_id: str, kb_id: str, path: str, declared: str | None
) -> str | None:
    """A file sent straight to object storage is checked here, the API never saw its bytes."""
    import psycopg2

    actual = _file_sha256(path)
    if declared:
        if declared != actual:
            return (
                f"The uploaded file has hash {actual} but the client declared "
                f"{declared}. Upload it again."
            )
        return None
    conn = psycopg2.connect(_sync_db_url())
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id::text FROM documents WHERE kb_id = %s AND content_sha256 = %s "
                "AND is_current IS TRUE AND id <> %s LIMIT 1",
                (kb_id, actual, doc_id),
            )
            twin = cur.fetchone()
            if twin:
                return f"This file is already in the collection as document {twin[0]}."
            cur.execute(
                "UPDATE documents SET content_sha256 = %s WHERE id = %s",
                (actual, doc_id),
            )
        conn.commit()
    finally:
        conn.close()
    return None


def _document_blocks(path: str, file_type: str):
    """(blocks, info) streamed when the format allows, the whole file path otherwise."""
    from engine.knowledge.extractors.streaming import StreamInfo, iter_document

    try:
        streamed = iter_document(path, file_type)
    except ImportError:
        streamed = None
    except Exception:
        logger.exception("streaming extract could not open %s", path)
        streamed = None
    if streamed is not None:
        return streamed
    blocks, method, quality = _extract_blocks(path, file_type)
    info = StreamInfo(method or "unknown", quality or 0.0)
    return ((t, p, False) for t, p in blocks), info


def _batches(
    chunks: Iterator[tuple[str, int | None]], start: int
) -> Iterator[tuple[int, list[str], list[int | None]]]:
    """(index of the first chunk, texts, pages), skipping what the checkpoint already holds."""
    index = 0
    texts: list[str] = []
    pages: list[int | None] = []
    first = start
    for text, page in chunks:
        if index >= start:
            texts.append(text)
            pages.append(page)
            if len(texts) >= BATCH_CHUNKS:
                yield first, texts, pages
                first += len(texts)
                texts, pages = [], []
        index += 1
    if texts:
        yield first, texts, pages


def _fingerprint(generation: int, model: str | None, size: int, overlap: int) -> str:
    return f"{generation}|{model}|{size}|{overlap}"[:200]


def _queue_again(task, args: list, kwargs: dict, countdown: float = 0) -> None:
    task.apply_async(args=args, kwargs=kwargs, countdown=countdown, queue="documents")


@celery_app.task(
    bind=True,
    name="worker.tasks.document_processor.process_document",
    max_retries=2,
    default_retry_delay=30,
)
def process_document(
    self,
    doc_id: str,
    kb_id: str,
    file_path: str,
    filename: str,
    file_type: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
    verify_content: bool = False,
    waiting_since: float | None = None,
    strict: bool = False,
) -> dict:
    """Extract, chunk, embed and store in bounded batches, each one a checkpoint."""
    self.update_state(state="PROCESSING", meta={"doc_id": doc_id, "step": "extracting"})

    args = [doc_id, kb_id, file_path, filename, file_type, chunk_size, chunk_overlap]
    carry = {"verify_content": verify_content, "strict": strict}
    # read before the model, so a flip in between costs a repeat and never mixes them
    generation = _kb_generation(kb_id)
    if generation is None:
        return {"status": "skipped", "doc_id": doc_id, "error": "collection deleted"}

    state = _begin_ingest(doc_id)
    if state is None:
        return {"status": "skipped", "doc_id": doc_id, "error": "document deleted"}
    # a redelivered message after the work finished, or a document marked failed
    if state.status != "PROCESSING":
        return {"status": "skipped", "doc_id": doc_id, "error": state.status.lower()}
    if state.attempts > MAX_ATTEMPTS:
        reason = (
            f"The worker stopped {state.attempts - 1} times at chunk "
            f"{state.checkpoint} without storing anything more, so this document was "
            "given up on. The usual cause is the worker running out of memory. Give "
            "the worker more memory or split the file, then upload it again."
        )
        _update_document_status(
            doc_id, kb_id, "failed", state.checkpoint, error_message=reason
        )
        return {"status": "failed", "doc_id": doc_id, "error": reason}

    lock = _IngestLock(doc_id)
    if not lock.acquire():
        lock.release()
        _forget_attempt(doc_id)
        return {"status": "skipped", "doc_id": doc_id, "error": "already running"}

    started = time.monotonic()
    tmp_path: str | None = None
    stored = state.checkpoint
    progressed = False
    method: str | None = None
    quality: float | None = None
    try:
        actual_path, tmp_path = _local_path(file_path, file_type)
        if verify_content and state.checkpoint == 0:
            problem = _content_problem(doc_id, kb_id, actual_path, state.sha256)
            if problem:
                _update_document_status(
                    doc_id, kb_id, "failed", 0, error_message=problem
                )
                return {"status": "failed", "doc_id": doc_id, "error": problem}

        backend, model = _kb_settings(kb_id)
        fingerprint = _fingerprint(generation, model, chunk_size, chunk_overlap)
        start = state.checkpoint if state.fingerprint == fingerprint else 0
        _prepare_resume(kb_id, doc_id, start, fingerprint, generation)
        stored = start

        blocks, info = _document_blocks(actual_path, file_type)
        method, quality = info.method, info.quality
        self.update_state(
            state="PROCESSING", meta={"doc_id": doc_id, "step": "embedding"}
        )
        chunks = _iter_chunks(blocks, chunk_size, chunk_overlap)
        provider_note: str | None = None
        final_status = "ready"
        error_message: str | None = None
        pending: deque[tuple[int, list[str], list[int | None], str | None, Future]] = (
            deque()
        )

        def persist() -> bool:
            """Store the oldest finished batch. False stops the document where it is."""
            nonlocal model, provider_note, stored, progressed
            nonlocal final_status, error_message, fingerprint
            first, texts, pages, used, future = pending.popleft()
            try:
                vectors, real = future.result()
                _record_embedding_spend(kb_id, used, texts)
            except EmbeddingProviderCallFailed as exc:
                if not exc.refused:
                    raise _WaitForProvider(exc) from exc
                if used != model:
                    vectors, real = _embed_chunks(texts, model, strict=strict)
                else:
                    # only a refused key reaches the fallback, an outage waits
                    vectors, usable, model, provider_note = _after_provider_failure(
                        kb_id, doc_id, texts, exc, stored
                    )
                    real = usable
                    fingerprint = _fingerprint(
                        generation, model, chunk_size, chunk_overlap
                    )
                    if usable:
                        _prepare_resume(kb_id, doc_id, stored, fingerprint, generation)
            if not real:
                final_status = "degraded"
                error_message = provider_note or (
                    "embedding provider unavailable; vectors not stored, "
                    "document not searchable"
                )
                return False
            if len(vectors) != len(texts):
                raise RuntimeError("embedding provider returned a short batch")
            generation_now = _kb_generation(kb_id)
            if generation_now is None:
                raise _SettingsMoved("deleted")
            if generation_now != generation or _kb_settings(kb_id)[1] != model:
                raise _SettingsMoved("flipped")
            try:
                _store_vectors(
                    kb_id,
                    doc_id,
                    filename,
                    texts,
                    vectors,
                    pages,
                    backend,
                    generation=generation,
                    start=first,
                )
            except Exception as ve:
                # Embeddings are real but the vector store rejected them.
                logger.warning("vector store failed for %s: %s", doc_id, ve)
                final_status = "degraded"
                error_message = (
                    "vector store unavailable; vectors not stored, "
                    "document not searchable"
                )
                return False
            stored = first + len(texts)
            progressed = True
            _mark_checkpoint(doc_id, stored)
            return True

        def embed(texts: list[str], used: str | None):
            return _embed_chunks(texts, used, strict=strict)

        chunk_seen = start > 0
        stopped = False
        sliced = False
        with ThreadPoolExecutor(EMBED_CONCURRENCY) as pool:
            try:
                for first, texts, pages in _batches(chunks, start):
                    chunk_seen = True
                    refused = _quota_refusal(kb_id, model, texts)
                    if refused:
                        final_status, error_message = "failed", refused
                        stopped = True
                        break
                    pending.append(
                        (first, texts, pages, model, pool.submit(embed, texts, model))
                    )
                    while len(pending) >= EMBED_CONCURRENCY and not stopped:
                        stopped = not persist()
                    if stopped:
                        break
                    if time.monotonic() - started > SLICE_SECONDS:
                        sliced = True
                        break
                while pending and not stopped:
                    stopped = not persist()
            finally:
                for entry in pending:
                    entry[4].cancel()

        if sliced:
            _forget_attempt(doc_id)
            _queue_again(self, args, carry)
            return {"status": "continuing", "doc_id": doc_id, "vectors": stored}

        method, quality = info.method, info.quality
        if not chunk_seen:
            _update_document_status(
                doc_id,
                kb_id,
                "failed",
                0,
                error_message="No text could be extracted",
                extraction_method=method,
                extraction_quality=quality,
            )
            return {"status": "failed", "doc_id": doc_id, "error": "No text extracted"}

        if not stopped:
            if provider_note:
                final_status, error_message = "degraded", provider_note
            # a flip after the last batch is still a flip
            generation_now = _kb_generation(kb_id)
            if generation_now is None:
                raise _SettingsMoved("deleted")
            if generation_now != generation or _kb_settings(kb_id)[1] != model:
                raise _SettingsMoved("flipped")
            _after_store(kb_id, doc_id, generation)

        _update_document_status(
            doc_id,
            kb_id,
            final_status,
            stored,
            error_message=error_message,
            extraction_method=method,
            extraction_quality=quality,
        )
        logger.info(
            "Document %s processed: %d vectors stored, status=%s, extractor=%s",
            doc_id,
            stored,
            final_status,
            method,
        )
        return {
            "status": final_status,
            "doc_id": doc_id,
            "chunks": stored,
            "vectors": stored,
            "extraction_method": method,
            "error": error_message,
        }

    except _SettingsMoved as moved:
        if str(moved) == "deleted":
            return {
                "status": "skipped",
                "doc_id": doc_id,
                "error": "collection deleted",
            }
        _forget_attempt(doc_id)
        _queue_again(self, args, {**carry, "strict": True})
        return {"status": "restarted", "doc_id": doc_id, "vectors": 0}

    except _WaitForProvider as wait:
        _forget_attempt(doc_id)
        since = None if progressed else waiting_since
        since = since or time.time()
        if time.time() - since > MAX_WAIT_SECONDS:
            reason = (
                f"The embedding provider kept failing for {MAX_WAIT_SECONDS // 3600} "
                f"hours. {stored} chunks are stored and the rest are not, so this "
                f"document is only partly searchable. Upload it again to finish it. "
                f"Provider said {str(wait.cause)[:300]}"
            )
            _update_document_status(
                doc_id, kb_id, "failed", stored, error_message=reason
            )
            return {"status": "failed", "doc_id": doc_id, "error": reason}
        countdown = min(REQUEUE_WAIT_MAX, wait.cause.retry_after or 60.0)
        _doc_update(
            "UPDATE documents SET error_message = %s WHERE id = %s",
            (
                f"Waiting for the embedding provider, {stored} chunks stored so far. "
                f"Provider said {str(wait.cause)[:200]}",
                doc_id,
            ),
        )
        _queue_again(self, args, {**carry, "waiting_since": since}, countdown=countdown)
        return {"status": "waiting", "doc_id": doc_id, "vectors": stored}

    except SoftTimeLimitExceeded:
        _forget_attempt(doc_id)
        _queue_again(self, args, carry)
        return {"status": "continuing", "doc_id": doc_id, "vectors": stored}

    except Exception as exc:
        logger.exception("Failed to process document %s", doc_id)
        if self.request.retries >= self.max_retries:
            _update_document_status(
                doc_id, kb_id, "failed", stored, error_message=str(exc)[:500]
            )
        raise self.retry(exc=exc)
    finally:
        lock.release()
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
