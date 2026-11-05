"""Knowledge Store tool â€” push content into the knowledge base from agents."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from engine import credentials
from engine.tools.base import BaseTool, ConfigField, Effect, ToolResult

logger = logging.getLogger(__name__)


class KnowledgeStoreTool(BaseTool):
    name = "knowledge_store"
    risk_tier = "medium"
    effect = Effect(
        kind="write", label="Add a document to a knowledge base", reversible=True
    )
    config_fields = (
        ConfigField(
            "OPENAI_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="OpenAI",
            signup_url="https://platform.openai.com/api-keys",
        ),
        ConfigField(
            "PINECONE_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="Pinecone",
            signup_url="https://app.pinecone.io",
        ),
        ConfigField(
            "PINECONE_INDEX_NAME",
            label="Index name",
            kind="string",
            required=False,
            group="Pinecone",
            default="agentforge-knowledge",
        ),
    )
    description = (
        "Store content into the knowledge base for future retrieval. "
        "Use this to save extracted data, analysis results, documents, or any "
        "structured/unstructured text into the agent's knowledge base. "
        "Content is indexed for vector similarity search and optionally "
        "processed through Cognify to extract entities and relationships "
        "into the knowledge graph (Neo4j). "
        "Returns the document ID and indexing status."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text content to store in the knowledge base",
            },
            "title": {
                "type": "string",
                "description": "A descriptive title for this content (used as document name)",
            },
            "metadata": {
                "type": "object",
                "description": "Optional metadata to attach (e.g. source, type, tags)",
                "default": {},
            },
            "cognify": {
                "type": "boolean",
                "description": "Whether to also run Cognify to extract entities into the knowledge graph",
                "default": False,
            },
        },
        "required": ["content", "title"],
    }

    def __init__(self, kb_ids: list[str], tenant_id: str = "") -> None:
        self.kb_ids = kb_ids
        self.tenant_id = tenant_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content", "")
        title = arguments.get("title", "Untitled")
        metadata = arguments.get("metadata", {})
        run_cognify = arguments.get("cognify", False)

        if not content:
            return ToolResult(content="Error: content is required", is_error=True)
        if not self.kb_ids:
            return ToolResult(
                content="Error: no knowledge base configured for this agent",
                is_error=True,
            )

        kb_id = self.kb_ids[0]  # Use the first attached KB
        doc_id = str(uuid.uuid4())

        results = {
            "doc_id": doc_id,
            "kb_id": kb_id,
            "title": title,
            "content_length": len(content),
            "vector_indexed": False,
            "cognify_status": "skipped",
        }

        try:
            chunks = self._chunk_text(content)
            results["chunks"] = len(chunks)

            refused = await self._quota_refusal(kb_id, chunks, len(content))
            if refused:
                return ToolResult(content=refused, is_error=True)

            embeddings, note, backend = await self._embed_for_collection(kb_id, chunks)
            if note:
                results["warnings"] = [note]
            if embeddings:
                if backend == "pgvector":
                    stored = await self._store_vectors_pgvector(
                        kb_id, doc_id, title, chunks, embeddings, metadata
                    )
                else:
                    stored = await self._store_vectors(
                        kb_id, doc_id, title, chunks, embeddings, metadata
                    )
                results["vector_indexed"] = stored > 0
                results["vectors_stored"] = stored
                logger.info(
                    "knowledge_store: indexed %d vectors for doc %s in kb %s",
                    stored,
                    doc_id,
                    kb_id,
                )
            else:
                results["vector_error"] = note

        except Exception as e:
            logger.warning("knowledge_store vector indexing failed: %s", e)
            results["vector_error"] = str(e)

        if run_cognify:
            try:
                from engine.knowledge.cognify_pipeline import run_cognify
                from engine.knowledge.neo4j_client import is_neo4j_available

                if await is_neo4j_available():
                    cognify_doc = {
                        "id": doc_id,
                        "filename": title,
                        "chunks": (
                            chunks if "chunks" in dir() else self._chunk_text(content)
                        ),
                    }

                    cognify_result = await run_cognify(
                        kb_id=kb_id,
                        tenant_id=self.tenant_id,
                        job_id=str(uuid.uuid4()),
                        documents=[cognify_doc],
                        config={},
                        db_url=os.environ.get("DATABASE_URL", ""),
                    )

                    results["cognify_status"] = cognify_result.status
                    results["entities_extracted"] = (
                        cognify_result.entities_after_resolution
                    )
                    results["relationships_written"] = (
                        cognify_result.relationships_written
                    )
                    logger.info(
                        "knowledge_store: cognified doc %s â€” %d entities, %d relationships",
                        doc_id,
                        cognify_result.entities_after_resolution,
                        cognify_result.relationships_written,
                    )
                else:
                    results["cognify_status"] = "skipped"
                    results["cognify_error"] = "Neo4j unavailable"
            except Exception as e:
                logger.warning("knowledge_store cognify failed: %s", e)
                results["cognify_status"] = "error"
                results["cognify_error"] = str(e)

        # Format output
        status = "stored" if results["vector_indexed"] else "not indexed"
        summary_parts = [f"Content '{title}' {status} in knowledge base {kb_id}."]
        summary_parts.append(f"Document ID: {doc_id}")
        summary_parts.append(
            f"Content length: {len(content)} characters, {results.get('chunks', 0)} chunks"
        )

        if results["vector_indexed"]:
            summary_parts.append(
                f"Vector store: {results.get('vectors_stored', 0)} embeddings indexed"
            )
        elif results.get("vector_error"):
            summary_parts.append(f"Vector store: failed â€” {results['vector_error']}")

        if run_cognify:
            if results["cognify_status"] == "complete":
                summary_parts.append(
                    f"Knowledge graph: {results.get('entities_extracted', 0)} entities, "
                    f"{results.get('relationships_written', 0)} relationships"
                )
            else:
                summary_parts.append(f"Knowledge graph: {results['cognify_status']}")

        if results.get("warnings"):
            summary_parts.extend(results["warnings"])

        return ToolResult(
            content="\n".join(summary_parts),
            is_error=not results["vector_indexed"],
            metadata=results,
        )

    @staticmethod
    def _chunk_text(
        text: str, chunk_size: int = 1000, chunk_overlap: int = 200
    ) -> list[str]:
        """Chunk text using simple sliding window (no langchain dependency)."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start += chunk_size - chunk_overlap
        return chunks or [text]

    async def _embed_for_collection(
        self, kb_id: str, chunks: list[str]
    ) -> tuple[list[list[float]] | None, str | None, str]:
        """(vectors, message for the caller, vector backend) under the worker's failure rule."""
        from engine.knowledge import hybrid_search as hs

        settings = await hs._kb_index_settings([kb_id])
        backend, model = settings.get(kb_id, ("pinecone", None))
        try:
            vectors = await hs.embed_for_collection(chunks, model)
        except Exception as exc:
            logger.warning("knowledge_store embedding failed for %s: %s", kb_id, exc)
            vectors, note = await self._after_provider_failure(kb_id, chunks, exc)
            return vectors, note, backend
        if not vectors:
            return (
                None,
                "No embedding provider is configured, so nothing was indexed. Set "
                "OPENAI_API_KEY, or ABENIX_LOCAL_EMBEDDINGS=1 for the local embedder.",
                backend,
            )
        return vectors, None, backend

    async def _after_provider_failure(
        self, kb_id: str, chunks: list[str], exc: Exception
    ) -> tuple[list[list[float]] | None, str]:
        from local_embeddings import MODEL_ID, embed_many, is_forced_off

        reason = str(exc)[:300]
        if is_forced_off() or not await self._move_empty_to_local(kb_id, MODEL_ID):
            return None, (
                "The embedding provider failed and no vectors were stored, so this "
                f"content cannot be searched. Provider said {reason}"
            )
        return embed_many(chunks), (
            "The embedding provider failed, so this content was indexed with the "
            "local hashing embedder, which matches words and not meaning. Fix the "
            f"provider and re-embed the collection. Provider said {reason}"
        )

    @staticmethod
    async def _quota_refusal(kb_id: str, chunks: list[str], size: int) -> str | None:
        """The tenant's knowledge limits apply to what an agent stores too."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine
        from engine.knowledge.hybrid_search import _async_db_url

        try:
            import embedding_models as em
            import knowledge_quota as kq
        except ImportError:
            return None
        url = _async_db_url()
        if not url:
            return None
        try:
            async with AsyncSession(shared_engine(url)) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT tenant_id, embedding_model FROM knowledge_collections "
                            "WHERE id = CAST(:k AS uuid)"
                        ),
                        {"k": kb_id},
                    )
                ).first()
                if row is None:
                    return None
                tenant = {"t": str(row[0])}
                limits = (
                    await session.execute(
                        text(kq.LIMITS_SQL.format(t="CAST(:t AS uuid)")), tenant
                    )
                ).first()
                if limits is None:
                    return None
                docs, count, stored = (
                    await session.execute(
                        text(kq.USAGE_SQL.format(t="CAST(:t AS uuid)")), tenant
                    )
                ).one()
                emb, cog, tokens = (
                    await session.execute(
                        text(kq.SPEND_SQL.format(t="CAST(:t AS uuid)", p=":p")),
                        {**tenant, "p": kq.period_start()},
                    )
                ).one()
        except Exception as exc:
            logger.warning("knowledge_store quota check failed: %s", exc)
            return None
        _tokens, usd = em.estimated_cost(row[1], chunks)
        try:
            kq.check(
                dict(zip(kq.LIMIT_KEYS, limits)),
                kq.Usage(
                    documents=int(docs),
                    chunks=int(count),
                    storage_bytes=int(stored),
                    embedding_usd=float(emb),
                    cognify_usd=float(cog),
                    embedding_tokens=int(tokens),
                ),
                add_documents=1,
                add_chunks=len(chunks),
                add_bytes=size,
                add_embedding_usd=usd,
            )
        except kq.KnowledgeQuotaExceeded as e:
            return e.message
        return None

    @staticmethod
    async def _move_empty_to_local(kb_id: str, model: str) -> bool:
        """True when the collection held no vectors and now records the local embedder."""
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine
        from engine.knowledge.hybrid_search import _async_db_url

        try:
            async with AsyncSession(shared_engine(_async_db_url())) as session:
                moved = await session.execute(
                    text(
                        "UPDATE knowledge_collections "
                        "SET embedding_model = :m, status = 'DEGRADED' "
                        "WHERE id = CAST(:id AS uuid) AND NOT EXISTS ("
                        "SELECT 1 FROM documents d WHERE d.kb_id = knowledge_collections.id "
                        "AND d.status IN ('READY', 'DEGRADED') AND d.chunk_count > 0) "
                        "AND NOT EXISTS (SELECT 1 FROM chunks c "
                        "WHERE c.collection_id = knowledge_collections.id)"
                    ),
                    {"m": model, "id": kb_id},
                )
                await session.commit()
                return moved.rowcount > 0
        except Exception as exc:
            logger.warning("knowledge_store could not record the embedder %s", exc)
            return False

    @staticmethod
    async def _store_vectors_pgvector(
        kb_id: str,
        doc_id: str,
        title: str,
        chunks: list[str],
        embeddings: list[list[float]],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        import json

        from sqlalchemy import text
        from engine.db_pool import shared_engine

        async with shared_engine(os.environ.get("DATABASE_URL", "")).begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO documents (id, kb_id, filename, file_type, "
                    "file_size, chunk_count, status, storage_url, version_number, is_current) VALUES "
                    "(:id, :kb, :name, 'text', :size, :count, 'READY', :url, 1, true)"
                ),
                {
                    "id": doc_id,
                    "kb": kb_id,
                    "name": title[:500],
                    "size": sum(len(c) for c in chunks),
                    "count": len(chunks),
                    "url": f"agent://knowledge_store/{doc_id}",
                },
            )
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                await conn.execute(
                    text(
                        "INSERT INTO chunks (id, collection_id, document_id, "
                        "chunk_index, content, metadata, embedding, "
                        "embedding_generation, dedicated_index) VALUES (:id, "
                        ":kb, :doc, :i, :content, CAST(:meta AS jsonb), "
                        "CAST(:emb AS vector), (SELECT embedding_generation "
                        "FROM knowledge_collections WHERE id = CAST(:kb AS uuid)), "
                        "(SELECT index_mode <> 'shared' FROM knowledge_collections "
                        "WHERE id = CAST(:kb AS uuid)))"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "kb": kb_id,
                        "doc": doc_id,
                        "i": i,
                        "content": chunk,
                        "meta": json.dumps(
                            {
                                "filename": title,
                                "chunk_index": i,
                                **(metadata or {}),
                            }
                        ),
                        "emb": "[" + ",".join(f"{x:.7f}" for x in emb) + "]",
                    },
                )
        return len(chunks)

    @staticmethod
    async def _store_vectors(
        kb_id: str,
        doc_id: str,
        title: str,
        chunks: list[str],
        embeddings: list[list[float]],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store vectors in Pinecone, a failure reaches the caller."""
        from pinecone import Pinecone

        pc = Pinecone(api_key=credentials.get("PINECONE_API_KEY"))
        index_name = credentials.get(
            "PINECONE_INDEX_NAME", default="agentforge-knowledge"
        )
        index = pc.Index(index_name)

        vectors = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            vec_meta = {
                "kb_id": kb_id,
                "doc_id": doc_id,
                "filename": title,
                "chunk_index": i,
                "text": chunk[:1000],  # Pinecone metadata limit
            }
            if metadata:
                vec_meta.update({k: str(v)[:200] for k, v in metadata.items()})
            vectors.append(
                {
                    "id": f"{doc_id}_{i}",
                    "values": emb,
                    "metadata": vec_meta,
                }
            )

        from engine.knowledge.kb_state import live_generations, pinecone_namespace

        generations = await live_generations([kb_id])
        namespace = pinecone_namespace(kb_id, (generations or {}).get(kb_id, 0))
        # Upsert in batches of 100
        for i in range(0, len(vectors), 100):
            index.upsert(vectors=vectors[i : i + 100], namespace=namespace)

        return len(vectors)
