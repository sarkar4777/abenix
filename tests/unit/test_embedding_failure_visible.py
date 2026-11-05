"""A dead embedding key is recorded and reported, never a silent READY on the wrong vectors."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import persona_vectors as pv
from worker.tasks import document_processor as dp

KB, DOC = str(uuid.uuid4()), str(uuid.uuid4())
OPENAI_MODEL = "text-embedding-3-small"


class ApiError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


DEAD_KEY = ApiError(401, "Incorrect API key provided")
NO_CREDITS = ApiError(429, "You exceeded your quota, code insufficient_quota")
RATE_LIMITED = ApiError(429, "Rate limit reached, try again in 20s")
OUTAGE = ApiError(503, "upstream unavailable")


def _ingest(monkeypatch, failure, other_docs=False, retries=2, kb_model=OPENAI_MODEL):
    state = {"model": kb_model, "status": None}

    def embed(chunks, model=None, strict=False):
        if model == "local-hashing-v1":
            from local_embeddings import embed_many

            return embed_many(chunks), True
        if failure is None:
            return [[0.5] * 1536 for _ in chunks], True
        raise dp.EmbeddingProviderCallFailed(str(failure), failure)

    def set_model(kb_id, model):
        state["model"] = model

    def status(doc_id, kb_id, s, chunk_count=0, error_message=None, **_kw):
        state["status"], state["chunks"], state["error"] = s, chunk_count, error_message

    def store(kb_id, doc_id, filename, chunks, embeddings, pages, backend):
        state["stored"] = embeddings
        return len(embeddings)

    monkeypatch.setattr(dp, "_local_path", lambda p, t: (p, None))
    monkeypatch.setattr(
        dp, "_extract_blocks", lambda p, t: ([("hello world", None)], "text", 1.0)
    )
    monkeypatch.setattr(dp, "_kb_settings", lambda kb: ("pgvector", state["model"]))
    monkeypatch.setattr(dp, "_embed_chunks", embed)
    monkeypatch.setattr(dp, "_set_collection_model", set_model)
    monkeypatch.setattr(dp, "_collection_has_vectors", lambda kb, doc: other_docs)
    monkeypatch.setattr(dp, "_update_document_status", status)
    monkeypatch.setattr(dp, "_store_vectors", store)
    monkeypatch.setattr(dp.process_document, "update_state", lambda **k: None)
    dp.process_document.push_request(retries=retries)
    try:
        out = dp.process_document.run(DOC, KB, "/tmp/x", "x.md", "md")
    finally:
        dp.process_document.pop_request()
    return out, state


@pytest.mark.parametrize("failure", [DEAD_KEY, NO_CREDITS])
def test_refused_key_on_an_empty_collection_moves_it_to_the_local_embedder(
    monkeypatch, failure
):
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    out, state = _ingest(monkeypatch, failure, retries=0)
    assert out["status"] == "degraded"
    assert state["status"] == "degraded"
    assert state["model"] == "local-hashing-v1"
    assert "local hashing embedder" in state["error"]
    assert str(failure) in state["error"]
    assert state["chunks"] == 1 and len(state["stored"][0]) == 1536


def test_refused_key_on_a_provider_collection_stores_nothing_and_says_so(monkeypatch):
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    out, state = _ingest(monkeypatch, DEAD_KEY, other_docs=True, retries=0)
    assert state["status"] == "degraded" and state["chunks"] == 0
    assert state["model"] == OPENAI_MODEL
    assert "stored" not in state
    assert "cannot be searched" in state["error"]
    assert str(DEAD_KEY) in state["error"]


def test_a_second_document_follows_a_collection_already_moved(monkeypatch):
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    out, state = _ingest(
        monkeypatch, DEAD_KEY, other_docs=True, retries=0, kb_model="local-hashing-v1"
    )
    assert state["model"] == "local-hashing-v1"
    assert state["chunks"] == 1


def test_forced_off_local_embedder_fails_visibly(monkeypatch):
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    out, state = _ingest(monkeypatch, DEAD_KEY, retries=0)
    assert state["status"] == "degraded" and state["chunks"] == 0
    assert state["model"] == OPENAI_MODEL


@pytest.mark.parametrize("failure", [OUTAGE, RATE_LIMITED])
def test_a_passing_failure_retries_before_falling_back(monkeypatch, failure):
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    retried = []

    def retry(exc=None, **_kw):
        retried.append(exc)
        return RuntimeError("retrying")

    monkeypatch.setattr(dp.process_document, "retry", retry)
    with pytest.raises(RuntimeError, match="retrying"):
        _ingest(monkeypatch, failure, retries=0)
    assert retried and isinstance(retried[0], dp.EmbeddingProviderCallFailed)


def test_a_passing_failure_falls_back_once_retries_run_out(monkeypatch):
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    _out, state = _ingest(monkeypatch, OUTAGE, retries=dp.process_document.max_retries)
    assert state["model"] == "local-hashing-v1"
    assert state["status"] == "degraded"


def test_a_healthy_provider_stays_ready_and_unchanged(monkeypatch):
    _out, state = _ingest(monkeypatch, None)
    assert state["status"] == "ready" and state["error"] is None
    assert state["model"] == OPENAI_MODEL


def test_live_failure_raises_instead_of_storing_silently(monkeypatch):
    class Dead:
        def __init__(self, api_key=None):
            self.embeddings = self

        def create(self, **_kw):
            raise DEAD_KEY

    import openai

    monkeypatch.setattr(dp, "OPENAI_API_KEY", "sk-dead")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai, "OpenAI", Dead)
    with pytest.raises(dp.EmbeddingProviderCallFailed) as err:
        dp._embed_chunks(["x"], OPENAI_MODEL)
    assert err.value.refused is True


async def _search(monkeypatch, settings, keys=True):
    from engine.knowledge import hybrid_search as hs

    if keys:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(hs, "is_neo4j_available", AsyncMock(return_value=False))
    monkeypatch.setattr(hs, "_kb_index_settings", AsyncMock(return_value=settings))
    monkeypatch.setattr(hs, "_vector_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(hs, "_rerank", AsyncMock(side_effect=lambda q, r, k: r))
    from engine.knowledge import document_acl

    monkeypatch.setattr(
        document_acl, "hidden_for_search", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        document_acl, "superseded_for_search", AsyncMock(return_value=set())
    )
    return await hs.hybrid_search("q", [KB], use_cache=False)


@pytest.mark.asyncio
async def test_search_on_a_locally_indexed_collection_says_it_is_not_semantic(
    monkeypatch,
):
    res = await _search(monkeypatch, {KB: ("pgvector", "local-hashing-v1")})
    assert "local hashing embedder" in res.degraded


@pytest.mark.asyncio
async def test_search_with_no_provider_key_says_so_too(monkeypatch):
    res = await _search(monkeypatch, {KB: ("pgvector", OPENAI_MODEL)}, keys=False)
    assert "local hashing embedder" in res.degraded


@pytest.mark.asyncio
async def test_search_on_a_provider_collection_is_not_degraded(monkeypatch):
    res = await _search(monkeypatch, {KB: ("pgvector", OPENAI_MODEL)})
    assert res.degraded == ""


@pytest.mark.asyncio
async def test_the_search_api_returns_degraded(monkeypatch):
    from types import SimpleNamespace

    from engine.knowledge import hybrid_search as hs

    from app.routers import knowledge_engine as ke
    from app.schemas.knowledge_engine import SearchRequest

    answer = hs.HybridSearchResponse(results=[], mode_used="keyword", degraded="why")
    monkeypatch.setattr(hs, "hybrid_search", AsyncMock(return_value=answer))
    monkeypatch.setattr(ke, "user_can_access_collection", AsyncMock(return_value=True))
    kb = SimpleNamespace(id=uuid.UUID(KB))
    found = MagicMock()
    found.scalar_one_or_none.return_value = kb
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="admin")
    )
    route = next(
        r.endpoint
        for r in ke.router.routes
        if getattr(r, "path", "").endswith("search")
    )
    resp = await route(uuid.UUID(KB), SearchRequest(query="q"), user=user, db=db)
    assert json.loads(resp.body)["data"]["degraded"] == "why"


@pytest.mark.asyncio
async def test_persona_falls_back_to_local_on_a_dead_key_and_warns(monkeypatch):
    real = pv.embed_texts

    async def dead_provider(texts, model, *, openai_key=None):
        if model == pv.local_model_id():
            return await real(texts, model)
        raise pv.PersonaIndexError("embedding failed, OpenAI 401 invalid key")

    monkeypatch.setattr(pv, "embed_texts", dead_provider)
    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    vectors, model, note = await pv.embed_with_fallback(
        ["alpha"], "text-embedding-3-small", openai_key="sk-dead"
    )
    assert model == pv.local_model_id()
    assert len(vectors[0]) == 1536
    assert "401" in note and "local hashing embedder" in note


@pytest.mark.asyncio
async def test_persona_respects_a_forced_off_local_embedder(monkeypatch):
    async def dead_provider(texts, model, *, openai_key=None):
        raise pv.PersonaIndexError("embedding failed")

    monkeypatch.setattr(pv, "embed_texts", dead_provider)
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    with pytest.raises(pv.PersonaIndexError):
        await pv.embed_with_fallback(["a"], "text-embedding-3-small", openai_key="sk")
