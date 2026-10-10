"""Superseded document versions stay out of search, Cognify and the document list."""

from __future__ import annotations

import asyncio
import inspect
import uuid

from engine.knowledge import document_acl, hybrid_search


def test_superseded_sql_reads_is_current():
    assert "is_current IS FALSE" in document_acl._SUPERSEDED_SQL


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.sql = []

    async def execute(self, stmt):
        self.sql.append(str(stmt))
        return _Rows(self.rows)


def test_superseded_document_ids_returns_old_versions():
    old = str(uuid.uuid4())
    s = _Session([(old,)])
    got = asyncio.run(document_acl.superseded_document_ids(s, [str(uuid.uuid4())]))
    assert got == {old}
    assert "is_current" in s.sql[0]


def test_superseded_document_ids_skips_bad_ids():
    s = _Session([])
    assert asyncio.run(document_acl.superseded_document_ids(s, ["nope"])) == set()
    assert s.sql == []


def test_hybrid_search_drops_superseded(monkeypatch):
    old = str(uuid.uuid4())
    seen = {}

    async def no_hidden(*a, **k):
        return set()

    async def superseded(kb_ids):
        return {old}

    async def vec(query, kb_ids, top_k, hidden):
        seen["hidden"] = set(hidden)
        return []

    monkeypatch.setattr(document_acl, "hidden_for_search", no_hidden)
    monkeypatch.setattr(document_acl, "superseded_for_search", superseded)
    monkeypatch.setattr(hybrid_search, "_vector_search", vec)
    resp = asyncio.run(
        hybrid_search.hybrid_search(
            "q",
            [str(uuid.uuid4())],
            mode=hybrid_search.SearchMode.VECTOR,
            use_cache=False,
        )
    )
    assert old in seen["hidden"]
    # superseded rows are not reported as access-restricted
    assert resp.hidden_documents == 0


def test_pgvector_query_filters_superseded_rows():
    src = inspect.getsource(hybrid_search._vector_search_pgvector)
    assert "is_current IS FALSE" in src


def test_cognify_trigger_and_worker_use_current_only():
    from app.routers import knowledge_engine

    src = inspect.getsource(knowledge_engine)
    assert "Document.is_current.is_(True)" in src
    from worker.tasks import cognify_task

    assert "is_current IS NOT FALSE" in inspect.getsource(
        cognify_task._fetch_document_chunks
    )


def test_document_list_hides_history_unless_asked():
    from app.routers import knowledge

    src = inspect.getsource(knowledge.list_documents)
    assert "Document.is_current.is_(True)" in src
    assert "include_history" in src
    assert "user_can_edit_collection" in src


def test_kb_detail_omits_superseded_and_restricted():
    from types import SimpleNamespace

    from app.routers.knowledge import _serialize_kb

    cur = uuid.uuid4()
    old = uuid.uuid4()
    hidden = uuid.uuid4()

    def doc(i, current=True):
        return SimpleNamespace(
            id=i,
            filename=str(i),
            file_type="txt",
            file_size=1,
            chunk_count=1,
            status="ready",
            error_message=None,
            version_number=1,
            is_current=current,
            parent_document_id=None,
            superseded_by=None,
            created_at=None,
        )

    kb = SimpleNamespace(
        id=uuid.uuid4(),
        name="k",
        description="",
        embedding_model="m",
        chunk_size=1,
        chunk_overlap=0,
        status="ready",
        doc_count=3,
        agent_id=None,
        project_id=None,
        default_visibility="tenant",
        vector_backend="pgvector",
        created_by=None,
        created_at=None,
        updated_at=None,
        documents=[doc(cur), doc(old, current=False), doc(hidden)],
    )
    out = _serialize_kb(kb, include_docs=True, hidden_doc_ids={hidden})
    assert [d["id"] for d in out["documents"]] == [str(cur)]
    assert out["documents"][0]["is_current"] is True
