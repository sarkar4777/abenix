"""RAG vector search tool - queries Pinecone for relevant document chunks."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ConfigField, ToolResult

EMBEDDING_MODEL = "text-embedding-3-small"


class VectorSearchTool(BaseTool):
    name = "vector_search"
    risk_tier = "low"
    config_fields = (
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
        ConfigField(
            "OPENAI_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="OpenAI",
            signup_url="https://platform.openai.com/api-keys",
        ),
    )
    description = (
        "Search the agent's knowledge base for relevant information. "
        "Returns the most relevant document chunks matching the query."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant documents",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(self, kb_ids: list[str]) -> None:
        self.kb_ids = kb_ids

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        top_k = arguments.get("top_k", 5)

        if not query.strip():
            return ToolResult(content="No query provided", is_error=True)

        if not self.cfg("PINECONE_API_KEY") or not self.cfg("OPENAI_API_KEY"):
            return ToolResult(
                content="Vector search not configured (missing API keys)",
                is_error=True,
            )

        if not self.kb_ids:
            return ToolResult(content="No knowledge bases attached", is_error=True)

        try:
            query_embedding = await self._embed_query(query)
        except Exception as e:
            return ToolResult(content=f"Embedding failed: {str(e)}", is_error=True)

        all_results: list[dict[str, Any]] = []
        for kb_id in self.kb_ids:
            try:
                results = self._search_pinecone(query_embedding, kb_id, top_k)
                all_results.extend(results)
            except Exception:
                continue

        from engine.knowledge.document_acl import superseded_for_search

        try:
            old_versions = await superseded_for_search(list(self.kb_ids))
        except Exception:
            old_versions = set()
        all_results = [r for r in all_results if r.get("doc_id") not in old_versions]

        if not all_results:
            return ToolResult(content="No relevant documents found.")

        all_results.sort(key=lambda r: r["score"], reverse=True)
        all_results = all_results[:top_k]

        output_parts = []
        for i, r in enumerate(all_results, 1):
            source = r.get("filename", "unknown")
            score = r.get("score", 0)
            text = r.get("text", "")
            output_parts.append(f"[{i}] (score: {score:.3f}, source: {source})\n{text}")

        return ToolResult(
            content="\n\n---\n\n".join(output_parts),
            metadata={"sources": [r.get("filename") for r in all_results]},
        )

    async def _embed_query(self, query: str) -> list[float]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.cfg("OPENAI_API_KEY"))
        response = await client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
        return response.data[0].embedding

    def _search_pinecone(
        self, embedding: list[float], namespace: str, top_k: int
    ) -> list[dict[str, Any]]:
        from pinecone import Pinecone

        pc = Pinecone(api_key=self.cfg("PINECONE_API_KEY"))
        index = pc.Index(self.cfg("PINECONE_INDEX_NAME"))

        response = index.query(
            vector=embedding,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True,
        )

        results = []
        for match in response.get("matches", []):
            meta = match.get("metadata", {})
            results.append(
                {
                    "score": match.get("score", 0),
                    "text": meta.get("text", ""),
                    "filename": meta.get("filename", ""),
                    "doc_id": meta.get("doc_id", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                }
            )

        return results
