"""Celery task: process uploaded documents for RAG.

Pipeline: detect type -> extract text -> chunk -> embed -> store in Pinecone -> update DB.
"""

import logging
import os
from pathlib import Path

from worker.celery_app import celery_app

logger = logging.getLogger(__name__)

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY", "")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


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


def _extract_text(file_path: str, file_type: str) -> str:
    path = Path(_strip_file_scheme(file_path))
    ft = file_type.lower()

    if ft in ("pdf", "application/pdf"):
        from PyPDF2 import PdfReader

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

    if ft in ("csv", "text/csv"):
        return path.read_text(encoding="utf-8", errors="replace")

    return path.read_text(encoding="utf-8", errors="replace")


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


def _embed_chunks(chunks: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    embeddings: list[list[float]] = []

    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        for item in response.data:
            embeddings.append(item.embedding)

    return embeddings


def _vector_backend_for(kb_id: str) -> str:
    """Return 'pinecone' or 'pgvector' based on the collection setting."""
    import psycopg2

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
    )
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")
    try:
        conn = psycopg2.connect(sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vector_backend FROM knowledge_collections WHERE id = %s",
                    (kb_id,),
                )
                row = cur.fetchone()
                return (row[0] if row and row[0] else "pinecone") or "pinecone"
        finally:
            conn.close()
    except Exception:
        return "pinecone"


def _store_vectors_pgvector(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """Insert chunks + embeddings directly into Postgres (pgvector)."""
    import json as _json
    import uuid as _uuid
    import psycopg2

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
    )
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")

    conn = psycopg2.connect(sync_url)
    try:
        with conn.cursor() as cur:
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                metadata = {
                    "filename": filename,
                    "chunk_index": i,
                    "text_preview": chunk[:200],
                }
                # pgvector accepts string-formatted arrays: '[0.1, 0.2, ...]'
                emb_str = "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"
                cur.execute(
                    """
                    INSERT INTO chunks
                        (id, collection_id, document_id, chunk_index, content,
                         metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                    ON CONFLICT (document_id, chunk_index)
                    DO UPDATE SET content = EXCLUDED.content,
                                  metadata = EXCLUDED.metadata,
                                  embedding = EXCLUDED.embedding
                    """,
                    (
                        str(_uuid.uuid4()),
                        kb_id,
                        doc_id,
                        i,
                        chunk,
                        _json.dumps(metadata),
                        emb_str,
                    ),
                )
            conn.commit()
            return len(embeddings)
    finally:
        conn.close()


def _store_vectors_pinecone(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    from pinecone import Pinecone

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    vectors = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        vector_id = f"{doc_id}_{i}"
        vectors.append(
            {
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "filename": filename,
                    "chunk_index": i,
                    "text": chunk[:8000],
                },
            }
        )

    batch_size = 100
    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        index.upsert(vectors=batch, namespace=kb_id)

    return len(vectors)


def _store_vectors(
    kb_id: str,
    doc_id: str,
    filename: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """Dispatch to the collection's configured vector backend, with"""
    import logging

    log = logging.getLogger(__name__)
    backend = _vector_backend_for(kb_id)

    if backend == "pgvector":
        try:
            return _store_vectors_pgvector(kb_id, doc_id, filename, chunks, embeddings)
        except Exception as e:
            log.warning(
                "pgvector store failed for kb=%s, falling back to Pinecone: %s",
                kb_id,
                e,
            )
            return _store_vectors_pinecone(kb_id, doc_id, filename, chunks, embeddings)

    # backend == "pinecone" (default for legacy collections).
    try:
        return _store_vectors_pinecone(kb_id, doc_id, filename, chunks, embeddings)
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
        return _store_vectors_pgvector(kb_id, doc_id, filename, chunks, embeddings)


def _update_document_status(
    doc_id: str, kb_id: str, status: str, chunk_count: int = 0
) -> None:
    import psycopg2

    db_url = os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
    )
    sync_url = db_url.replace("+asyncpg", "").replace(
        "postgresql+asyncpg", "postgresql"
    )
    # asyncpg accepts `?ssl=...` but psycopg2 rejects it — strip the ssl query
    # params (and sslmode if invalid) so the sync connection succeeds.
    if "?" in sync_url:
        base, query = sync_url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        sync_url = base + (("?" + "&".join(kept)) if kept else "")

    db_status = status.upper()

    conn = psycopg2.connect(sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE documents SET status = %s, chunk_count = %s WHERE id = %s",
                (db_status, chunk_count, doc_id),
            )
            if status == "ready":
                cur.execute(
                    "UPDATE knowledge_collections SET doc_count = ("
                    "  SELECT COUNT(*) FROM documents WHERE kb_id = %s AND status = 'READY'"
                    "), status = 'READY' WHERE id = %s",
                    (kb_id, kb_id),
                )
            elif status == "failed":
                remaining = 0
                cur.execute(
                    "SELECT COUNT(*) FROM documents WHERE kb_id = %s AND status = 'PROCESSING'",
                    (kb_id,),
                )
                row = cur.fetchone()
                if row:
                    remaining = row[0]
                if remaining == 0:
                    cur.execute(
                        "UPDATE knowledge_collections SET status = 'READY' WHERE id = %s",
                        (kb_id,),
                    )
            conn.commit()
    finally:
        conn.close()


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
) -> dict:
    """Process a single document: extract -> chunk -> embed -> store."""
    self.update_state(state="PROCESSING", meta={"doc_id": doc_id, "step": "extracting"})

    try:
        # Download from StorageService if URI (s3://, az://), otherwise use local path
        actual_path = file_path
        if (
            file_path.startswith("s3://")
            or file_path.startswith("az://")
            or file_path.startswith("file://")
        ):
            import asyncio
            import tempfile

            try:
                from engine.storage import get_storage

                storage = get_storage()
                loop = asyncio.new_event_loop()
                data = loop.run_until_complete(storage.download(file_path))
                loop.close()
                # Write to temp file for extraction
                suffix = f".{file_type}" if file_type else ""
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(data)
                tmp.close()
                actual_path = tmp.name
            except Exception as e:
                logger.warning(
                    "StorageService download failed, trying direct path: %s", e
                )

        text = _extract_text(actual_path, file_type)
        if not text.strip():
            _update_document_status(doc_id, kb_id, "failed", 0)
            return {"status": "failed", "doc_id": doc_id, "error": "No text extracted"}

        self.update_state(
            state="PROCESSING", meta={"doc_id": doc_id, "step": "chunking"}
        )
        chunks = _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        if not chunks:
            _update_document_status(doc_id, kb_id, "failed", 0)
            return {"status": "failed", "doc_id": doc_id, "error": "No chunks produced"}

        self.update_state(
            state="PROCESSING",
            meta={"doc_id": doc_id, "step": "embedding", "chunks": len(chunks)},
        )
        embeddings = _embed_chunks(chunks)

        self.update_state(
            state="PROCESSING", meta={"doc_id": doc_id, "step": "storing"}
        )
        stored = _store_vectors(kb_id, doc_id, filename, chunks, embeddings)

        _update_document_status(doc_id, kb_id, "ready", stored)

        logger.info(
            "Document %s processed: %d chunks, %d vectors stored",
            doc_id,
            len(chunks),
            stored,
        )

        return {
            "status": "ready",
            "doc_id": doc_id,
            "chunks": len(chunks),
            "vectors": stored,
        }

    except Exception as exc:
        logger.exception("Failed to process document %s", doc_id)
        _update_document_status(doc_id, kb_id, "failed", 0)
        raise self.retry(exc=exc)
