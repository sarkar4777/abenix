"""Knowledge Search tool — hybrid vector + graph retrieval for agents."""

from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = (
        "Search the agent's knowledge base using hybrid retrieval that combines "
        "vector similarity with knowledge graph traversal. Returns results with "
        "relationship context, entity connections, and source provenance. "
        "Supports three modes: 'vector' (fast semantic search), 'graph' (relationship-based), "
        "or 'hybrid' (best quality — combines both). Use for complex questions that "
        "require understanding relationships between concepts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query — what information you're looking for",
            },
            "mode": {
                "type": "string",
                "enum": ["vector", "graph", "hybrid"],
                "description": "Search mode: vector (fast), graph (relationship-focused), hybrid (best quality)",
                "default": "hybrid",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        kb_ids: list[str],
        tenant_id: str = "",
        agent_id: str = "",
    ) -> None:
        self.kb_ids = kb_ids
        self.tenant_id = tenant_id
        self.agent_id = agent_id

    async def _filter_to_tenant(self, ids: list[str]) -> list[str]:
        """Re-validate that every kb_id is accessible to this agent."""
        if not ids or not self.tenant_id:
            return ids
        try:
            import os
            import uuid as _uuid
            from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
            from sqlalchemy import text

            db_url = (
                os.environ.get("DATABASE_URL")
                or os.environ.get("ASYNC_DATABASE_URL")
                or ""
            )
            if not db_url:
                return ids
            if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            # Materialise input as UUIDs; bad strings (e.g. legacy
            # subject-namespace strings like "example_app-<uuid>") are
            # passed through unchanged — those are not collection ids,
            # they're Pinecone-only namespaces that bypass the table.
            uuid_inputs: list[_uuid.UUID] = []
            passthrough: list[str] = []
            for s in ids:
                try:
                    uuid_inputs.append(_uuid.UUID(s))
                except (ValueError, AttributeError):
                    passthrough.append(s)
            if not uuid_inputs:
                return ids

            tenant_uuid = _uuid.UUID(self.tenant_id)
            agent_uuid: _uuid.UUID | None = None
            if self.agent_id:
                try:
                    agent_uuid = _uuid.UUID(self.agent_id)
                except (ValueError, AttributeError):
                    agent_uuid = None

            engine = create_async_engine(db_url, pool_pre_ping=True)
            try:
                async with AsyncSession(engine) as session:
                    # Gate 1: tenant match.
                    rows = (
                        await session.execute(
                            text(
                                "SELECT id FROM knowledge_collections "
                                "WHERE id = ANY(:ids) AND tenant_id = :tid"
                            ).bindparams(ids=uuid_inputs, tid=tenant_uuid)
                        )
                    ).all()
                    tenant_ok = {str(r[0]) for r in rows}

                    # Gate 2: agent grants (only when agent has ANY grants).
                    grant_ok: set[str] | None = None
                    if agent_uuid is not None:
                        g_rows = (
                            await session.execute(
                                text(
                                    "SELECT collection_id FROM agent_collection_grants "
                                    "WHERE agent_id = :aid"
                                ).bindparams(aid=agent_uuid)
                            )
                        ).all()
                        if g_rows:
                            grant_ok = {str(r[0]) for r in g_rows}
            finally:
                await engine.dispose()

            allowed = tenant_ok if grant_ok is None else (tenant_ok & grant_ok)
            return [s for s in ids if s in allowed] + passthrough
        except Exception:
            return ids

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        mode_str = arguments.get("mode", "hybrid")
        top_k = arguments.get("top_k", 5)

        try:
            from engine.knowledge.hybrid_search import hybrid_search, SearchMode

            mode = SearchMode(mode_str)
        except (ImportError, ValueError):
            # Fall back to vector-only if knowledge engine not available
            from engine.knowledge.hybrid_search import hybrid_search, SearchMode

            mode = SearchMode.VECTOR

        # v2 safeguard: re-check that every kb_id still belongs to this
        # tenant on every call. See `_filter_to_tenant` for rationale.
        validated_ids = await self._filter_to_tenant(self.kb_ids)

        # Structured warning when no collection is wired at all — agents
        # can branch on metadata.warning instead of guessing why hits=0.
        # Without this, every fresh deploy with un-seeded KBs returned a
        # silent empty response, and downstream agents (resolveai-policy-
        # research, resolveai-resolution-planner, claimsiq-policy-matcher)
        # produced zero citations / zero actions with no actionable signal.
        if not validated_ids:
            return ToolResult(
                content=(
                    "No knowledge base is configured for this agent. "
                    "Returning structured no-KB-configured signal so the "
                    "caller can fall back gracefully. "
                    "(query was: " + query[:120] + ")"
                ),
                metadata={
                    "warning": "no_kb_configured",
                    "status": "no_kb_configured",
                    "mode": mode_str,
                    "results": 0,
                    "hits": [],
                },
            )

        try:
            response = await hybrid_search(
                query=query,
                kb_ids=validated_ids,
                mode=mode,
                top_k=top_k,
                tenant_id=str(self.tenant_id) if self.tenant_id else "",
            )

            if not response.results:
                return ToolResult(
                    content=(
                        "No relevant results found in the knowledge base "
                        "for the given query. Collection(s) are wired and "
                        "reachable but produced 0 hits at the requested "
                        "top_k. The caller should treat this as 'searched, "
                        "found nothing' (NOT as 'KB not configured')."
                    ),
                    metadata={
                        "warning": "collection_empty_or_no_match",
                        "status": "no_match",
                        "mode": response.mode_used,
                        "results": 0,
                        "hits": [],
                        "kb_ids_searched": [str(x) for x in validated_ids],
                    },
                )

            # Format results for the LLM
            parts = [
                f"Knowledge Search Results ({response.mode_used} mode, {len(response.results)} results):"
            ]
            parts.append("")

            for i, r in enumerate(response.results, 1):
                source_label = f"[{r.source_type}]" if r.source_type != "chunk" else ""
                parts.append(
                    f"[{i}] (score: {r.score:.3f}, source: {r.source} {source_label})"
                )
                parts.append(r.content)
                if r.metadata.get("relationship_chain"):
                    parts.append(f"  Path: {r.metadata['relationship_chain']}")
                parts.append("")

            if response.entities_found:
                parts.append(
                    f"Entities identified: {', '.join(response.entities_found)}"
                )
            if response.graph_hops > 0:
                parts.append(f"Graph depth: {response.graph_hops} hops")

            content = "\n".join(parts)
            return ToolResult(
                content=content,
                metadata={
                    "mode": response.mode_used,
                    "results": len(response.results),
                    "vector_count": response.vector_results_count,
                    "graph_count": response.graph_results_count,
                    "entities": response.entities_found,
                    "latency_ms": response.latency_ms,
                },
            )

        except Exception as e:
            return ToolResult(content=f"Knowledge search error: {e}", is_error=True)
