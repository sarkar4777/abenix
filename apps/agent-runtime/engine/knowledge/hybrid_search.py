"""Hybrid Search Engine — combines vector similarity with knowledge graph traversal"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import re
import time
import uuid as _uuid_mod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from engine.knowledge.neo4j_client import (
    FULLTEXT_INDEX,
    _NEO4J_DATABASE,
    cypher,
    ensure_kb_keys,
    ensure_schema,
    entity_scope,
    fulltext_query,
    get_neo4j_driver,
    is_neo4j_available,
    visible,
)
from engine.knowledge.prompts import SEARCH_ENTITY_EXTRACTION

logger = logging.getLogger(__name__)

RERANK_CANDIDATES = 50


class EmbeddingProviderError(Exception):
    """Embedding provider (e.g. OpenAI) failed — distinct from empty-corpus."""


_AZURE_STRIP_WARNED = False


class NoEmbeddingProvider(EmbeddingProviderError):
    """Nothing is configured, which is not an outage, so an empty keyword result stands."""


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
    """Embed a search query with the model the collection was indexed with."""
    vectors = await embed_for_collection([query], model)
    return vectors[0] if vectors else None


async def embed_for_collection(
    texts: list[str], model: str | None = None
) -> list[list[float]] | None:
    """Embed with the collection's model, Azure OpenAI then OpenAI. None when no provider is configured."""
    import asyncio
    import os

    # Same fallback the ingest path uses, and it has to be the same one:
    # vectors from two schemes share a space and nothing else.
    try:
        from local_embeddings import MODEL_ID as _LOCAL_ID
        from local_embeddings import embed_many as _local_embed_many
        from local_embeddings import is_enabled as _local_enabled

        if model == _LOCAL_ID or _local_enabled():
            return await asyncio.to_thread(_local_embed_many, texts)
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

    async def batched(client: Any, name: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):
            resp = await client.embeddings.create(
                input=texts[i : i + 100], model=name, **extra
            )
            out.extend(d.embedding for d in resp.data)
        return out

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
            return await batched(client, deployment)
        except Exception:
            # Azure failed live — fall through to OpenAI if a direct key is
            # available. Only return None if both providers are unreachable.
            if not openai_key:
                raise

    if not openai_key:
        return None
    from openai import AsyncOpenAI

    return await batched(AsyncOpenAI(api_key=openai_key), openai_model)


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
    digest = getattr(hidden, "digest", "")
    if digest:
        return digest
    if not hidden:
        return ""
    return hashlib.sha256(",".join(sorted(hidden)).encode()).hexdigest()[:16]


def _rerank_candidates() -> int:
    return max(
        1, int(os.environ.get("KB_RERANK_MAX_CANDIDATES", str(RERANK_CANDIDATES)))
    )


def _rerank_allowed(settings: dict[str, dict[str, str]], tenant_id: str) -> bool:
    """Off on any searched collection wins, and each tenant has a call budget per minute."""
    from engine.knowledge import reranker
    from engine.knowledge.embed_gate import rerank_gate

    if reranker.provider() == "none":
        return False
    if any(v.get("rerank_mode") == "off" for v in settings.values()):
        return False
    if not rerank_gate(tenant_id).try_acquire():
        logger.info(
            "rerank budget spent for tenant %s, keeping retrieval order", tenant_id
        )
        return False
    return True


def _rerank_language(settings: dict[str, dict[str, str]]) -> str:
    languages = {v.get("search_language", "simple") for v in settings.values()}
    return languages.pop() if len(languages) == 1 else "simple"


async def _rerank(
    query: str, results: list[SearchResult], top_k: int, language: str = "simple"
) -> list[SearchResult]:
    from engine.knowledge import reranker

    if reranker.provider() == "none" or len(results) <= 1:
        return results[:top_k]
    pool = results[: _rerank_candidates()]
    items = [{"content": r.content, "_i": i} for i, r in enumerate(pool)]
    try:
        kwargs = {"language": language} if language != "simple" else {}
        ranked = await asyncio.wait_for(
            reranker.rerank(query, items, top_k=top_k, **kwargs),
            float(os.environ.get("KB_RERANK_TIMEOUT_SECONDS", "8")),
        )
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

    from engine.knowledge import document_acl

    start = time.monotonic()

    restricted = await document_acl.hidden_for_search(
        kb_ids, user_id=user_id, user_role=user_role, agent_id=agent_id
    )
    # superseded versions are dropped the same way, only the current version is searched
    hidden = document_acl.merge_hidden(
        restricted, await document_acl.superseded_for_search(kb_ids)
    )
    restricted_total = getattr(restricted, "total", len(restricted))

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
                    hidden_documents=restricted_total,
                    degraded=cached.get("degraded", ""),
                )
                return resp
            except Exception:
                # Schema drift on cached blob — ignore and recompute.
                pass

    response = HybridSearchResponse(
        results=[], mode_used=mode.value, hidden_documents=restricted_total
    )

    settings = await _kb_search_settings(kb_ids)
    use_reranker = _rerank_allowed(settings, tenant_id)
    fetch = top_k * 2
    if use_reranker:
        fetch = max(fetch, _rerank_candidates())
    vector_results: list[SearchResult] = []
    outage = False
    notes: list[str] = []
    if mode in (SearchMode.VECTOR, SearchMode.HYBRID):
        response.degraded = await _lexical_index_note(kb_ids)
        notes_token = _SEARCH_NOTES.set(notes)
        try:
            vector_results = await _vector_search(
                query, kb_ids, top_k=fetch, hidden=hidden
            )
        except EmbeddingProviderError as e:
            # the chunk text is still in Postgres, match words rather than fail the search
            vector_results = await _keyword_search_pg(query, kb_ids, fetch, hidden)
            not_configured = isinstance(e, NoEmbeddingProvider)
            if not vector_results and not not_configured:
                raise
            outage = True
            response.degraded = (
                "Searched by keywords because no embedding provider is configured. "
                "Add one for semantic search."
                if not_configured
                else "Matched by keywords because the embedding provider is unavailable, "
                f"{str(e)[:200]}"
            )
            response.mode_used = "keyword"
        finally:
            _SEARCH_NOTES.reset(notes_token)
        if notes:
            response.degraded = " ".join([response.degraded, *notes]).strip()
        response.vector_results_count = 0 if outage else len(vector_results)

    graph_results: list[SearchResult] = []

    graph_blocked = bool(getattr(hidden, "overflow", False))
    if graph_blocked and mode in (SearchMode.GRAPH, SearchMode.HYBRID):
        # graph facts filter on a list of ids, past the cap that list would leak
        note = (
            "Graph results were left out because too many documents are hidden "
            "from this caller to filter them safely."
        )
        response.degraded = f"{response.degraded} {note}".strip()
    if (
        mode in (SearchMode.GRAPH, SearchMode.HYBRID)
        and not graph_blocked
        and await is_neo4j_available()
    ):
        # Extract entity mentions from the query
        query_entities = await _extract_query_entities(query)
        response.entities_found = query_entities

        if query_entities:
            notes: list[str] = []
            try:
                graph_results, _found = await _graph_search(
                    query_entities,
                    kb_ids,
                    depth=graph_depth,
                    hidden=hidden,
                    tenant_id=tenant_id,
                    notes=notes,
                )
            except Exception as e:
                # a slow or failed graph leaves the vector answer standing
                logger.warning("graph search failed: %s", e)
                notes.append(f"Graph search failed: {str(e)[:200]}")
            if notes:
                response.degraded = " ".join(filter(None, [response.degraded, *notes]))
            response.graph_results_count = len(graph_results)
            response.graph_hops = graph_depth

    if mode == SearchMode.VECTOR:
        ranked = vector_results
    elif mode == SearchMode.GRAPH:
        ranked = graph_results
    else:
        ranked = _merge_results(vector_results, graph_results, graph_weight)
    if use_reranker:
        language = _rerank_language(settings)
        extra = {"language": language} if language != "simple" else {}
        response.results = await _rerank(query, ranked, top_k, **extra)
    else:
        response.results = ranked[:top_k]
    _attach_citations(response.results)

    response.latency_ms = int((time.monotonic() - start) * 1000)

    # Stash in cache (best-effort). Only cache hits with results to
    # avoid burning Redis on empty-corpus misses.
    if cache_k and response.results and not outage and not notes:
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
                    "degraded": response.degraded,
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
                        "FROM knowledge_collections "
                        "WHERE id = ANY(:ids) AND deleted_at IS NULL"
                    ).bindparams(ids=uuid_inputs)
                )
            ).all()
        for r in rows:
            result[r[0]] = (r[1] or "pinecone", r[2] or None)
        return result
    except Exception:
        return fallback


_SEARCH_DEFAULTS = {
    "search_language": "simple",
    "rerank_mode": "auto",
    "index_mode": "shared",
}


async def _kb_search_settings(kb_ids: list[str]) -> dict[str, dict[str, str]]:
    """Language, rerank and index mode per collection, defaults when it cannot be read."""
    out = {str(k): dict(_SEARCH_DEFAULTS) for k in kb_ids}
    ids = _uuid_list(kb_ids)
    db_url = _async_db_url()
    if not ids or not db_url:
        return out
    try:
        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine

        async with AsyncSession(shared_engine(db_url)) as session:
            rows = (
                await session.execute(
                    _t(
                        "SELECT id::text, search_language, rerank_mode, index_mode "
                        "FROM knowledge_collections WHERE id = ANY(:ids)"
                    ).bindparams(ids=ids)
                )
            ).all()
        for r in rows:
            out[r[0]] = {
                "search_language": r[1] or "simple",
                "rerank_mode": r[2] or "auto",
                "index_mode": r[3] or "shared",
            }
    except Exception as e:
        logger.warning("collection search settings unavailable: %s", e)
    return out


def _uuid_list(values: Any) -> list[_uuid_mod.UUID]:
    out = []
    for v in values:
        try:
            out.append(_uuid_mod.UUID(str(v)))
        except (ValueError, AttributeError):
            continue
    return out


async def _lexical_index_note(kb_ids: list[str]) -> str:
    try:
        from local_embeddings import MODEL_ID, is_enabled
    except ImportError:
        return ""
    settings = await _kb_index_settings(kb_ids)
    if is_enabled() or any(s[1] == MODEL_ID for s in settings.values()):
        return (
            "Matched by word overlap because this collection uses the local hashing "
            "embedder. Results are not semantic. Add an embedding provider key and "
            "re-embed the collection for semantic search."
        )
    return ""


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

        try:
            emb = await _embed_query(query, model)
        except (openai.RateLimitError, openai.APIError, httpx.HTTPStatusError) as e:
            logger.error("Embedding provider unavailable (pgvector path): %s", e)
            raise EmbeddingProviderError(str(e)) from e
        if emb is None:
            raise NoEmbeddingProvider("no embedding provider is configured")
        emb_str = "[" + ",".join(f"{x:.7f}" for x in emb) + "]"

        db_url = _async_db_url()
        id_params = _uuid_list(kb_ids)
        if not id_params:
            return []

        from engine.db_pool import shared_engine

        engine = shared_engine(db_url)
        results: list[SearchResult] = []
        modes = await _kb_search_settings([str(i) for i in id_params])
        rows = []
        async with AsyncSession(engine) as session:
            store = await _chunk_store_facts(session, db_url)
            for kb in id_params:
                rows.extend(
                    await _search_collection(
                        session,
                        kb,
                        emb_str,
                        top_k,
                        hidden,
                        store,
                        modes.get(str(kb), _SEARCH_DEFAULTS)["index_mode"],
                    )
                )
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
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]
    except EmbeddingProviderError:
        raise
    except Exception as e:
        logger.error("pgvector search failed: %s", e)
        _search_note(f"Vector search failed and returned nothing: {str(e)[:200]}")
        return []


_SEARCH_NOTES: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "kb_search_notes", default=None
)


def _search_note(note: str) -> None:
    notes = _SEARCH_NOTES.get()
    if notes is not None and note not in notes:
        notes.append(note)


_STORE_FACTS: dict[str, tuple[float, dict[str, Any]]] = {}


async def _chunk_store_facts(session: Any, db_url: str) -> dict[str, Any]:
    """pgvector version and the embedding column type, read rarely."""
    import time

    from sqlalchemy import text as _t

    hit = _STORE_FACTS.get(db_url)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    row = (
        await session.execute(
            _t(
                "SELECT (SELECT extversion FROM pg_extension WHERE extname = 'vector'), "
                "(SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
                "WHERE a.attrelid = to_regclass('chunks') AND a.attname = 'embedding')"
            )
        )
    ).first()
    version = tuple(
        int(p) for p in re.findall(r"\d+", (row[0] if row else "") or "0")[:3]
    )
    facts = {
        "version": version,
        "cast": (
            "halfvec"
            if ((row[1] if row else "") or "").startswith("halfvec")
            else "vector"
        ),
    }
    _STORE_FACTS[db_url] = (time.monotonic() + 600, facts)
    return facts


def _exact_scan_max() -> int:
    return int(os.environ.get("KB_EXACT_SCAN_MAX_CHUNKS", "20000"))


def _hidden_filter(
    hidden: Any, chunk_alias: str = "chunks"
) -> tuple[str, dict[str, Any]]:
    """Ids while they fit in a bind, otherwise the rule itself runs in SQL."""
    from engine.knowledge import document_acl

    extra = ""
    params: dict[str, Any] = {}
    if getattr(hidden, "restricted_overflow", False):
        extra = f" OR {document_acl.RESTRICTED_PREDICATE.format(doc='d')}"
        params.update(
            uid=getattr(hidden, "uid", None), aid=getattr(hidden, "aid", None)
        )
    sql = f"""
                  AND NOT ({chunk_alias}.document_id = ANY(:hidden))
                  AND NOT EXISTS (
                      SELECT 1 FROM documents d
                      WHERE d.id = {chunk_alias}.document_id
                        AND (d.is_current IS FALSE{extra}))
                  AND EXISTS (
                      SELECT 1 FROM knowledge_collections kc
                      WHERE kc.id = {chunk_alias}.collection_id
                        AND kc.deleted_at IS NULL
                        AND kc.embedding_generation = {chunk_alias}.embedding_generation)
    """
    params["hidden"] = _uuid_list(hidden)
    return sql, params


async def _search_collection(
    session: Any,
    kb: _uuid_mod.UUID,
    emb_str: str,
    top_k: int,
    hidden: Any,
    store: dict[str, Any],
    index_mode: str,
) -> list[Any]:
    """Exact while small or unindexed. Above that HNSW, then deeper, then exact, never a silent short page."""
    from sqlalchemy import text as _t

    limit = _exact_scan_max()
    size = (
        await session.execute(
            _t(
                "SELECT count(*) FROM (SELECT 1 FROM chunks "
                "WHERE collection_id = :kb LIMIT :n) x"
            ).bindparams(kb=kb, n=limit + 1)
        )
    ).scalar() or 0
    await session.commit()
    if not size:
        return []
    if size <= limit or index_mode in ("deferred", "building"):
        return await _exact_scan(session, kb, emb_str, top_k, hidden, store)
    want = min(top_k, size)
    rows = await _hnsw_scan(session, kb, emb_str, top_k, hidden, store, index_mode)
    # a shared index walks closer vectors of other collections first
    if len(rows) < want and store["version"] >= (0, 8):
        deeper = await _hnsw_scan(
            session, kb, emb_str, top_k, hidden, store, index_mode, deep=True
        )
        if len(deeper) > len(rows):
            rows = deeper
    if len(rows) >= want:
        return rows
    exact = await _exact_scan(session, kb, emb_str, top_k, hidden, store, timeout=True)
    if exact is not None:
        # finished, so what it found is everything this caller may see
        return exact
    _search_note(
        f"Only {len(rows)} of {top_k} results came back from a collection this large "
        "because the full scan ran out of time, so results are incomplete. Run "
        "scripts/kb-chunks-partition.py or give this collection its own index."
    )
    return rows


async def _exact_scan(
    session: Any,
    kb: _uuid_mod.UUID,
    emb_str: str,
    top_k: int,
    hidden: Any,
    store: dict[str, Any],
    timeout: bool = False,
) -> list[Any] | None:
    """The rows, or None when the time limit stopped it and they would be a guess."""
    from sqlalchemy import text as _t

    where, params = _hidden_filter(hidden)
    cast = store["cast"]
    try:
        if timeout:
            await session.execute(
                _t("SELECT set_config('statement_timeout', :v, true)").bindparams(
                    v=os.environ.get("KB_EXACT_FALLBACK_TIMEOUT_MS", "30000")
                )
            )
        # the materialized scan can not touch HNSW, so nothing is lost to post filtering
        rows = (
            await session.execute(
                _t(
                    f"""
                WITH c AS MATERIALIZED (
                    SELECT id, collection_id, document_id, chunk_index, content,
                           metadata, embedding
                    FROM chunks
                    WHERE collection_id = :kb
                    {where}
                )
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       1 - (embedding <=> CAST(:emb AS {cast})) AS score
                FROM c
                ORDER BY embedding <=> CAST(:emb AS {cast})
                LIMIT :k
                """
                ).bindparams(kb=kb, emb=emb_str, k=top_k, **params)
            )
        ).all()
        await session.commit()
        return list(rows)
    except Exception as e:
        await session.rollback()
        if not timeout:
            raise
        logger.warning("exact fallback for collection %s stopped: %s", kb, e)
        return None


async def _hnsw_scan(
    session: Any,
    kb: _uuid_mod.UUID,
    emb_str: str,
    top_k: int,
    hidden: Any,
    store: dict[str, Any],
    index_mode: str,
    deep: bool = False,
) -> list[Any]:
    from sqlalchemy import text as _t

    where, params = _hidden_filter(hidden)
    cast = store["cast"]
    # post filtering eats candidates, so ask for more than the caller wants
    ef = min(1000, max(int(os.environ.get("KB_HNSW_EF_SEARCH", "100")), top_k * 4))
    await session.execute(
        _t("SELECT set_config('hnsw.ef_search', :v, true)").bindparams(v=str(ef))
    )
    if store["version"] >= (0, 8):
        await session.execute(
            _t("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)")
        )
        await session.execute(
            _t("SELECT set_config('hnsw.max_scan_tuples', :v, true)").bindparams(
                v=(
                    os.environ.get("KB_HNSW_DEEP_SCAN_TUPLES", "2000000")
                    if deep
                    else os.environ.get("KB_HNSW_MAX_SCAN_TUPLES", "50000")
                )
            )
        )
        if deep:
            # the scan stops at work_mem times this, a low limit would end it early
            await session.execute(
                _t("SELECT set_config('hnsw.scan_mem_multiplier', '8', true)")
            )
    # a literal id lets the planner prune partitions and prove a partial index applies
    scope = "dedicated_index" if index_mode == "dedicated" else "NOT dedicated_index"
    rows = (
        await session.execute(
            _t(
                f"""
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       1 - (embedding <=> CAST(:emb AS {cast})) AS score
                FROM chunks
                WHERE collection_id = '{kb}'
                  AND {scope}
                  {where}
                ORDER BY embedding <=> CAST(:emb AS {cast})
                LIMIT :k
                """
            ).bindparams(emb=emb_str, k=top_k, **params)
        )
    ).all()
    await session.commit()
    return list(rows)


_WORD = re.compile(r"\w{2,}")


def _ts_config(language: str | None) -> str:
    try:
        from chunks_store import validate_language

        return validate_language(language)
    except ImportError:
        return "simple"


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
        from sqlalchemy import text as _t
        from sqlalchemy.ext.asyncio import AsyncSession

        from engine.db_pool import shared_engine

        ids = _uuid_list(kb_ids)
        if not ids:
            return []
        settings = await _kb_search_settings([str(i) for i in ids])
        groups: dict[str, list[Any]] = {}
        for i in ids:
            groups.setdefault(
                _ts_config(settings.get(str(i), _SEARCH_DEFAULTS)["search_language"]),
                [],
            ).append(i)
        rows: list[Any] = []
        where, params = _hidden_filter(hidden)
        async with AsyncSession(shared_engine(_async_db_url())) as session:
            for config, group in groups.items():
                # a keyword scan has no vector index, this keeps it from running on
                await session.execute(
                    _t("SELECT set_config('statement_timeout', :v, true)").bindparams(
                        v=os.environ.get("KB_KEYWORD_TIMEOUT_MS", "15000")
                    )
                )
                rows.extend(
                    (
                        await session.execute(
                            _t(
                                f"""
                SELECT id::text, collection_id::text, document_id::text,
                       chunk_index, content, metadata,
                       ts_rank_cd(to_tsvector('{config}', content), q) AS score
                FROM chunks, to_tsquery('{config}', :q) q
                WHERE collection_id = ANY(:ids)
                  {where}
                  AND to_tsvector('{config}', content) @@ q
                ORDER BY score DESC
                LIMIT :k
                """
                            ).bindparams(
                                q=" | ".join(words), ids=group, k=top_k, **params
                            )
                        )
                    ).all()
                )
                await session.commit()
        rows.sort(key=lambda r: float(r[6]), reverse=True)
        rows = rows[:top_k]
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
                        "SELECT k.id::text FROM knowledge_collections k "
                        "WHERE k.id = ANY(:ids) AND k.deleted_at IS NULL AND EXISTS ("
                        "SELECT 1 FROM chunks c WHERE c.collection_id = k.id "
                        "AND c.embedding_generation = k.embedding_generation)"
                    ).bindparams(ids=ids)
                )
            ).all()
        return [r[0] for r in rows]
    except Exception as e:
        logger.warning("pgvector fallback lookup failed: %s", e)
        return []


def _pinecone_nin_max() -> int:
    return int(os.environ.get("KB_PINECONE_NIN_MAX", "1000"))


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
            raise NoEmbeddingProvider("no embedding provider is configured")

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
            raise NoEmbeddingProvider("no embedding provider is configured")

        # Search across all KB namespaces (Pinecone v7+ returns structured objects)
        pc = Pinecone(api_key=pinecone_key)
        index = pc.Index(index_name)

        from engine.knowledge.kb_state import live_generations, pinecone_namespace

        generations = await live_generations(kb_ids)
        results: list[SearchResult] = []
        # past the cap nothing is sent, more is fetched and each result is checked
        unlisted = bool(getattr(hidden, "overflow", False)) or (
            len(hidden) > _pinecone_nin_max()
        )
        fetch_k = min(1000, top_k * 3) if unlisted else top_k
        for kb_id in kb_ids:
            if generations is not None and kb_id not in generations:
                continue
            namespace = pinecone_namespace(kb_id, (generations or {}).get(kb_id, 0))
            _filter: dict[str, Any] = {
                "persona_scope": {"$ne": "_persona_"},
                # stamped on a replaced version, so the list below stays short
                "superseded": {"$ne": True},
            }
            if hidden and not unlisted:
                _filter["doc_id"] = {"$nin": sorted(hidden)}
            try:
                response = index.query(
                    namespace=namespace,
                    vector=query_vector,
                    top_k=fetch_k,
                    include_metadata=True,
                    filter=_filter,
                )
            except Exception:
                # Some Pinecone index versions reject the filter silently;
                # retry once unfiltered, then re-filter in memory.
                response = index.query(
                    namespace=namespace,
                    vector=query_vector,
                    top_k=fetch_k,
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
        if unlisted and results:
            from engine.knowledge.document_acl import hidden_among

            gone = await hidden_among(
                {r.metadata.get("doc_id", "") for r in results}, hidden, kb_ids
            )
            results = [r for r in results if r.metadata.get("doc_id") not in gone]
        return results

    except EmbeddingProviderError:
        # Bubble up — caller distinguishes provider outage from no-match.
        raise
    except Exception as e:
        logger.error("Vector search failed: %s", e)
        _search_note(f"Vector search failed and returned nothing, {str(e)[:200]}")
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
_VISIBLE = visible("{v}")


# limits per query so one hub entity cannot run the database out of memory
GRAPH_NAME_MATCHES = 25
GRAPH_FANOUT = 25
GRAPH_SCAN_CAP = 1000
GRAPH_FRONTIER_CAP = 50
GRAPH_RESULT_CAP = 30
GRAPH_RELATIONSHIP_CAP = 20
GRAPH_MAX_HOPS = 4
GRAPH_SEARCH_DEADLINE_S = float(os.environ.get("GRAPH_SEARCH_DEADLINE_S", "20"))


def _graph_scoped_params(kb_id: str, tenant_id: str, hidden_list: list[str]) -> dict:
    return {"kb_id": kb_id, "tenant_id": tenant_id or "", "hidden": hidden_list}


def _match_names_cypher() -> str:
    """Exact names through the unique index, each a single index seek."""
    return f"""
    UNWIND $names AS wanted
    MATCH (e:Entity {{kb_id: $kb_id, canonical_name: wanted}})
    WHERE {entity_scope("e")} AND {_VISIBLE.format(v="e")}
    RETURN e.canonical_name AS name, e.entity_type AS type,
           e.description AS description, e.mention_count AS mentions,
           e.pg_id AS pg_id
    """


def _match_aliases_cypher() -> str:
    """Aliases and partial names through the fulltext index, the KB filter is in the query."""
    return f"""
    UNWIND $queries AS q
    CALL db.index.fulltext.queryNodes($index, q, {{limit: $limit}})
    YIELD node AS e
    WITH DISTINCT e
    WHERE {entity_scope("e")} AND {_VISIBLE.format(v="e")}
    RETURN e.canonical_name AS name, e.entity_type AS type,
           e.description AS description, e.mention_count AS mentions,
           e.pg_id AS pg_id
    LIMIT $limit
    """


def _hop_cypher() -> str:
    """One hop from the frontier, capped per node before it sorts."""
    return f"""
    UNWIND $frontier AS origin
    MATCH (s:Entity {{kb_id: $kb_id, canonical_name: origin}})
    WHERE {entity_scope("s")}
    CALL {{
        WITH s
        MATCH (s)-[r]->(c:Entity {{kb_id: $kb_id}})
        WITH r, c LIMIT $scan
        WITH r, c
        WHERE {_VISIBLE.format(v="c")} AND {_VISIBLE.format(v="r")}
        RETURN r, c
        ORDER BY coalesce(r.weight, 0) DESC, coalesce(c.mention_count, 0) DESC
        LIMIT $fanout
    }}
    RETURN s.canonical_name AS origin, type(r) AS rel_type,
           c.canonical_name AS name, c.entity_type AS type,
           c.description AS description, c.mention_count AS mention_count
    """


def _direct_relationships_cypher() -> str:
    """Relationships touching the matches, walked from each match rather than OR over both ends."""
    return f"""
    UNWIND $names AS matched
    MATCH (m:Entity {{kb_id: $kb_id, canonical_name: matched}})
    WHERE {entity_scope("m")}
    CALL {{
        WITH m
        MATCH (m)-[r]-(o:Entity {{kb_id: $kb_id}})
        WITH m, r, o LIMIT $scan
        WITH m, r, o
        WHERE {_VISIBLE.format(v="r")} AND {_VISIBLE.format(v="o")} AND {_VISIBLE.format(v="m")}
        RETURN r, startNode(r) AS a, endNode(r) AS b
        ORDER BY coalesce(r.weight, 0) DESC
        LIMIT $fanout
    }}
    WITH DISTINCT r, a, b
    RETURN a.canonical_name AS source, type(r) AS rel_type,
           b.canonical_name AS target, r.description AS description,
           r.weight AS weight
    ORDER BY weight DESC
    LIMIT $limit
    """


async def _graph_search(
    entity_names: list[str],
    kb_ids: list[str],
    depth: int = 2,
    hidden: set[str] | frozenset[str] = frozenset(),
    tenant_id: str = "",
    notes: list[str] | None = None,
) -> tuple[list[SearchResult], list[str]]:
    """Search the knowledge graph for entities and their relationships.

    Returns: (search_results, found_entity_names)
    """
    results: list[SearchResult] = []
    found_entities: list[str] = []
    hidden_list = sorted(hidden)
    deadline = time.monotonic() + GRAPH_SEARCH_DEADLINE_S
    try:
        await ensure_schema()
    except Exception as e:
        logger.debug("graph schema check failed: %s", e)
    driver = await get_neo4j_driver()

    def out_of_time() -> bool:
        if time.monotonic() < deadline:
            return False
        if notes is not None:
            notes.append("Graph results are partial, the traversal hit its time limit.")
        return True

    async with driver.session(database=_NEO4J_DATABASE) as session:
        for kb_id in kb_ids:
            if out_of_time():
                break
            params = _graph_scoped_params(kb_id, tenant_id, hidden_list)
            matched: dict[str, Any] = {}

            exact = await session.run(
                cypher(_match_names_cypher()), names=entity_names, **params
            )
            async for record in exact:
                matched[record["name"]] = record

            if len(matched) < len(entity_names):
                try:
                    await ensure_kb_keys(kb_id, tenant_id)
                    fuzzy = await session.run(
                        cypher(_match_aliases_cypher()),
                        index=FULLTEXT_INDEX,
                        queries=[fulltext_query(kb_id, n) for n in entity_names],
                        limit=GRAPH_NAME_MATCHES,
                        **params,
                    )
                    async for record in fuzzy:
                        matched.setdefault(record["name"], record)
                except Exception as e:
                    logger.warning("graph name search failed for kb %s: %s", kb_id, e)

            matched_names = list(matched)[:GRAPH_NAME_MATCHES]
            for name in matched_names:
                record = matched[name]
                found_entities.append(name)
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

            # Walk one hop at a time so a limit bounds the work, not only the answer
            safe_depth = max(1, min(GRAPH_MAX_HOPS, int(depth)))
            chains: dict[str, list[str]] = {n: [] for n in matched_names}
            frontier = matched_names[:GRAPH_FRONTIER_CAP]
            reached = 0
            for hop in range(1, safe_depth + 1):
                if not frontier or reached >= GRAPH_RESULT_CAP or out_of_time():
                    break
                step = await session.run(
                    cypher(_hop_cypher()),
                    frontier=frontier,
                    scan=GRAPH_SCAN_CAP,
                    fanout=GRAPH_FANOUT,
                    **params,
                )
                rows = [dict(r) async for r in step]
                rows.sort(key=lambda r: -(r["mention_count"] or 0))
                next_frontier: list[str] = []
                for record in rows:
                    name = record["name"]
                    if name in chains or reached >= GRAPH_RESULT_CAP:
                        continue
                    chain = chains[record["origin"]] + [record["rel_type"]]
                    chains[name] = chain
                    next_frontier.append(name)
                    reached += 1
                    # Score decreases with hops
                    hop_penalty = 1.0 / (1 + hop * 0.3)
                    rel_chain = " → ".join(chain)
                    results.append(
                        SearchResult(
                            content=f"{name} ({record['type']}): {record['description'] or 'No description'} [via: {rel_chain}]",
                            score=0.7 * hop_penalty,
                            source=name,
                            source_type="graph_context",
                            metadata={
                                "kb_id": kb_id,
                                "hops": hop,
                                "relationship_chain": rel_chain,
                            },
                        )
                    )
                frontier = next_frontier[:GRAPH_FRONTIER_CAP]

            if out_of_time():
                break
            rel_query = await session.run(
                cypher(_direct_relationships_cypher()),
                names=matched_names,
                scan=GRAPH_SCAN_CAP,
                fanout=GRAPH_FANOUT,
                limit=GRAPH_RELATIONSHIP_CAP,
                **params,
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
