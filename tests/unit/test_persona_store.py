"""Persona KB on Postgres: chunking, batching, owner filters, item failure state."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

import persona_vectors as pv


def test_chunk_text_overlaps_and_covers_the_end():
    text = "x" * 3000
    chunks = pv.chunk_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= pv.CHUNK_SIZE for c in chunks)
    assert chunks[-1].endswith("x")
    assert pv.chunk_text("  ") == []
    assert pv.chunk_text("short") == ["short"]


def test_default_model_is_local_with_no_provider(monkeypatch):
    for k in (
        "OPENAI_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_BASE",
        "ABENIX_LOCAL_EMBEDDINGS",
    ):
        monkeypatch.delenv(k, raising=False)
    assert pv.default_model("") == pv.local_model_id()
    assert pv.default_model("sk-test") != pv.local_model_id()
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "1")
    assert pv.default_model("sk-test") == pv.local_model_id()


@pytest.mark.asyncio
async def test_local_embeddings_need_no_key():
    vecs = await pv.embed_texts(["alpha beta", "gamma"], pv.local_model_id())
    assert len(vecs) == 2 and len(vecs[0]) == 1536


@pytest.mark.asyncio
async def test_provider_embeddings_are_batched(monkeypatch):
    calls: list[int] = []

    class FakeEmbeddings:
        async def create(self, model, input, **kw):
            calls.append(len(input))
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1] * 4) for _ in input]
            )

    class FakeClient:
        def __init__(self, api_key):
            self.embeddings = FakeEmbeddings()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    vecs = await pv.embed_texts(
        [f"t{i}" for i in range(250)], "text-embedding-3-small", openai_key="sk"
    )
    assert len(vecs) == 250
    assert calls == [100, 100, 50]


@pytest.mark.asyncio
async def test_missing_provider_gives_a_readable_reason(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    with pytest.raises(pv.PersonaIndexError) as ei:
        await pv.embed_texts(["a"], "text-embedding-3-small", openai_key="")
    assert "OPENAI_API_KEY" in str(ei.value)


def test_every_search_query_filters_on_the_owner():
    for sql in (pv.GROUPS_SQL, pv.VECTOR_SQL, pv.FALLBACK_SQL):
        assert "c.user_id = :u" in sql and "i.user_id = :u" in sql
        assert "c.tenant_id = :t" in sql and "c.persona_scope = :s" in sql
        assert "i.deleted_at IS NULL" in sql


def test_chunk_table_builds_without_the_vector_extension():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    import models  # noqa: F401
    from models.base import Base

    table = Base.metadata.tables["persona_chunks"]
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "REAL[]" in ddl and "vector" not in ddl.lower()
    fk = {fk.parent.name: fk.ondelete for fk in table.foreign_keys}
    assert fk["item_id"] == "CASCADE"
    items = Base.metadata.tables["persona_items"]
    assert {"content", "last_error", "embedding_model"} <= set(items.c.keys())


# API side: a failed index is saved with its reason


class _FakeDB:
    def __init__(self):
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1
        self.added.clear()

    async def refresh(self, obj):
        return None


def _item(text: str):
    from models.meeting import PersonaItem

    return PersonaItem(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        persona_scope="self",
        kind="note",
        title="t",
        status="pending",
        content=text,
        chunk_count=0,
        byte_size=len(text),
    )


@pytest.mark.asyncio
async def test_index_failure_records_last_error(monkeypatch):
    from app.routers import persona

    async def boom(texts, model, *, openai_key=None):
        raise pv.PersonaIndexError("embedding failed, OpenAI: 401 invalid key")

    async def key(_t):
        return "sk-bad"

    monkeypatch.setattr(persona.pv, "embed_texts", boom)
    monkeypatch.setattr(persona, "_openai_key", key)
    db = _FakeDB()
    p = _item("some note text")
    reason = await persona._index(db, p)
    assert p.status == "failed" and p.chunk_count == 0
    assert p.last_error == reason and "401" in reason
    body = json.loads(persona._saved(p, reason).body)
    assert body["data"]["warning"].startswith("Saved but not searchable yet: ")
    assert body["data"]["last_error"] == reason


@pytest.mark.asyncio
async def test_index_success_writes_chunks(monkeypatch):
    from app.routers import persona
    from models.persona_chunk import PersonaChunk

    async def key(_t):
        return ""

    monkeypatch.setattr(persona, "_openai_key", key)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    db = _FakeDB()
    p = _item("y" * 2500)
    assert await persona._index(db, p) is None
    assert p.status == "indexed" and p.last_error is None
    chunks = [o for o in db.added if isinstance(o, PersonaChunk)]
    assert len(chunks) == p.chunk_count == 3
    assert {c.user_id for c in chunks} == {p.user_id}
    assert p.embedding_model == pv.local_model_id()


def test_empty_text_and_size_limits():
    from app.routers import persona

    assert persona._too_long("a" * (pv.MAX_TEXT_CHARS + 1))
    assert persona._too_long("ok") is None
    assert persona._valid_scope("client:acme")
    assert not persona._valid_scope("bad scope")
