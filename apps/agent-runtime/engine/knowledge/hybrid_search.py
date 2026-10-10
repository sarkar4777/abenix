"""Hybrid Search Engine — combines vector similarity with knowledge graph traversal"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.knowledge.neo4j_client import get_neo4j_driver, is_neo4j_available
from engine.knowledge.prompts import SEARCH_ENTITY_EXTRACTION

logger = logging.getLogger(__name__)

RERANK_CANDIDATES = 50


class EmbeddingProviderError(Exception):
    """Embedding provider (e.g. OpenAI) failed — distinct from empty-corpus."""


_AZURE_STRIP_WARNED = False


def _normalize_azure_endpoint(raw: str) -> str:
    """Strip the /openai/deployments path the SDK adds itself. Trailing slashes too."""
    if not raw:
        return raw
    s = raw.rstrip("/")
    for suffix in ("/openai/deployments", "/openai"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s.rstrip("/")


def _model_names(model: str | None) -> tuple[str, str, dict]:
    """(openai model, azure deployment, extra request kwargs) for a collection's model."""
    import os

    try:
        import embedding_models as em

        return (
            em.provider_model(model),
            em.azure_deployment(model),
            em.request_kwargs(model),
        )
    except ImportError:
        name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        return name, os.environ.get("AZURE_EMBEDDING_DEPLOYMENT", name), {}


async def _embed_query(query: str, model: str | None = None) -> list[float] | None:
    """Embed a search query with the model the collection was indexed with.

    Azure OpenAI if configured, else direct OpenAI. Returns None when no
    provider is configured so callers can fall back to other backends instead
    of treating it as a hard error."""
    import os

    # Same fallback the ingest path uses, and it has to be the same one:
    # vectors from two schemes share a space and nothing else.
    try:
        from local_embeddings import MODEL_ID as _LOCAL_ID
        from local_embeddings import embed as _local_embed
        from local_embeddings import is_enabled as _local_enabled

        if model == _LOCAL_ID or _local_enabled():
            return _local_embed(query)
    except ImportError:
        pass

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
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    openai_model, deployment, extra = _model_names(model)

    if azure_key and azure_endpoint:
        try:
            from openai import AsyncAzureOpenAI

            client = AsyncAzureOpenAI(
                api_key=azure_key,
                azure_endpoint=azure_endpoint,
                api_version=os.environ.get(
                    "AZURE_OPENAI_API_VERSION", "2024-10-01-preview"
                ),
            )
            resp = await client.embeddings.create(
                input=query, model=deployment, **extra
            )
            return resp.data[0].embedding
        except Exception:
            # Azure failed live — fall through to OpenAI if a direct key is
            # available. Only return None if both providers are unreachable.
            if not openai_key:
                raise

    if not openai_key:
        return None
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=openai_key)
    resp = await client.embeddings.create(model=openai_model, input=query, **extra)
    return resp.data[0].embedding


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
    hidden_documents: int = 0
    # set when the search had to fall back, says why in words
    degraded: str = ""


def _acl_scope(hidden: set[str]) -> str:
    if not hidden:
        return ""
    return hashlib.sha256(",".join(sorted(hidden)).encode()).hexdigest()[:16]


async def _rerank(
    query: str, results: list[SearchResult], top_k: int
) -> list[SearchResult]:
    from engine.knowledge import reranker

    if reranker.provider() == "none" or len(results) <= 1:
        return results[:top_k]
    pool = results[:RERANK_CANDIDATES]
    items = [{"content": r.content, "_i": i} for i, r in enumerate(pool)]
    try:
        ranked = await reranker.rerank(query, items, top_k=top_k)
    except Exception as e:
        logger.warning("rerank failed, keeping retrieval order: %s", e)
        return results[:top_k]
    out: list[SearchResult] = []
    for row in ranked:
        r = pool[row["_i"]]
        if "reranker" in row:
            r.metadata = {
                **r.metadata,
                "retrieval_score": r.score,
                "reranker": row["reranker"],
            }
            r.score = float(row.get("score", r.score))
        out.append(r)
    return out


def _attach_citations(results: list[SearchResult]) -> None:
    from engine.knowledge.reranker import build_citation

    for r in results:
        if r.source_type != "chunk" or "citation" in r.metadata:
            continue
        c = build_citation({**r.metadata, "filename": r.source})
        if c is not None:
            r.metadata = {**r.metadata, "citation": c.to_dict()}


async def hybrid_search(
    query: str,
    kb_ids: list[str],
    mode: SearchMode = SearchMode.HYBRID,
    top_k: int = 10,
    graph_depth: int = 2,
    graph_weight: float = 0.4,
    tenant_id: str = "",
    use_cache: bool = True,
    user_id: str = "",
    user_role: str = "",
    agent_id: str = "",
) -> HybridSearchResponse:
    """Execute hybrid search across vector store and knowledge graph.

    user_id / user_role / agent_id feed the per-document ACL: documents
    restricted by document_grants are dropped before ranking."""
    import time

    from engine.knowledge.document_acl import hidden_for_search, superseded_for_search

    start = time.monotonic()

    restricted = await hidden_for_search(
        kb_ids, user_id=user_id, user_role=user_role, agent_id=agent_id
    )
    # superseded versions are dropped the same way, only the current version is searched
    hidden = restricted | await superseded_for_search(kb_ids)

    # KB v2 query cache (5-min TTL). Best-effort: redis miss/failure
    # falls through to live search.
    from engine.knowledge import search_cache

    cache_k: str | None = None
    if use_cache and tenant_id and kb_ids:
        cache_k = search_cache.cache_key(
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            query=query,
            mode=mode.value,
            top_k=top_k,
            scope=_acl_scope(hidden),
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
                    hidden_documents=len(restricted),
                )
                return resp
            except Exception:
                # Schema drift on cached blob — ignore and recompute.
                pass

    response = HybridSearchResponse(
        results=[], mode_used=mode.value, hidden_documents=len(restricted)
    )

    from engine.knowledge import reranker

    fetch = top_k * 2
    if reranker.provider() != "none":
        fetch = max(fetch, RERANK_CANDIDATES)
    vector_results: list[SearchResult] = []
    if mode in (SearchMode.VECTOR, SearchMode.HYBRID):
        try:
            vector_results = await _vector_search(
                query, kb_ids, top_k=fetch, hidden=hidden
            )
        except EmbeddingProviderError as e:
            # the chunk text is still in Postgres, match words rather than fail the search
            vector_results = await _keyword_search_pg(query, kb_ids, fetch, hidden)
            if not vector_results:
                raise
            response.degraded = (
                "Matched by keywords because the embedding provider is unavailable: "
                f"{str(e)[:200]}"
            )
            response.mode_used = "keyword"
        response.vector_results_count = len(vector_results)

    graph_results: list[SearchResult] = []

    if mode in (SearchMode.GRAPH, SearchMode.HYBRID) and await is_neo4j_available():
        # Extract entity mentions from the query
        query_entities = await _extract_query_entities(query)
        response.entities_found = query_entities

        if query_entities:
            graph_results, _found = await _graph_search(
                query_entities,
                kb_ids,
                depth=graph_depth,
                hidden=hidden,
            )
            response.graph_results_count = len(graph_results)
            response.graph_hops = graph_depth

    if mode == SearchMode.VECTOR:
        ranked = vector_results
    elif mode == SearchMode.GRAPH:
        ranked = graph_results
    else:
        ranked = _merge_results(vector_results, graph_results, graph_weight)
    response.results = await _rerank(query, ranked, top_k)
    _attach_citations(response.results)

    response.latency_ms = int((time.monotonic() - start) * 1000)

    # Stash in cache (best-effort). Only cache hits with results to
    # avoid burning Redis on empty-corpus misses.
    if cache_k and response.results and not response.degraded:
        try:
            await search_cache.set(
                cache_k,
                {
                    "results": [
                        {
                            "content": r.content,
                            "score": r.score,
                            "source": r.source,
                            "source_type": r.source_type,
                            "metadata": r.metadata,
                        }
                        for r in response.results
                    ],
                    "mode_used": response.mode_used,
                    "vector_results_count": response.vector_results_count,
                    "graph_results_count": response.graph_results_count,
                    "entities_found": response.entities_found,
                    "graph_hops": response.graph_hops,
                },
            )
        except Exception:
            pass
    return response


def _async_db_url() -> str:
    import os

    db_url = (
        os.environ.get("DATABASE_URL") or os.environ.get("ASYNC_DATABASE_URL") or ""
    )
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return db_url


async def _kb_index_settings(kb_ids: list[str]) -> dict[str, tuple[str, str | None]]:
    """(vector_backend, embedding_model) per kb in one round-trip."""
    if not kb_ids:
        return {}
    fallback = {kb: ("pinecone", None) for kb in kb_ids}
    try:
        import uuid as _uuid
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import text as _t

        db_url = _async_db_url()
        if not db_url:
            return fallback
        # Filter out non-UUID strings (legacy subject-namespace hack)
        # — those can't be in knowledge_collections anyway.
        uuid_inputs: list[_uuid.UUID] = []
        passthrough: list[str] = []
        for s in kb_ids:
            try:
                uuid_inputs.append(_uuid.UUID(s))
            except (ValueError, AttributeError):
                passthrough.append(s)
        result: dict[str, tuple[str, str | None]] = {
            p: ("pinecone", None) for p in passthrough
        }
        if not uuid_inputs:
            return result
        from engine.db_pool import shared_engine

        engine = shared_engine(db_url)
        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(
                    _t(
                        "SELECT id::text, vector_backend, embedding_model "
                        "FROM knowledge_collections WHERE id = ANY(:ids)"
                    ).bindparams(ids=uuid_inputs)
                )
            ).all()
        for r in rows:
            result[r[0]] = (r[1] or "pinecone", r[2] or None)
        return result
    except Exception:
        return fallback


async def _classify_kb_backends(kb_ids: list[str]) -> dict[str, str]:
    """Look up vector_backend per kb in one round-trip."""
    return {k: v[0] for k, v in (await _kb_index_settings(kb_ids)).items()}


async def _vector_search_pgvector(
    query: str,
    kb_ids: list[str],
    top_k: int,
    model: str | None = None,
    hidden: set[str] | frozenset[str] = frozenset(),
) -> list[SearchResult]:
    """Vector search via Postgres+pgvector for collections opted into it."""
    try:
        import httpx
        import openai
        from sqlalchemy.ext.asyncio import AsyncSession
        from sqlalchemy import text as _t

        try:
            emb = await _embed_query(query, model)
        except (openai.RateLimitError, openai.APIError, httpx.HTTPStatusError) as e:
            logger.error("Embedding provider unavailable (pgvector path): %s", e)
            raise EmbeddingProviderError(str(e)) from e
        if emb is None:
            return []
        emb_str = "[" + ",".join(f"{x:.7f}" for x in emb) + "]"

        db_url = _async_db_url()
        # text() will not bind `:emb::vector` — its parameter regex refuses a
        # name followed by a colon, so the cast swallowed the placeholder and
        # every search died on "no bound parameter named 'emb'". CAST() reads
        # the same to Postgres and leaves the name alone.
        import uuid as _uuid

        id_params: list[_uuid.UUID] = []
        for s in kb_ids:
            try:
                id_params.append(_uuid.UUID(str(s)))
            except (ValueError, AttributeError):
                continue
        if not id_params:
            return []
        hidden_params = [_uuid.UUID(h) for h in hidden]

        from engine.db_pool import shared_engine

        engine = shared_engine(db_url)
        results: list[SearchResult] = []
        async with AsyncSession(engine) as session:
            rows = (
                await session.execute(
                    _t(
                        """
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       1 - (embedding <=> CAST(:emb AS vector)) AS score
                FROM chunks
                WHERE collection_id = ANY(:ids)
                  AND NOT (document_id = ANY(:hidden))
                  AND NOT EXISTS (
                      SELECT 1 FROM documents d
                      WHERE d.id = chunks.document_id AND d.is_current IS FALSE)
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :k
                """
                    ).bindparams(
                        emb=emb_str, ids=id_params, hidden=hidden_params, k=top_k
                    )
                )
            ).all()
        for r in rows:
            meta = r[5] or {}
            if not isinstance(meta, dict):
                meta = {}
            filename = meta.get("filename") or "unknown"
            # Whatever the document was stored with — policy_id, jurisdiction,
            # version — travels with the chunk. Only the filename used to come
            # back, so an agent asked to cite a policy id could only name the
            # file it came out of.
            carried = dict(meta)
            carried.update(
                {
                    "kb_id": r[1],
                    "doc_id": r[2],
                    "chunk_index": r[3],
                    "backend": "pgvector",
                }
            )
            results.append(
                SearchResult(
                    content=r[4],
                    score=float(r[6]),
                    source=filename,
                    source_type="chunk",
                    metadata=carried,
                )
            )
        return results
    except EmbeddingProviderError:
        raise
    except Exception as e:
        logger.error("pgvector search failed: %s", e)
        return []


_WORD = re.compile(r"[A-Za-z0-9]{3,}")


async def _keyword_search_pg(
    query: str,
    kb_ids: list[str],
    top_k: int,
    hidden: set[str] | frozenset[str] = frozenset(),
) -> list[SearchResult]:
    """Postgres full-text match over the stored chunks, any query word counts."""
    words = list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))[:24]
    if not words:
        return []
    try:
        import uuid as _uuid

        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine

        ids = []
        for k in kb_ids:
            try:
                ids.append(_uuid.UUID(str(k)))
            except (ValueError, AttributeError):
                continue
        if not ids:
            return []
        async with AsyncSession(shared_engine(_async_db_url())) as session:
            rows = (
                await session.execute(
                    _t(
                        """
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       ts_rank_cd(to_tsvector('english', content), q) AS score
                FROM chunks, to_tsquery('english', :q) q
                WHERE collection_id = ANY(:ids)
                  AND NOT (document_id = ANY(:hidden))
                  AND NOT EXISTS (
                      SELECT 1 FROM documents d
                      WHERE d.id = chunks.document_id AND d.is_current IS FALSE)
                  AND to_tsvector('english', content) @@ q
                ORDER BY score DESC
                LIMIT :k
                """
                    ).bindparams(
                        q=" | ".join(words),
                        ids=ids,
                        hidden=[_uuid.UUID(h) for h in hidden],
                        k=top_k,
                    )
                )
            ).all()
    except Exception as e:
        logger.error("keyword search failed: %s", e)
        return []
    out: list[SearchResult] = []
    for r in rows:
        meta = r[5] if isinstance(r[5], dict) else {}
        carried = dict(meta)
        carried.update(
            {"kb_id": r[1], "doc_id": r[2], "chunk_index": r[3], "backend": "keyword"}
        )
        out.append(
            SearchResult(
                content=r[4],
                score=float(r[6]),
                source=meta.get("filename") or "unknown",
                source_type="chunk",
                metadata=carried,
            )
        )
    return out


async def _vector_search(
    query: str,
    kb_ids: list[str],
    top_k: int = 20,
    hidden: set[str] | frozenset[str] = frozenset(),
) -> list[SearchResult]:
    """Perform vector similarity search across kb_ids.

    Each collection is queried with the embedding model it was indexed with."""
    settings = await _kb_index_settings(kb_ids)
    groups: dict[tuple[str, str | None], list[str]] = {}
    for k in kb_ids:
        backend, model = settings.get(k, ("pinecone", None))
        key = ("pgvector" if backend == "pgvector" else "pinecone", model)
        groups.setdefault(key, []).append(k)

    results: list[SearchResult] = []
    for (backend, model), ids in groups.items():
        if backend == "pgvector":
            results.extend(
                await _vector_search_pgvector(query, ids, top_k, model, hidden)
            )
        else:
            results.extend(
                await _vector_search_pinecone(query, ids, top_k, model, hidden)
            )
            # the worker stores into pgvector when Pinecone refuses a write,
            # those chunks were invisible to search until now
            fallback_ids = await _kbs_with_pg_chunks(ids)
            if fallback_ids:
                results.extend(
                    await _vector_search_pgvector(
                        query, fallback_ids, top_k, model, hidden
                    )
                )
    results.sort(key=lambda r: r.score, reverse=True)
    return results


async def _kbs_with_pg_chunks(kb_ids: list[str]) -> list[str]:
    try:
        import uuid as _uuid

        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine

        ids = []
        for s in kb_ids:
            try:
                ids.append(_uuid.UUID(str(s)))
            except (ValueError, AttributeError):
                continue
        if not ids:
            return []
        async with AsyncSession(shared_engine(_async_db_url())) as session:
            rows = (
                await session.execute(
                    _t(
                        "SELECT DISTINCT collection_id::text FROM chunks"
                        " WHERE collection_id = ANY(:ids)"
                    ).bindparams(ids=ids)
                )
            ).all()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("pgvector fallback lookup failed: %s", e)
        return []


async def _vector_search_pinecone(
    query: str,
    kb_ids: list[str],
    top_k: int,
    model: str | None = None,
    hidden: set[str] | frozenset[str] = frozenset(),
) -> list[SearchResult]:
    try:
        import os
        import httpx
        import openai
        from pinecone import Pinecone

        azure_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        azure_endpoint = _normalize_azure_endpoint(
            os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            or os.environ.get("AZURE_OPENAI_API_BASE", "")
        )
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        pinecone_key = os.environ.get("PINECONE_API_KEY", "")
        index_name = os.environ.get("PINECONE_INDEX_NAME", "agentforge-knowledge")

        if not pinecone_key:
            return []
        if not ((azure_key and azure_endpoint) or openai_key):
            return []

        # Embedding-provider failures (rate-limit, 5xx, transport errors) must
        # NOT degrade to an empty result — that hides a real outage as "no
        # match". Re-raise as EmbeddingProviderError so the router can return
        # 503 instead of 200/empty.
        try:
            query_vector = await _embed_query(query, model)
        except (openai.RateLimitError, openai.APIError, httpx.HTTPStatusError) as e:
            logger.error("Embedding provider unavailable: %s", e)
            raise EmbeddingProviderError(str(e)) from e
        if query_vector is None:
            return []

        # Search across all KB namespaces (Pinecone v7+ returns structured objects)
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

        results: list[SearchResult] = []
        for kb_id in kb_ids:
            _filter: dict[str, Any] = {"persona_scope": {"$ne": "_persona_"}}
            if hidden:
                _filter["doc_id"] = {"$nin": sorted(hidden)}
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
            matches = (
                getattr(response, "matches", None) or response.get("matches", [])
                if isinstance(response, dict)
                else getattr(response, "matches", None) or []
            )
            for m in matches:
                meta = getattr(m, "metadata", None) or (
                    m.get("metadata", {}) if isinstance(m, dict) else {}
                )
                # Defense-in-depth: drop any persona chunk that made it past
                # the Pinecone filter (e.g. older SDK ignored the filter
                # arg). Generic search must NEVER surface persona data.
                if isinstance(meta, dict) and meta.get("persona_scope"):
                    continue
                doc_id = meta.get("doc_id", "") if isinstance(meta, dict) else ""
                if doc_id and doc_id in hidden:
                    continue
                score = getattr(m, "score", None) or (
                    m.get("score", 0.0) if isinstance(m, dict) else 0.0
                )
                carried: dict[str, Any] = {
                    "kb_id": kb_id,
                    "doc_id": doc_id,
                    "chunk_index": (
                        meta.get("chunk_index", 0) if isinstance(meta, dict) else 0
                    ),
                }
                if isinstance(meta, dict) and meta.get("page") is not None:
                    carried["page"] = meta.get("page")
                results.append(
                    SearchResult(
                        content=(
                            meta.get("text", "")
                            if isinstance(meta, dict)
                            else str(meta)
                        ),
                        score=float(score),
                        source=(
                            meta.get("filename", "unknown")
                            if isinstance(meta, dict)
                            else "unknown"
                        ),
                        source_type="chunk",
                        metadata=carried,
                    )
                )
        return results

    except EmbeddingProviderError:
        # Bubble up — caller distinguishes provider outage from no-match.
        raise
    except Exception as e:
        logger.error("Vector search failed: %s", e)
        return []


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
            entities = json.loads(text[text.index("[") : text.rindex("]") + 1])
            return [e for e in entities if isinstance(e, str)]
    except Exception as e:
        logger.debug("Query entity extraction failed: %s", e)

    # Fallback: split query into significant words (>3 chars, capitalized)
    words = query.split()
    return [w for w in words if len(w) > 3 and w[0].isupper()]


# a graph fact stays visible while at least one of its source documents is
_VISIBLE = (
    "(size(coalesce({v}.source_doc_ids, [])) = 0 "
    "OR any(d IN {v}.source_doc_ids WHERE NOT d IN $hidden))"
)


async def _graph_search(
    entity_names: list[str],
    kb_ids: list[str],
    depth: int = 2,
    hidden: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[SearchResult], list[str]]:
    """Search the knowledge graph for entities and their relationships.

    Returns: (search_results, found_entity_names)
    """
    driver = await get_neo4j_driver()
    results: list[SearchResult] = []
    found_entities: list[str] = []
    hidden_list = sorted(hidden)

    async with driver.session() as session:
        for kb_id in kb_ids:
            # Find matching entities (exact or alias match)
            entity_match = await session.run(
                f"""
                MATCH (e:Entity {{kb_id: $kb_id}})
                WHERE (e.canonical_name IN $names
                   OR any(a IN e.aliases WHERE a IN $names))
                  AND {_VISIBLE.format(v="e")}
                RETURN e.canonical_name AS name, e.entity_type AS type,
                       e.description AS description, e.mention_count AS mentions,
                       e.pg_id AS pg_id
                """,
                kb_id=kb_id,
                names=entity_names,
                hidden=hidden_list,
            )

            matched_names = []
            async for record in entity_match:
                matched_names.append(record["name"])
                found_entities.append(record["name"])
                results.append(
                    SearchResult(
                        content=f"{record['name']} ({record['type']}): {record['description'] or 'No description'}",
                        score=0.8 + min(0.2, (record["mentions"] or 1) / 100),
                        source=record["name"],
                        source_type="entity",
                        metadata={
                            "kb_id": kb_id,
                            "entity_type": record["type"],
                            "pg_id": record["pg_id"],
                        },
                    )
                )

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
                WITH start, connected, relationships(path) AS r, length(path) AS hops
                WHERE connected.canonical_name <> start.canonical_name
                  AND {_VISIBLE.format(v="connected")}
                  AND all(rel IN r WHERE {_VISIBLE.format(v="rel")})
                RETURN DISTINCT
                    connected.canonical_name AS name,
                    connected.entity_type AS type,
                    connected.description AS description,
                    hops,
                    [rel IN r | type(rel)] AS rel_types,
                    connected.mention_count AS mention_count
                ORDER BY hops ASC, mention_count DESC
                LIMIT 30
                """,
                kb_id=kb_id,
                names=matched_names,
                hidden=hidden_list,
            )

            async for record in traversal:
                # Score decreases with hops
                hop_penalty = 1.0 / (1 + record["hops"] * 0.3)
                rel_chain = (
                    " → ".join(record["rel_types"]) if record["rel_types"] else ""
                )

                results.append(
                    SearchResult(
                        content=f"{record['name']} ({record['type']}): {record['description'] or 'No description'} [via: {rel_chain}]",
                        score=0.7 * hop_penalty,
                        source=record["name"],
                        source_type="graph_context",
                        metadata={
                            "kb_id": kb_id,
                            "hops": record["hops"],
                            "relationship_chain": rel_chain,
                        },
                    )
                )

            # Get direct relationships between matched entities
            rel_query = await session.run(
                f"""
                MATCH (a:Entity {{kb_id: $kb_id}})-[r]->(b:Entity {{kb_id: $kb_id}})
                WHERE (a.canonical_name IN $names OR b.canonical_name IN $names)
                  AND {_VISIBLE.format(v="r")}
                  AND {_VISIBLE.format(v="a")}
                  AND {_VISIBLE.format(v="b")}
                RETURN a.canonical_name AS source, type(r) AS rel_type,
                       b.canonical_name AS target, r.description AS description,
                       r.weight AS weight
                ORDER BY r.weight DESC
                LIMIT 20
                """,
                kb_id=kb_id,
                names=matched_names,
                hidden=hidden_list,
            )

            async for record in rel_query:
                weight = record["weight"] or 1.0
                results.append(
                    SearchResult(
                        content=f"{record['source']} —[{record['rel_type']}]→ {record['target']}: {record['description'] or ''}",
                        score=0.75 * min(1.0, weight),
                        source=f"{record['source']}→{record['target']}",
                        source_type="relationship",
                        metadata={
                            "kb_id": kb_id,
                            "relationship_type": record["rel_type"],
                            "weight": weight,
                        },
                    )
                )

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
            r.score *= 1 - graph_weight
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
