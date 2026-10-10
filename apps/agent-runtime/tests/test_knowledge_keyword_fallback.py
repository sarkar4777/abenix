"""When embeddings fail, knowledge search matches by keywords and says so, never faking 'no match'."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from engine.knowledge import hybrid_search as hs


def _hit(text: str) -> hs.SearchResult:
    return hs.SearchResult(
        content=text, score=0.5, source="plan.md", source_type="chunk", metadata={}
    )


def _run(**kw):
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
                AsyncMock(side_effect=hs.EmbeddingProviderError("429 no credits")),
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
