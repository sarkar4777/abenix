"""Hybrid Search Engine — combines vector similarity with knowledge graph traversal"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.knowledge.neo4j_client import get_neo4j_driver, is_neo4j_available
from engine.knowledge.prompts import SEARCH_ENTITY_EXTRACTION

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    VECTOR = "vector"
    GRAPH = "graph"
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    content: str
    score: float
    source: str  # filename or entity name
    source_type: str  # "chunk", "entity", "relationship", "graph_context"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HybridSearchResponse:
    results: list[SearchResult]
    mode_used: str
    vector_results_count: int = 0
    graph_results_count: int = 0
    entities_found: list[str] = field(default_factory=list)
    graph_hops: int = 0
    latency_ms: int = 0


async def hybrid_search(
    query: str,
    kb_ids: list[str],
    mode: SearchMode = SearchMode.HYBRID,
    top_k: int = 10,
    graph_depth: int = 2,
    graph_weight: float = 0.4,
    tenant_id: str = "",
    use_cache: bool = True,
) -> HybridSearchResponse:
    """Execute hybrid search across vector store and knowledge graph."""
    import time
    start = time.monotonic()

    # KB v2 query cache (5-min TTL). Best-effort: redis miss/failure
    # falls through to live search.
    from engine.knowledge import search_cache
    cache_k: str | None = None
    if use_cache and tenant_id and kb_ids:
        cache_k = search_cache.cache_key(
            tenant_id=tenant_id, kb_ids=kb_ids,
            query=query, mode=mode.value, top_k=top_k,
        )
        cached = await search_cache.get(cache_k)
        if cached:
            try:
                resp = HybridSearchResponse(
                    results=[SearchResult(**r) for r in cached.get("results", [])],
                    mode_used=cached.get("mode_used", mode.value),
                    vector_results_count=cached.get("vector_results_count", 0),
                    graph_results_count=cached.get("graph_results_count", 0),
                    entities_found=cached.get("entities_found", []),
                    graph_hops=cached.get("graph_hops", 0),
                    latency_ms=int((time.monotonic() - start) * 1000),
                )
                return resp
            except Exception:
                # Schema drift on cached blob — ignore and recompute.
                pass

    response = HybridSearchResponse(results=[], mode_used=mode.value)

    vector_results: list[SearchResult] = []
    if mode in (SearchMode.VECTOR, SearchMode.HYBRID):
        vector_results = await _vector_search(query, kb_ids, top_k=top_k * 2)
        response.vector_results_count = len(vector_results)

    graph_results: list[SearchResult] = []
    graph_entities: list[str] = []

    if mode in (SearchMode.GRAPH, SearchMode.HYBRID) and await is_neo4j_available():
        # Extract entity mentions from the query
        query_entities = await _extract_query_entities(query)
        response.entities_found = query_entities

        if query_entities:
            graph_results, graph_entities = await _graph_search(
                query_entities, kb_ids, depth=graph_depth,
            )
            response.graph_results_count = len(graph_results)
            response.graph_hops = graph_depth

    if mode == SearchMode.VECTOR:
        response.results = vector_results[:top_k]
    elif mode == SearchMode.GRAPH:
        response.results = graph_results[:top_k]
    else:
        # Hybrid: combine and re-rank
        merged = _merge_results(vector_results, graph_results, graph_weight)
        response.results = merged[:top_k]

    response.latency_ms = int((time.monotonic() - start) * 1000)

    # Stash in cache (best-effort). Only cache hits with results to
    # avoid burning Redis on empty-corpus misses.
    if cache_k and response.results:
        try:
            await search_cache.set(cache_k, {
                "results": [
                    {
                        "content": r.content, "score": r.score,
                        "source": r.source, "source_type": r.source_type,
                        "metadata": r.metadata,
                    } for r in response.results
                ],
                "mode_used": response.mode_used,
                "vector_results_count": response.vector_results_count,
                "graph_results_count": response.graph_results_count,
                "entities_found": response.entities_found,
                "graph_hops": response.graph_hops,
            })
        except Exception:
            pass
    return response


async def _classify_kb_backends(kb_ids: list[str]) -> dict[str, str]:
    """Look up vector_backend per kb in one round-trip."""
    if not kb_ids:
        return {}
    try:
        import os
        import uuid as _uuid
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy import text as _t
        db_url = (
            os.environ.get("DATABASE_URL")
            or os.environ.get("ASYNC_DATABASE_URL")
            or ""
        )
        if not db_url:
            return {kb: "pinecone" for kb in kb_ids}
        if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        # Filter out non-UUID strings (legacy subject-namespace hack)
        # — those can't be in knowledge_collections anyway.
        uuid_inputs: list[_uuid.UUID] = []
        passthrough: list[str] = []
        for s in kb_ids:
            try:
                uuid_inputs.append(_uuid.UUID(s))
            except (ValueError, AttributeError):
                passthrough.append(s)
        result: dict[str, str] = {p: "pinecone" for p in passthrough}
        if not uuid_inputs:
            return result
        engine = create_async_engine(db_url, pool_pre_ping=True)
        async with AsyncSession(engine) as session:
            rows = (await session.execute(_t(
                "SELECT id::text, vector_backend FROM knowledge_collections "
                "WHERE id = ANY(:ids)"
            ).bindparams(ids=uuid_inputs))).all()
        await engine.dispose()
        for r in rows:
            result[r[0]] = r[1] or "pinecone"
        return result
    except Exception:
        return {kb: "pinecone" for kb in kb_ids}


async def _vector_search_pgvector(
    query: str, kb_ids: list[str], top_k: int,
) -> list[SearchResult]:
    """Vector search via Postgres+pgvector for collections opted into it."""
    try:
        import os
        from openai import AsyncOpenAI
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy import text as _t

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return []
        client = AsyncOpenAI(api_key=api_key)
        embedding_resp = await client.embeddings.create(
            model="text-embedding-3-small", input=query,
        )
        emb = embedding_resp.data[0].embedding
        emb_str = "[" + ",".join(f"{x:.7f}" for x in emb) + "]"

        db_url = (
            os.environ.get("DATABASE_URL")
            or os.environ.get("ASYNC_DATABASE_URL")
            or ""
        )
        if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(db_url, pool_pre_ping=True)
        results: list[SearchResult] = []
        async with AsyncSession(engine) as session:
            rows = (await session.execute(_t(
                """
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       1 - (embedding <=> :emb::vector) AS score
                FROM chunks
                WHERE collection_id = ANY(:ids)
                ORDER BY embedding <=> :emb::vector
                LIMIT :k
                """
            ).bindparams(emb=emb_str, ids=kb_ids, k=top_k))).all()
        await engine.dispose()
        for r in rows:
            meta = r[5] or {}
            filename = meta.get("filename") if isinstance(meta, dict) else "unknown"
            results.append(SearchResult(
                content=r[4],
                score=float(r[6]),
                source=filename or "unknown",
                source_type="chunk",
                metadata={
                    "kb_id": r[1],
                    "doc_id": r[2],
                    "chunk_index": r[3],
                    "backend": "pgvector",
                },
            ))
        return results
    except Exception as e:
        logger.error("pgvector search failed: %s", e)
        return []


async def _vector_search(query: str, kb_ids: list[str], top_k: int = 20) -> list[SearchResult]:
    """Perform vector similarity search across kb_ids."""
    backends = await _classify_kb_backends(kb_ids)
    pgv_ids = [k for k in kb_ids if backends.get(k) == "pgvector"]
    pin_ids = [k for k in kb_ids if backends.get(k) != "pgvector"]

    pgv_results: list[SearchResult] = []
    if pgv_ids:
        pgv_results = await _vector_search_pgvector(query, pgv_ids, top_k)
    if not pin_ids:
        return pgv_results

    try:
        import os
        from openai import AsyncOpenAI
        from pinecone import Pinecone

        api_key = os.environ.get("OPENAI_API_KEY", "")
        pinecone_key = os.environ.get("PINECONE_API_KEY", "")
        index_name = os.environ.get("PINECONE_INDEX_NAME", "abenix-knowledge")

        if not api_key or not pinecone_key:
            return pgv_results
        kb_ids = pin_ids  # rest of the function operates on Pinecone-only set

        # Embed query
        client = AsyncOpenAI(api_key=api_key)
        embedding_resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        query_vector = embedding_resp.data[0].embedding

        # Search across all KB namespaces (Pinecone v7+ returns structured objects)
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

        results: list[SearchResult] = []
        for kb_id in kb_ids:
            _filter = {"persona_scope": {"$ne": "_persona_"}}
            try:
                response = index.query(
                    namespace=kb_id,
                    vector=query_vector,
                    top_k=top_k,
                    include_metadata=True,
                    filter=_filter,
                )
            except Exception:
                # Some Pinecone index versions reject the filter silently;
                # retry once unfiltered, then re-filter in memory.
                response = index.query(
                    namespace=kb_id,
                    vector=query_vector,
                    top_k=top_k,
                    include_metadata=True,
                )
            # Pinecone v7 returns QueryResponse with .matches attribute
            matches = getattr(response, 'matches', None) or response.get("matches", []) if isinstance(response, dict) else []
            for m in matches:
                meta = getattr(m, 'metadata', None) or (m.get("metadata", {}) if isinstance(m, dict) else {})
                # Defense-in-depth: drop any persona chunk that made it past
                # the Pinecone filter (e.g. older SDK ignored the filter
                # arg). Generic search must NEVER surface persona data.
                if isinstance(meta, dict) and meta.get("persona_scope"):
                    continue
                score = getattr(m, 'score', None) or (m.get("score", 0.0) if isinstance(m, dict) else 0.0)
                results.append(SearchResult(
                    content=meta.get("text", "") if isinstance(meta, dict) else str(meta),
                    score=float(score),
                    source=meta.get("filename", "unknown") if isinstance(meta, dict) else "unknown",
                    source_type="chunk",
                    metadata={
                        "kb_id": kb_id,
                        "doc_id": meta.get("doc_id", "") if isinstance(meta, dict) else "",
                        "chunk_index": meta.get("chunk_index", 0),
                    },
                ))

        # Merge pgvector results from collections that opted in
        # before sort, so the top_k cut sees both backends together.
        results.extend(pgv_results)
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    except Exception as e:
        logger.error("Vector search failed: %s", e)
        # Even on Pinecone failure, return whatever pgvector found.
        return pgv_results


async def _extract_query_entities(query: str) -> list[str]:
    """Use LLM to extract entity names from a search query."""
    try:
        from engine.llm_router import LLMRouter
        llm = LLMRouter()

        prompt = SEARCH_ENTITY_EXTRACTION.format(query=query)
        response = await llm.complete(
            messages=[{"role": "user", "content": prompt}],
            system="Extract entity names. Return only a JSON array.",
            model="claude-haiku-3-5-20241022",  # Fast model for extraction
            temperature=0.0,
        )

        text = response.content.strip()
        if "[" in text:
            entities = json.loads(text[text.index("["):text.rindex("]") + 1])
            return [e for e in entities if isinstance(e, str)]
    except Exception as e:
        logger.debug("Query entity extraction failed: %s", e)

    # Fallback: split query into significant words (>3 chars, capitalized)
    words = query.split()
    return [w for w in words if len(w) > 3 and w[0].isupper()]


async def _graph_search(
    entity_names: list[str],
    kb_ids: list[str],
    depth: int = 2,
) -> tuple[list[SearchResult], list[str]]:
    """Search the knowledge graph for entities and their relationships.

    Returns: (search_results, found_entity_names)
    """
    driver = await get_neo4j_driver()
    results: list[SearchResult] = []
    found_entities: list[str] = []

    async with driver.session() as session:
        for kb_id in kb_ids:
            # Find matching entities (exact or alias match)
            entity_match = await session.run(
                """
                MATCH (e:Entity {kb_id: $kb_id})
                WHERE e.canonical_name IN $names
                   OR any(a IN e.aliases WHERE a IN $names)
                RETURN e.canonical_name AS name, e.entity_type AS type,
                       e.description AS description, e.mention_count AS mentions,
                       e.pg_id AS pg_id
                """,
                kb_id=kb_id, names=entity_names,
            )

            matched_names = []
            async for record in entity_match:
                matched_names.append(record["name"])
                found_entities.append(record["name"])
                results.append(SearchResult(
                    content=f"{record['name']} ({record['type']}): {record['description'] or 'No description'}",
                    score=0.8 + min(0.2, (record["mentions"] or 1) / 100),
                    source=record["name"],
                    source_type="entity",
                    metadata={"kb_id": kb_id, "entity_type": record["type"], "pg_id": record["pg_id"]},
                ))

            if not matched_names:
                continue

            # Traverse graph N hops from matched entities
            # Depth is validated to 1-4 range — safe to interpolate as integer
            safe_depth = max(1, min(4, int(depth)))
            traversal = await session.run(
                f"""
                MATCH (start:Entity {{kb_id: $kb_id}})
                WHERE start.canonical_name IN $names
                MATCH path = (start)-[r*1..{safe_depth}]->(connected:Entity {{kb_id: $kb_id}})
                WITH connected, relationships(path) AS r, length(path) AS hops
                WHERE connected.canonical_name <> start.canonical_name
                RETURN DISTINCT
                    connected.canonical_name AS name,
                    connected.entity_type AS type,
                    connected.description AS description,
                    hops,
                    [rel IN r | type(rel)] AS rel_types
                ORDER BY hops ASC, connected.mention_count DESC
                LIMIT 30
                """,
                kb_id=kb_id, names=matched_names,
            )

            async for record in traversal:
                # Score decreases with hops
                hop_penalty = 1.0 / (1 + record["hops"] * 0.3)
                rel_chain = " → ".join(record["rel_types"]) if record["rel_types"] else ""

                results.append(SearchResult(
                    content=f"{record['name']} ({record['type']}): {record['description'] or 'No description'} [via: {rel_chain}]",
                    score=0.7 * hop_penalty,
                    source=record["name"],
                    source_type="graph_context",
                    metadata={
                        "kb_id": kb_id, "hops": record["hops"],
                        "relationship_chain": rel_chain,
                    },
                ))

            # Get direct relationships between matched entities
            rel_query = await session.run(
                """
                MATCH (a:Entity {kb_id: $kb_id})-[r]->(b:Entity {kb_id: $kb_id})
                WHERE a.canonical_name IN $names OR b.canonical_name IN $names
                RETURN a.canonical_name AS source, type(r) AS rel_type,
                       b.canonical_name AS target, r.description AS description,
                       r.weight AS weight
                ORDER BY r.weight DESC
                LIMIT 20
                """,
                kb_id=kb_id, names=matched_names,
            )

            async for record in rel_query:
                weight = record["weight"] or 1.0
                results.append(SearchResult(
                    content=f"{record['source']} —[{record['rel_type']}]→ {record['target']}: {record['description'] or ''}",
                    score=0.75 * min(1.0, weight),
                    source=f"{record['source']}→{record['target']}",
                    source_type="relationship",
                    metadata={
                        "kb_id": kb_id,
                        "relationship_type": record["rel_type"],
                        "weight": weight,
                    },
                ))

    results.sort(key=lambda r: r.score, reverse=True)
    return results, found_entities


def _merge_results(
    vector_results: list[SearchResult],
    graph_results: list[SearchResult],
    graph_weight: float = 0.4,
) -> list[SearchResult]:
    """Merge vector and graph results with weighted scoring.

    Deduplicates by content similarity and combines scores.
    """
    # Normalize scores to 0-1 range
    if vector_results:
        max_v = max(r.score for r in vector_results)
        for r in vector_results:
            r.score = r.score / max_v if max_v > 0 else 0

    if graph_results:
        max_g = max(r.score for r in graph_results)
        for r in graph_results:
            r.score = r.score / max_g if max_g > 0 else 0

    # Weighted combination
    merged: list[SearchResult] = []
    seen_content: set[str] = set()

    for r in vector_results:
        key = r.content[:100].lower().strip()
        if key not in seen_content:
            r.score *= (1 - graph_weight)
            merged.append(r)
            seen_content.add(key)

    for r in graph_results:
        key = r.content[:100].lower().strip()
        if key not in seen_content:
            r.score *= graph_weight
            merged.append(r)
            seen_content.add(key)
        else:
            # Boost existing result that also has graph support
            for m in merged:
                if m.content[:100].lower().strip() == key:
                    m.score += r.score * graph_weight * 0.5
                    break

    merged.sort(key=lambda r: r.score, reverse=True)
    return merged
