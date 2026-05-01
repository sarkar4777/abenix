"""Knowledge Store tool — push content into the knowledge base from agents."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class KnowledgeStoreTool(BaseTool):
    name = "knowledge_store"
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

            embeddings = await self._embed_chunks(chunks)
            if embeddings:
                stored = await self._store_vectors(
                    kb_id, doc_id, title, chunks, embeddings, metadata
                )
                results["vector_indexed"] = True
                results["vectors_stored"] = stored
                logger.info(
                    "knowledge_store: indexed %d vectors for doc %s in kb %s",
                    stored,
                    doc_id,
                    kb_id,
                )
            else:
                results["vector_error"] = (
                    "No embeddings generated (check OPENAI_API_KEY)"
                )

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
                        config={"model": "claude-sonnet-4-5-20250929"},
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
                        "knowledge_store: cognified doc %s — %d entities, %d relationships",
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
        status = "stored" if results["vector_indexed"] else "partial"
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
            summary_parts.append(f"Vector store: failed — {results['vector_error']}")

        if run_cognify:
            if results["cognify_status"] == "complete":
                summary_parts.append(
                    f"Knowledge graph: {results.get('entities_extracted', 0)} entities, "
                    f"{results.get('relationships_written', 0)} relationships"
                )
            else:
                summary_parts.append(f"Knowledge graph: {results['cognify_status']}")

        return ToolResult(
            content="\n".join(summary_parts),
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

    @staticmethod
    async def _embed_chunks(chunks: list[str]) -> list[list[float]]:
        """Embed chunks using OpenAI API."""
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return []

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            embeddings = []
            batch_size = 100
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                response = client.embeddings.create(
                    model="text-embedding-3-small",
                    input=batch,
                )
                embeddings.extend([d.embedding for d in response.data])
            return embeddings
        except Exception as e:
            logger.warning("Embedding failed: %s", e)
            return []

    @staticmethod
    async def _store_vectors(
        kb_id: str,
        doc_id: str,
        title: str,
        chunks: list[str],
        embeddings: list[list[float]],
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store vectors in Pinecone."""
        try:
            from pinecone import Pinecone

            pc = Pinecone(api_key=os.environ.get("PINECONE_API_KEY", ""))
            index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")
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

            # Upsert in batches of 100
            for i in range(0, len(vectors), 100):
                index.upsert(vectors=vectors[i : i + 100], namespace=kb_id)

            return len(vectors)
        except Exception as e:
            logger.warning("Pinecone storage failed: %s", e)
            return 0
