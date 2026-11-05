"""When embeddings fail, knowledge search matches by keywords and says so, never faking 'no match'."""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, patch

import pytest

from engine.knowledge import hybrid_search as hs


def _hit(text: str) -> hs.SearchResult:
    return hs.SearchResult(
        content=text, score=0.5, source="plan.md", source_type="chunk", metadata={}
    )


def _run(error=None, **kw):
    async def go():
        with (
            patch(
                "engine.knowledge.document_acl.hidden_for_search",
                AsyncMock(return_value=set()),
            ),
            patch(
                "engine.knowledge.document_acl.superseded_for_search",
                AsyncMock(return_value=set()),
            ),
            patch.object(hs, "is_neo4j_available", AsyncMock(return_value=False)),
            patch.object(hs, "_rerank", AsyncMock(side_effect=lambda q, r, k: r[:k])),
            patch.object(
                hs,
                "_vector_search",
                AsyncMock(
                    side_effect=error or hs.EmbeddingProviderError("429 no credits")
                ),
            ),
            patch.object(hs, "_keyword_search_pg", AsyncMock(**kw)),
        ):
            return await hs.hybrid_search(
                "worker in swing radius", ["kb"], use_cache=False
            )

    return asyncio.run(go())


def test_embedding_outage_falls_back_to_keywords_and_says_so():
    res = _run(return_value=[_hit("Stop when a worker is inside the swing radius")])
    assert [r.content for r in res.results] == [
        "Stop when a worker is inside the swing radius"
    ]
    assert res.mode_used == "keyword"
    assert "embedding provider is unavailable" in res.degraded
    assert "429 no credits" in res.degraded


def test_no_keyword_hits_still_reports_the_outage():
    with pytest.raises(hs.EmbeddingProviderError):
        _run(return_value=[])


def test_keyword_hits_do_not_count_as_vector_hits():
    res = _run(return_value=[_hit("a"), _hit("b")])
    assert res.vector_results_count == 0


def test_no_provider_configured_searches_by_keywords_and_says_so():
    res = _run(
        error=hs.NoEmbeddingProvider("no embedding provider is configured"),
        return_value=[_hit("Stop when a worker is inside the swing radius")],
    )
    assert res.mode_used == "keyword"
    assert "no embedding provider is configured" in res.degraded
    assert len(res.results) == 1


def test_no_provider_and_no_keyword_hit_is_empty_with_a_reason_not_an_outage():
    res = _run(
        error=hs.NoEmbeddingProvider("no embedding provider is configured"),
        return_value=[],
    )
    assert res.results == []
    assert res.mode_used == "keyword"
    assert "no embedding provider is configured" in res.degraded


@pytest.mark.parametrize("backend", ["pgvector", "pinecone"])
def test_vector_paths_report_a_missing_provider_instead_of_an_empty_page(
    backend, monkeypatch
):
    for name in ("AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PINECONE_API_KEY", "k")
    monkeypatch.setattr(hs, "_embed_query", AsyncMock(return_value=None))
    search = (
        hs._vector_search_pgvector
        if backend == "pgvector"
        else hs._vector_search_pinecone
    )

    async def go():
        await search("q", ["kb"], 5)

    fake_pinecone = types.ModuleType("pinecone")
    fake_pinecone.Pinecone = object
    monkeypatch.setitem(sys.modules, "pinecone", fake_pinecone)
    with pytest.raises(hs.NoEmbeddingProvider):
        asyncio.run(go())


def test_a_failed_pinecone_search_leaves_a_note(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "k")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(hs, "_embed_query", AsyncMock(side_effect=OSError("down")))
    fake_pinecone = types.ModuleType("pinecone")
    fake_pinecone.Pinecone = object
    monkeypatch.setitem(sys.modules, "pinecone", fake_pinecone)

    async def go():
        notes = []
        token = hs._SEARCH_NOTES.set(notes)
        try:
            assert await hs._vector_search_pinecone("q", ["kb"], 5) == []
        finally:
            hs._SEARCH_NOTES.reset(token)
        return notes

    notes = asyncio.run(go())
    assert notes and "down" in notes[0]


def _tool_result(response):
    from engine.tools.knowledge_search import KnowledgeSearchTool

    tool = KnowledgeSearchTool(kb_ids=["kb"])
    with patch(
        "engine.knowledge.hybrid_search.hybrid_search",
        AsyncMock(return_value=response),
    ):
        return asyncio.run(tool.execute({"query": "swing radius"}))


def test_the_tool_passes_degraded_on_with_results_and_without():
    why = "Searched by keywords because no embedding provider is configured."
    empty = _tool_result(
        hs.HybridSearchResponse(results=[], mode_used="keyword", degraded=why)
    )
    assert empty.metadata["degraded"] == why and why in empty.content
    hits = _tool_result(
        hs.HybridSearchResponse(results=[_hit("a")], mode_used="keyword", degraded=why)
    )
    assert hits.metadata["degraded"] == why and why in hits.content
