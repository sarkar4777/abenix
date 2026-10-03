"""Knowledge search wiring: document ACL pre-filter, per-collection embedding
models, reranking, citations, Cognify confidence and conflicts, extractors."""

from __future__ import annotations

import asyncio
import sys
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.knowledge import document_acl, hybrid_search as hs, reranker
from engine.knowledge.cognify_pipeline import _hold_back
from engine.knowledge.entity_extractor import (
    ExtractedEntity,
    ExtractedRelationship,
    _confidence,
)
from engine.knowledge.entity_resolver import resolve_entities
from engine.knowledge.hybrid_search import SearchMode, SearchResult

KB1, KB2 = str(uuid.uuid4()), str(uuid.uuid4())
D1, D2 = str(uuid.uuid4()), str(uuid.uuid4())


# document ACL


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.stmts = []

    async def execute(self, stmt):
        self.stmts.append(stmt)
        res = MagicMock()
        res.all.return_value = self.rows
        return res


@pytest.mark.asyncio
async def test_admin_sees_every_document_without_a_query():
    s = _Session([(D1,)])
    assert await document_acl.hidden_document_ids(s, [KB1], user_role="admin") == set()
    assert s.stmts == []


@pytest.mark.asyncio
async def test_restricted_documents_come_back_hidden():
    s = _Session([(D1,)])
    uid, aid = uuid.uuid4(), uuid.uuid4()
    hidden = await document_acl.hidden_document_ids(
        s, [KB1, "user-legacy-ns"], user_id=uid, user_role="user", agent_id=aid
    )
    assert hidden == {D1}
    stmt = s.stmts[0]
    sql = str(stmt)
    assert "document_grants" in sql and "user_collection_grants" in sql
    params = stmt.compile().params
    assert params["kb_ids"] == [uuid.UUID(KB1)]
    assert params["uid"] == uid and params["aid"] == aid


# hybrid search


@pytest.fixture
def no_cache(monkeypatch):
    from engine.knowledge import search_cache

    seen = {}

    def key(**kw):
        seen.update(kw)
        return "k"

    monkeypatch.setattr(search_cache, "cache_key", key)
    monkeypatch.setattr(search_cache, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(search_cache, "set", AsyncMock())
    return seen


def _chunk(text, score, doc=D2, idx=0):
    return SearchResult(
        content=text,
        score=score,
        source="contract.pdf",
        source_type="chunk",
        metadata={"kb_id": KB1, "doc_id": doc, "chunk_index": idx, "page": 4},
    )


@pytest.mark.asyncio
async def test_search_passes_the_hidden_set_and_scopes_the_cache(monkeypatch, no_cache):
    monkeypatch.delenv("RERANKER_PROVIDER", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.setattr(document_acl, "hidden_for_search", AsyncMock(return_value={D1}))
    captured = {}

    async def vs(query, kb_ids, top_k=20, hidden=frozenset()):
        captured["hidden"] = hidden
        return [_chunk("clause 7", 0.9)]

    monkeypatch.setattr(hs, "_vector_search", vs)
    resp = await hs.hybrid_search(
        "termination", [KB1], mode=SearchMode.VECTOR, tenant_id="t", user_id="u"
    )
    assert captured["hidden"] == {D1}
    assert no_cache["scope"] and no_cache["scope"] == hs._acl_scope({D1})
    assert resp.hidden_documents == 1
    cite = resp.results[0].metadata["citation"]
    assert cite["document_id"] == D2 and cite["page"] == 4
    assert cite["anchor_url"] == "contract.pdf · page 4 · chunk 0"


@pytest.mark.asyncio
async def test_reranker_reorders_and_keeps_the_retrieval_score(monkeypatch, no_cache):
    monkeypatch.setenv("RERANKER_PROVIDER", "cohere")
    monkeypatch.setattr(
        document_acl, "hidden_for_search", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        hs,
        "_vector_search",
        AsyncMock(return_value=[_chunk("a", 0.9, idx=0), _chunk("b", 0.5, idx=1)]),
    )

    async def fake_rerank(query, items, top_k=10, text_key="content"):
        return [dict(items[1], score=0.99, reranker="cohere")]

    monkeypatch.setattr(reranker, "rerank", fake_rerank)
    resp = await hs.hybrid_search("q", [KB1], mode=SearchMode.VECTOR, top_k=1)
    assert [r.content for r in resp.results] == ["b"]
    assert resp.results[0].score == 0.99
    assert resp.results[0].metadata["retrieval_score"] == 0.5


def test_llm_reranker_is_opt_in(monkeypatch):
    monkeypatch.delenv("RERANKER_PROVIDER", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert reranker.provider() == "none"
    monkeypatch.setenv("RERANKER_PROVIDER", "llm")
    assert reranker.provider() == "llm"


@pytest.mark.asyncio
async def test_each_collection_is_queried_with_its_own_model(monkeypatch):
    monkeypatch.setattr(
        hs,
        "_kb_index_settings",
        AsyncMock(
            return_value={
                KB1: ("pgvector", "text-embedding-3-large"),
                KB2: ("pgvector", "local-hashing-v1"),
            }
        ),
    )
    calls = []

    async def pgv(query, ids, top_k, model=None, hidden=frozenset()):
        calls.append((tuple(ids), model, hidden))
        return []

    monkeypatch.setattr(hs, "_vector_search_pgvector", pgv)
    await hs._vector_search("q", [KB1, KB2], hidden={D1})
    assert sorted(calls) == sorted(
        [((KB1,), "text-embedding-3-large", {D1}), ((KB2,), "local-hashing-v1", {D1})]
    )


@pytest.mark.asyncio
async def test_local_model_collections_embed_locally_even_with_a_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    vec = await hs._embed_query("termination clause", "local-hashing-v1")
    assert len(vec) == 1536


def test_model_names_follow_the_collection(monkeypatch):
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("AZURE_EMBEDDING_DEPLOYMENT", "emb-small")
    assert hs._model_names(None) == ("text-embedding-3-small", "emb-small", {})
    assert hs._model_names("text-embedding-3-large") == (
        "text-embedding-3-large",
        "text-embedding-3-large",
        {"dimensions": 1536},
    )


@pytest.mark.asyncio
async def test_pinecone_search_filters_hidden_docs_and_reads_sdk_objects(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "pc")
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.setattr(hs, "_embed_query", AsyncMock(return_value=[0.1] * 4))
    seen = {}

    class _Match:
        def __init__(self, doc, score):
            self.score = score
            self.metadata = {
                "doc_id": doc,
                "text": f"text {doc}",
                "filename": "f.pdf",
                "chunk_index": 2,
            }

    class _Index:
        def query(self, **kw):
            seen.update(kw)
            return types.SimpleNamespace(matches=[_Match(D2, 0.8), _Match(D1, 0.7)])

    fake = types.ModuleType("pinecone")
    fake.Pinecone = lambda api_key: types.SimpleNamespace(Index=lambda name: _Index())
    monkeypatch.setitem(sys.modules, "pinecone", fake)
    out = await hs._vector_search_pinecone("q", [KB1], 5, None, {D1})
    assert seen["filter"]["doc_id"] == {"$nin": [D1]}
    assert [r.metadata["doc_id"] for r in out] == [D2]


@pytest.mark.asyncio
async def test_graph_search_hands_the_hidden_set_to_every_query(monkeypatch):
    calls = []

    class _Res:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _S:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def run(self, cypher, **kw):
            calls.append((cypher, kw))
            return _Res()

    driver = types.SimpleNamespace(session=lambda: _S())
    monkeypatch.setattr(hs, "get_neo4j_driver", AsyncMock(return_value=driver))
    await hs._graph_search(["Acme"], [KB1], hidden={D1})
    assert calls and all(kw["hidden"] == [D1] for _c, kw in calls)
    assert "NOT d IN $hidden" in calls[0][0]


# Cognify confidence and conflicts


def _ent(name, etype, doc, conf=1.0):
    return ExtractedEntity(
        name=name,
        entity_type=etype,
        description=f"{name} as {etype}",
        source_doc_id=doc,
        confidence=conf,
    )


def test_confidence_parsing():
    assert _confidence(None) == 1.0
    assert _confidence("0.42") == 0.42
    assert _confidence(87) == 0.87
    assert _confidence(-3) == 0.0


@pytest.mark.asyncio
async def test_type_disagreement_is_flagged_and_the_stored_type_kept():
    res = await resolve_entities(
        [_ent("Acme", "product", D1, 0.95)],
        [],
        existing_entities=[
            {
                "canonical_name": "Acme",
                "entity_type": "organization",
                "aliases": [],
                "source_doc_ids": [D2],
                "confidence": 0.9,
            }
        ],
    )
    assert res.entities[0].entity_type == "organization"
    c = res.conflicts[0]
    assert (c.status, c.a_value, c.b_value, c.a_doc_id, c.b_doc_id) == (
        "open",
        "organization",
        "product",
        D2,
        D1,
    )


@pytest.mark.asyncio
async def test_higher_confidence_wins_when_configured():
    res = await resolve_entities(
        [
            _ent("Acme", "product", D1, 0.6),
            _ent("Acme", "organization", D2, 0.97),
            _ent("Acme", "product", D1, 0.5),
        ],
        [],
        conflict_action="higher_conf_wins",
    )
    assert res.entities[0].entity_type == "organization"
    assert res.conflicts[0].status == "auto_resolved"
    assert res.conflicts[0].resolved_value == "organization"


@pytest.mark.asyncio
async def test_split_keeps_both_types_linked_as_variants():
    res = await resolve_entities(
        [
            _ent("Mercury", "location", D1),
            _ent("Mercury", "technology", D2),
            _ent("Mercury", "location", D1),
        ],
        [],
        conflict_action="split",
    )
    names = {e.canonical_name: e.entity_type for e in res.entities}
    assert names == {"Mercury": "location", "Mercury (technology)": "technology"}
    rel = res.relationships[0]
    assert (rel.source, rel.relationship_type, rel.target) == (
        "Mercury (technology)",
        "VARIANT_OF",
        "Mercury",
    )


@pytest.mark.asyncio
async def test_threshold_holds_back_unsure_proposals_and_their_edges():
    res = await resolve_entities(
        [
            _ent("Acme", "organization", D1, 0.95),
            _ent("Maybe Corp", "organization", D1, 0.4),
        ],
        [
            ExtractedRelationship(
                "Acme", "Maybe Corp", "OWNS", "", source_doc_id=D1, confidence=0.9
            ),
            ExtractedRelationship(
                "Acme", "Acme", "SELF", "", source_doc_id=D1, confidence=0.3
            ),
        ],
    )
    ents, rels, held = _hold_back(res.entities, res.relationships, 0.85)
    assert [e.canonical_name for e in ents] == ["Acme"]
    assert rels == []
    assert {h["name"] for h in held} == {"Maybe Corp", "Acme SELF Acme"}
    same = _hold_back(res.entities, res.relationships, 0.0)
    assert len(same[0]) == 2 and same[2] == []


# extractors


def test_extractor_uses_the_stored_file_type_over_the_path(tmp_path):
    from engine.knowledge.extractors import extract_document

    f = tmp_path / "blob"
    f.write_text("hello knowledge", encoding="utf-8")
    blocks, method, quality = asyncio.run(extract_document(str(f), file_type="txt"))
    assert method == "text_plain" and quality == 1.0
    assert blocks[0].text == "hello knowledge"


def test_docx_falls_back_to_python_docx(tmp_path):
    docx = pytest.importorskip("docx")
    from engine.knowledge.extractors import extract_document

    d = docx.Document()
    d.add_paragraph("Termination requires 30 days notice.")
    path = tmp_path / "c.docx"
    d.save(str(path))
    blocks, method, _q = asyncio.run(extract_document(str(path)))
    assert "30 days" in blocks[0].text
    assert method in ("office", "docx")
