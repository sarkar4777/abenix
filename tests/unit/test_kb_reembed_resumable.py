"""Re-embed in slices against real Postgres, with a flip that is one row update."""

from __future__ import annotations

import uuid

import pytest
from kb_pg import make_doc, make_kb, make_tenant

from worker.tasks import document_processor as dp
from worker.tasks import kb_reembed

NEW = "text-embedding-3-small"


@pytest.fixture
def embed(monkeypatch):
    calls = []

    def fake(chunks, model=None, strict=False):
        calls.append(list(chunks))
        return [[0.2] * 1536 for _ in chunks], True

    monkeypatch.setattr(dp, "_embed_chunks", fake)
    return calls


def _job(cur, tenant, kb, target=1, to_model=NEW, status="queued"):
    jid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO kb_reembed_jobs (id, tenant_id, kb_id, from_model, to_model, backend, "
        "from_generation, target_generation, status, documents_total, documents_done, "
        "chunks_done, from_file, from_indexed_text) VALUES "
        "(%s, %s, %s, 'local-hashing-v1', %s, 'pgvector', 0, %s, %s, 0, 0, 0, 0, 0)",
        (jid, tenant, kb, to_model, target, status),
    )
    return jid


def _gens(cur, kb):
    cur.execute(
        "SELECT embedding_generation, count(*) FROM chunks WHERE collection_id = %s "
        "GROUP BY 1 ORDER BY 1",
        (kb,),
    )
    return dict(cur.fetchall())


def _visible(cur, kb):
    """What the search queries read."""
    cur.execute(
        "SELECT count(*) FROM chunks c WHERE c.collection_id = %s AND EXISTS ("
        "SELECT 1 FROM knowledge_collections k WHERE k.id = c.collection_id "
        "AND k.deleted_at IS NULL AND k.embedding_generation = c.embedding_generation)",
        (kb,),
    )
    return cur.fetchone()[0]


def _setup(cur, docs=4, chunks=3):
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    ids = [
        make_doc(
            cur,
            kb,
            [f"doc {d} chunk {i}" for i in range(chunks)],
            metadata={"policy_id": f"P{d}"},
        )
        for d in range(docs)
    ]
    return tenant, kb, ids


def test_slices_resume_and_only_the_flip_moves_queries(kb_conn, embed):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur)
    job = _job(cur, tenant, kb)
    queue: list[str] = []

    # a zero slice stops after every document, like a worker that keeps restarting
    for _ in range(50):
        result = kb_reembed.reembed_slice(job, slice_seconds=0, requeue=queue.append)
        if result["status"] != "continuing":
            break
        cur.execute(
            "SELECT embedding_model, embedding_generation FROM knowledge_collections "
            "WHERE id = %s",
            (kb,),
        )
        model, generation = cur.fetchone()
        if generation == 0:
            assert model == "local-hashing-v1"
            assert _visible(cur, kb) == 12
    assert result["status"] == "completed"
    assert len(queue) >= 3
    assert sum(len(c) for c in embed) == 12

    cur.execute(
        "SELECT embedding_model, embedding_generation FROM knowledge_collections WHERE id = %s",
        (kb,),
    )
    assert cur.fetchone() == (NEW, 1)
    assert _gens(cur, kb) == {1: 12}
    assert _visible(cur, kb) == 12
    cur.execute(
        "SELECT status, documents_done, chunks_done, flipped_at IS NOT NULL "
        "FROM kb_reembed_jobs WHERE id = %s",
        (job,),
    )
    assert cur.fetchone() == ("completed", 4, 12, True)
    cur.execute(
        "SELECT DISTINCT metadata->>'policy_id' FROM chunks WHERE collection_id = %s",
        (kb,),
    )
    assert {r[0] for r in cur.fetchall()} == {"P0", "P1", "P2", "P3"}


def test_pause_stops_and_resume_does_not_redo_finished_documents(kb_conn, embed):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur)
    job = _job(cur, tenant, kb)

    real = dp._embed_chunks
    seen = {"n": 0}

    def pause_after_first_doc(chunks, model=None, strict=False):
        seen["n"] += 1
        out = real(chunks, model, strict)
        if seen["n"] == 1:
            cur.execute(
                "UPDATE kb_reembed_jobs SET status = 'pausing' WHERE id = %s", (job,)
            )
        return out

    dp._embed_chunks = pause_after_first_doc
    try:
        result = kb_reembed.reembed_slice(job, requeue=lambda _j: None)
    finally:
        dp._embed_chunks = real
    assert result["status"] == "paused"
    cur.execute(
        "SELECT status, documents_done FROM kb_reembed_jobs WHERE id = %s", (job,)
    )
    assert cur.fetchone() == ("paused", 1)
    assert _visible(cur, kb) == 12
    assert _gens(cur, kb) == {0: 12, 1: 3}

    # a paused job ignores a stray task
    assert kb_reembed.reembed_slice(job, requeue=lambda _j: None)["status"] == "paused"

    before = sum(len(c) for c in embed)
    cur.execute("UPDATE kb_reembed_jobs SET status = 'queued' WHERE id = %s", (job,))
    assert (
        kb_reembed.reembed_slice(job, requeue=lambda _j: None)["status"] == "completed"
    )
    assert sum(len(c) for c in embed) - before == 9
    assert _gens(cur, kb) == {1: 12}


def test_provider_failure_leaves_search_alone_and_can_resume(
    kb_conn, monkeypatch, embed
):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=2)
    job = _job(cur, tenant, kb)
    real = dp._embed_chunks
    count = {"n": 0}

    def flaky(chunks, model=None, strict=False):
        count["n"] += 1
        if count["n"] == 2:
            raise RuntimeError("provider down")
        return real(chunks, model, strict)

    monkeypatch.setattr(dp, "_embed_chunks", flaky)
    result = kb_reembed.reembed_slice(job, requeue=lambda _j: None)
    assert result["status"] == "failed" and "provider down" in result["error"]
    assert _visible(cur, kb) == 6
    cur.execute(
        "SELECT embedding_generation FROM knowledge_collections WHERE id = %s", (kb,)
    )
    assert cur.fetchone()[0] == 0

    cur.execute("UPDATE kb_reembed_jobs SET status = 'queued' WHERE id = %s", (job,))
    assert (
        kb_reembed.reembed_slice(job, requeue=lambda _j: None)["status"] == "completed"
    )
    assert _gens(cur, kb) == {1: 6}


def test_a_document_arriving_mid_job_is_taken_before_the_flip(
    kb_conn, monkeypatch, embed
):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=1)
    job = _job(cur, tenant, kb)
    real = dp._embed_chunks
    added = {"done": False}

    def adds_a_document(chunks, model=None, strict=False):
        if not added["done"]:
            added["done"] = True
            make_doc(cur, kb, ["late arrival"])
        return real(chunks, model, strict)

    monkeypatch.setattr(dp, "_embed_chunks", adds_a_document)
    assert (
        kb_reembed.reembed_slice(job, requeue=lambda _j: None)["status"] == "completed"
    )
    assert _gens(cur, kb) == {1: 4}


def test_a_document_deleted_while_being_staged_does_not_stop_the_job(
    kb_conn, monkeypatch, embed
):
    cur = kb_conn.cursor()
    tenant, kb, ids = _setup(cur, docs=2)
    job = _job(cur, tenant, kb)
    real = dp._embed_chunks
    gone = {"done": False}

    def deletes_a_document(chunks, model=None, strict=False):
        if not gone["done"]:
            gone["done"] = True
            cur.execute(
                "DELETE FROM documents WHERE id = (SELECT document_id FROM chunks "
                "WHERE collection_id = %s AND content = %s LIMIT 1)",
                (kb, chunks[0]),
            )
        return real(chunks, model, strict)

    monkeypatch.setattr(dp, "_embed_chunks", deletes_a_document)
    out = kb_reembed.reembed_slice(job, requeue=lambda _j: None)
    assert out["status"] == "completed", out
    assert _gens(cur, kb) == {1: 3}


def test_spend_limit_pauses_with_the_reason(kb_conn, embed):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=1)
    cur.execute(
        "INSERT INTO tenant_knowledge_quotas (tenant_id, monthly_embedding_usd) VALUES (%s, 0)",
        (tenant,),
    )
    job = _job(cur, tenant, kb)
    result = kb_reembed.reembed_slice(job, requeue=lambda _j: None)
    assert result["status"] == "paused"
    assert "Embedding has cost" in result["error"]
    assert embed == []
    assert _visible(cur, kb) == 3


def test_cancel_removes_staged_rows_and_never_flips(kb_conn, embed):
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=2)
    job = _job(cur, tenant, kb)
    assert (
        kb_reembed.reembed_slice(job, slice_seconds=0, requeue=lambda _j: None)[
            "status"
        ]
        == "continuing"
    )
    assert 1 in _gens(cur, kb)
    cur.execute(
        "UPDATE kb_reembed_jobs SET status = 'cancelling' WHERE id = %s", (job,)
    )
    assert (
        kb_reembed.reembed_slice(job, requeue=lambda _j: None)["status"] == "cancelled"
    )
    assert _gens(cur, kb) == {0: 6}
    cur.execute(
        "SELECT embedding_generation, embedding_model FROM knowledge_collections WHERE id = %s",
        (kb,),
    )
    assert cur.fetchone() == (0, "local-hashing-v1")


def test_one_live_job_per_collection_is_a_database_rule(kb_conn):
    import psycopg2

    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=1)
    _job(cur, tenant, kb)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _job(cur, tenant, kb, target=2)


def test_pinecone_flip_moves_namespace_and_drops_the_old_one(
    kb_conn, monkeypatch, embed
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant, backend="pinecone")
    doc = make_doc(cur, kb, [])
    cur.execute("UPDATE documents SET chunk_count = 2 WHERE id = %s", (doc,))

    class Index:
        def __init__(self):
            self.ns = {
                kb: {
                    f"{doc}_0": {"text": "one", "policy_id": "P9"},
                    f"{doc}_1": {"text": "two", "policy_id": "P9"},
                }
            }
            self.deleted = []

        def fetch(self, ids, namespace):
            have = self.ns.get(namespace, {})
            return {"vectors": {i: {"metadata": have[i]} for i in ids if i in have}}

        def list(self, namespace):
            yield list(self.ns.get(namespace, {}))

        def upsert(self, vectors, namespace):
            self.ns.setdefault(namespace, {}).update(
                {v["id"]: v["metadata"] for v in vectors}
            )

        def delete(self, ids=None, namespace=None, delete_all=False):
            self.deleted.append(namespace)
            if delete_all:
                self.ns.pop(namespace, None)

    index = Index()
    monkeypatch.setattr(dp, "PINECONE_API_KEY", "k")
    monkeypatch.setattr(kb_reembed, "_pinecone_index", lambda: index)
    jid = _job(cur, tenant, kb)
    cur.execute("UPDATE kb_reembed_jobs SET backend = 'pinecone' WHERE id = %s", (jid,))
    assert (
        kb_reembed.reembed_slice(jid, requeue=lambda _j: None)["status"] == "completed"
    )
    assert list(index.ns) == [f"{kb}.g1"]
    assert index.ns[f"{kb}.g1"][f"{doc}_0"]["policy_id"] == "P9"


# the API


def _admin(tenant):
    from types import SimpleNamespace

    from models.user import UserRole

    return SimpleNamespace(id=None, tenant_id=uuid.UUID(tenant), role=UserRole.ADMIN)


@pytest.fixture
def session_factory(kb_db_url):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_api_starts_refuses_a_second_and_controls_the_job(
    kb_conn, session_factory, monkeypatch
):
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.routers import knowledge_v2 as api

    monkeypatch.setattr(api, "log_action", AsyncMock())
    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=1)
    user = _admin(tenant)
    kb_id = uuid.UUID(kb)
    body = api.ReembedRequest(embedding_model="text-embedding-3-large")
    with patch("app.services.kb_lifecycle.send_task") as send:
        async with session_factory() as db:
            first = await api.reembed_kb(kb_id, body, MagicMock(), user, db)
        assert first.status_code == 202
        assert json.loads(first.body)["data"]["chunks_to_reembed"] == 3
        job = json.loads(first.body)["data"]["job_id"]
        assert send.call_args[0] == (
            "worker.tasks.kb_reembed.run",
            {"job_id": job},
        )
        cur.execute(
            "SELECT embedding_model, embedding_generation FROM knowledge_collections "
            "WHERE id = %s",
            (kb,),
        )
        assert cur.fetchone() == ("local-hashing-v1", 0)

        async with session_factory() as db:
            second = await api.reembed_kb(kb_id, body, MagicMock(), user, db)
        assert second.status_code == 409

        async with session_factory() as db:
            paused = await api.pause_reembed(kb_id, user=user, db=db)
        assert json.loads(paused.body)["data"]["status"] == "paused"
        async with session_factory() as db:
            state = await api.reembed_status(kb_id, user=user, db=db)
        assert json.loads(state.body)["data"]["job"]["status"] == "paused"
        async with session_factory() as db:
            resumed = await api.resume_reembed(kb_id, user=user, db=db)
        assert json.loads(resumed.body)["data"]["status"] == "queued"
        async with session_factory() as db:
            cancelled = await api.cancel_reembed(kb_id, user=user, db=db)
        assert json.loads(cancelled.body)["data"]["status"] == "cancelling"
        async with session_factory() as db:
            late = await api.pause_reembed(kb_id, user=user, db=db)
        assert late.status_code == 409


@pytest.mark.asyncio
async def test_a_job_whose_worker_died_is_sent_again(kb_conn, session_factory):
    from unittest.mock import patch

    from app.services.kb_lifecycle import sweep_stuck_jobs

    cur = kb_conn.cursor()
    tenant, kb, _ids = _setup(cur, docs=1)
    job = _job(cur, tenant, kb, status="running")
    cur.execute(
        "UPDATE kb_reembed_jobs SET heartbeat_at = now() - interval '1 hour' WHERE id = %s",
        (job,),
    )
    with patch("app.services.kb_lifecycle.send_task") as send:
        async with session_factory() as db:
            await sweep_stuck_jobs(db)
    sent = [
        c[0][1]["job_id"]
        for c in send.call_args_list
        if c[0][0].endswith("kb_reembed.run")
    ]
    assert job in sent
