"""knowledge_store follows the worker's rule, a refused key is visible and schemes never mix."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from engine.knowledge import hybrid_search as hs
from engine.tools.knowledge_store import KnowledgeStoreTool

KB = "11111111-1111-1111-1111-111111111111"
OPENAI_MODEL = "text-embedding-3-small"


class Refused(Exception):
    status_code = 401


def _tool(monkeypatch, *, embed, moved=True, model=OPENAI_MODEL, backend="pinecone"):
    tool = KnowledgeStoreTool(kb_ids=[KB])
    stored: dict = {}

    async def store(kb_id, doc_id, title, chunks, embeddings, metadata=None):
        stored["embeddings"] = embeddings
        return len(embeddings)

    monkeypatch.delenv("ABENIX_LOCAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(
        hs, "_kb_index_settings", AsyncMock(return_value={KB: (backend, model)})
    )
    monkeypatch.setattr(hs, "embed_for_collection", embed)
    monkeypatch.setattr(tool, "_store_vectors", store)
    monkeypatch.setattr(tool, "_move_empty_to_local", AsyncMock(return_value=moved))
    return tool, stored


async def _run(tool):
    return await tool.execute({"content": "hello world", "title": "Note"})


async def test_refused_key_on_an_empty_collection_uses_the_local_embedder(monkeypatch):
    tool, stored = _tool(monkeypatch, embed=AsyncMock(side_effect=Refused("401 bad")))
    result = await _run(tool)
    assert not result.is_error
    assert len(stored["embeddings"][0]) == 1536
    assert "local hashing embedder" in result.content and "401 bad" in result.content
    assert "401 bad" in result.metadata["warnings"][0]
    tool._move_empty_to_local.assert_awaited_once_with(KB, "local-hashing-v1")


async def test_refused_key_on_a_filled_collection_stores_nothing_and_errors(
    monkeypatch,
):
    tool, stored = _tool(
        monkeypatch, embed=AsyncMock(side_effect=Refused("401 bad")), moved=False
    )
    result = await _run(tool)
    assert result.is_error
    assert stored == {}
    assert result.metadata["vector_indexed"] is False
    assert "cannot be searched" in result.content and "401 bad" in result.content


async def test_a_forced_off_local_embedder_stores_nothing(monkeypatch):
    tool, stored = _tool(monkeypatch, embed=AsyncMock(side_effect=Refused("401 bad")))
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    result = await _run(tool)
    assert result.is_error and stored == {}
    tool._move_empty_to_local.assert_not_awaited()


async def test_no_provider_at_all_is_an_error_that_says_what_to_set(monkeypatch):
    tool, stored = _tool(monkeypatch, embed=AsyncMock(return_value=None))
    result = await _run(tool)
    assert result.is_error and stored == {}
    assert "ABENIX_LOCAL_EMBEDDINGS" in result.content


async def test_the_collection_model_is_the_one_embedded_with(monkeypatch):
    embed = AsyncMock(return_value=[[0.1] * 1536])
    tool, _stored = _tool(monkeypatch, embed=embed, model="text-embedding-3-large")
    result = await _run(tool)
    assert not result.is_error and result.metadata["vector_indexed"] is True
    assert embed.await_args.args[1] == "text-embedding-3-large"


async def test_a_vector_store_failure_is_not_reported_as_stored(monkeypatch):
    tool, _stored = _tool(monkeypatch, embed=AsyncMock(return_value=[[0.1] * 1536]))
    monkeypatch.setattr(
        tool, "_store_vectors", AsyncMock(side_effect=RuntimeError("index missing"))
    )
    result = await _run(tool)
    assert result.is_error
    assert "index missing" in result.content
    assert "stored in knowledge base" not in result.content


async def test_a_pgvector_collection_stores_in_postgres_not_pinecone(monkeypatch):
    embed = AsyncMock(return_value=[[0.1] * 1536])
    tool, stored = _tool(monkeypatch, embed=embed, backend="pgvector")
    to_postgres = AsyncMock(return_value=1)
    monkeypatch.setattr(tool, "_store_vectors_pgvector", to_postgres)
    result = await _run(tool)
    assert not result.is_error
    to_postgres.assert_awaited_once()
    assert not stored


async def test_query_and_store_share_one_embedder(monkeypatch):
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "1")
    many = await hs.embed_for_collection(["alpha", "beta"], OPENAI_MODEL)
    assert len(many) == 2
    assert await hs._embed_query("alpha", OPENAI_MODEL) == many[0]


async def test_no_provider_and_no_local_gives_none(monkeypatch):
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    assert await hs.embed_for_collection(["a"], OPENAI_MODEL) is None
    assert await hs._embed_query("a", OPENAI_MODEL) is None


async def test_provider_errors_reach_the_caller_of_the_shared_embedder(monkeypatch):
    class Dead:
        def __init__(self, api_key=None):
            self.embeddings = self

        async def create(self, **_kw):
            raise Refused("401 bad")

    import openai

    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dead")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai, "AsyncOpenAI", Dead)
    with pytest.raises(Refused):
        await hs.embed_for_collection(["a"], OPENAI_MODEL)
