"""KB re-embed, Pinecone vacuum and their wiring into the worker and the API."""

from __future__ import annotations

import json
import re
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp
from worker.tasks import kb_reembed, pinecone_vacuum

KB = str(uuid.uuid4())
D1, D2 = str(uuid.uuid4()), str(uuid.uuid4())


# celery wiring


def test_both_tasks_are_included_and_routed_to_a_consumed_queue():
    include = celery_app.conf.include
    assert "worker.tasks.kb_reembed" in include
    assert "worker.tasks.pinecone_vacuum" in include
    routes = celery_app.conf.task_routes
    assert routes["worker.tasks.kb_reembed.*"]["queue"] == "documents"
    assert routes["worker.tasks.pinecone_vacuum.*"]["queue"] == "documents"
    assert "worker.tasks.kb_reembed.run" in celery_app.tasks
    assert "worker.tasks.pinecone_vacuum.run" in celery_app.tasks


# re-embed


class _Cursor:
    def __init__(self, db):
        self.db = db
        self._rows = []

    def execute(self, sql, params=None):
        self.db.log.append((" ".join(sql.split()), params))
        s = sql.lower()
        if "pg_try_advisory_lock" in s:
            self._rows = [(self.db.lock_free,)]
        elif "from knowledge_collections where id" in s and "vector_backend" in s:
            self._rows = [("pgvector", "text-embedding-3-small", 500, 50, "READY")]
        elif "from documents where kb_id" in s:
            self._rows = self.db.docs
        elif "select content, metadata from chunks" in s:
            self._rows = [("indexed text", {"page": 2})]
        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, db):
        self.db = db
        self.autocommit = False

    def cursor(self):
        return _Cursor(self.db)

    def commit(self):
        self.db.commits += 1

    def rollback(self):
        self.db.rollbacks += 1

    def close(self):
        pass


class _DB:
    def __init__(self, docs, lock_free=True):
        self.docs = docs
        self.lock_free = lock_free
        self.log: list = []
        self.commits = 0
        self.rollbacks = 0

    def sql(self):
        return [s for s, _p in self.log]


class _Progress:
    def __init__(self):
        self.state = {}

    def update(self, **kw):
        self.state.update(kw)


def _docs():
    return [
        (D1, "a.pdf", "pdf", "/data/a.pdf", 3),
        (D2, "b.md", "md", "/data/missing.md", 1),
    ]


def _run(monkeypatch, db, embed=None, blocks=None):
    import psycopg2

    monkeypatch.setattr(psycopg2, "connect", lambda url: _Conn(db))
    monkeypatch.setattr(dp, "_local_path", lambda p, t: (p, None))

    def extract(path, ftype):
        if blocks is not None:
            return blocks(path)
        if "missing" in path:
            raise FileNotFoundError(path)
        return [("page one text", 1), ("page two text", 2)], "text_pdf", 1.0

    monkeypatch.setattr(dp, "_extract_blocks", extract)
    monkeypatch.setattr(
        dp,
        "_embed_chunks",
        embed
        or (
            lambda chunks, model=None, strict=False: ([[0.5] * 4 for _ in chunks], True)
        ),
    )
    monkeypatch.setattr(kb_reembed, "_invalidate_search_cache", lambda kb: None)
    progress = _Progress()
    out = kb_reembed.reembed_collection(
        kb_id=KB, new_model="text-embedding-3-large", job_id="j1", progress=progress
    )
    return out, progress


def test_reembed_stages_everything_then_swaps_in_one_go(monkeypatch):
    db = _DB(_docs())
    out, progress = _run(monkeypatch, db)
    assert out["status"] == "completed", out
    assert out["documents"] == 2
    assert (out["from_file"], out["from_indexed_text"]) == (1, 1)
    sql = db.sql()
    stage_inserts = [s for s in sql if s.startswith("INSERT INTO reembed_stage")]
    assert len(stage_inserts) == 3
    swap = next(i for i, s in enumerate(sql) if s.startswith("DELETE FROM chunks"))
    last_stage = max(
        i for i, s in enumerate(sql) if s.startswith("INSERT INTO reembed_stage")
    )
    assert swap > last_stage
    flip = next(
        (s, p)
        for s, p in db.log
        if s.startswith("UPDATE knowledge_collections SET embedding_model")
    )
    assert flip[1][0] == "text-embedding-3-large"
    deleted = next(p for s, p in db.log if s.startswith("DELETE FROM chunks"))
    assert set(deleted[1]) == {D1, D2}
    assert progress.state["status"] == "completed"
    assert progress.state["documents_done"] == 2


def test_a_failed_embedding_swaps_nothing_and_restores_the_status(monkeypatch):
    db = _DB(_docs())

    def boom(chunks, model=None, strict=False):
        assert strict is True
        raise dp.EmbeddingProviderError("quota")

    out, progress = _run(monkeypatch, db, embed=boom)
    assert out["status"] == "failed"
    sql = db.sql()
    assert not any(s.startswith("DELETE FROM chunks") for s in sql)
    assert not any("SET embedding_model" in s for s in sql)
    restore = [
        p
        for s, p in db.log
        if s.startswith("UPDATE knowledge_collections SET status = %s")
    ]
    assert restore and restore[-1][0] == "READY"
    assert progress.state["status"] == "failed"
    assert "quota" in progress.state["error"]


def test_concurrent_reembed_is_skipped(monkeypatch):
    db = _DB(_docs(), lock_free=False)
    out, progress = _run(monkeypatch, db)
    assert out["status"] == "skipped"
    assert progress.state["status"] == "skipped"


def test_unsupported_model_is_refused(monkeypatch):
    progress = _Progress()
    out = kb_reembed.reembed_collection(
        kb_id=KB, new_model="voyage-3", job_id="j", progress=progress
    )
    assert out["status"] == "failed"
    assert "not a supported" in out["error"]


def test_vector_packing_round_trips():
    vec = [0.25, -1.5, 3.0]
    assert kb_reembed._unpack(kb_reembed._pack(vec)) == vec


# ingestion


def test_page_aware_chunking():
    chunks, pages = dp._chunk_blocks([("one " * 10, 1), ("two " * 10, 2)], 1000, 0)
    assert pages == [1, 2]
    chunks, pages = dp._chunk_blocks([("plain text", None)], 1000, 0)
    assert chunks == ["plain text"] and pages == [None]


def test_local_model_collection_embeds_locally(monkeypatch):
    monkeypatch.setattr(dp, "OPENAI_API_KEY", "sk")
    vecs, real = dp._embed_chunks(["termination"], "local-hashing-v1")
    assert real and len(vecs[0]) == 1536


def test_strict_embedding_never_falls_back(monkeypatch):
    monkeypatch.setattr(dp, "OPENAI_API_KEY", "")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ABENIX_LOCAL_EMBEDDINGS", "1")
    with pytest.raises(dp.EmbeddingProviderError):
        dp._embed_chunks(["x"], "text-embedding-3-small", strict=True)
    vecs, real = dp._embed_chunks(["x"], "text-embedding-3-small")
    assert real and len(vecs[0]) == 1536


def test_extraction_records_method_and_pages(tmp_path):
    f = tmp_path / "blob"
    f.write_text("hello", encoding="utf-8")
    blocks, method, quality = dp._extract_blocks(str(f), "md")
    assert blocks == [("hello", 1)]
    assert (method, quality) == ("text_plain", 1.0)


# vacuum


def test_doc_orphans_only_trims_known_documents():
    docs = {D1.lower(): (2, "READY"), D2.lower(): (0, "PROCESSING")}
    ids = [f"{D1}_0", f"{D1}_1", f"{D1}_2", f"{D2}_0", f"{uuid.uuid4()}_0", "odd"]
    assert pinecone_vacuum.doc_orphans(ids, docs) == [f"{D1}_2"]


def test_persona_orphans():
    live, gone = str(uuid.uuid4()), str(uuid.uuid4())
    items = {live: (False, {f"{live}:0"}), gone: (True, {f"{gone}:0"})}
    ids = [f"{live}:0", f"{live}:1", f"{gone}:0", f"{uuid.uuid4()}:0"]
    assert pinecone_vacuum.persona_orphans(ids, items) == ids[1:]


def test_vacuum_end_to_end_with_fakes():
    dead_kb = str(uuid.uuid4())
    tenant = str(uuid.uuid4())

    class _Index:
        def __init__(self):
            self.deleted = []

        def describe_index_stats(self):
            return {
                "namespaces": {
                    KB: {},
                    dead_kb: {},
                    f"persona:{tenant}": {},
                    "user-x": {},
                }
            }

        def list(self, namespace):
            if namespace == KB:
                yield [f"{D1}_0", f"{D1}_5"]
            else:
                yield ["gone:0"]

        def delete(self, **kw):
            self.deleted.append(kw)

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [(KB,)],
        [(KB, D1, 1, "READY")],
        [],
    ]
    index = _Index()
    out = pinecone_vacuum.vacuum(index, cur)
    assert out["deleted"] == 2
    assert out["namespaces_dropped"] == 1
    assert {"delete_all": True, "namespace": dead_kb} in index.deleted
    assert {"ids": [f"{D1}_5"], "namespace": KB} in index.deleted
    assert {"ids": ["gone:0"], "namespace": f"persona:{tenant}"} in index.deleted
    assert not any(d.get("namespace") == "user-x" for d in index.deleted)


# API side


@pytest.mark.asyncio
async def test_enqueue_sends_to_the_documents_queue(monkeypatch):
    from app.workers import kb_reembed as api

    sent = {}

    def fake_send(name, kwargs=None, task_id=None):
        sent.update(name=name, kwargs=kwargs, task_id=task_id)

    redis = MagicMock()
    redis.set = AsyncMock()
    monkeypatch.setattr(api, "_send", fake_send)
    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=redis))
    job = await api.enqueue_reembed(kb_id=uuid.UUID(KB), new_model="local-hashing-v1")
    assert sent["name"] == "worker.tasks.kb_reembed.run"
    assert sent["task_id"] == str(job)
    assert api.QUEUE == "documents"
    key, raw = redis.set.call_args.args
    assert key == f"kb_reembed:{KB}" and json.loads(raw)["status"] == "queued"


@pytest.mark.asyncio
async def test_vacuum_enqueue_is_deduped(monkeypatch):
    from app.workers import kb_reembed as api

    redis = MagicMock()
    redis.set = AsyncMock(side_effect=[True, None])
    sends = []
    monkeypatch.setattr(api, "_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(api, "_send", lambda name, *a, **k: sends.append(name))
    assert await api.enqueue_pinecone_vacuum() is True
    assert await api.enqueue_pinecone_vacuum() is False
    assert sends == ["worker.tasks.pinecone_vacuum.run"]


def _user(role="admin"):
    from models.user import UserRole

    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.uuid4()
    u.role = UserRole(role)
    return u


def _db_with_kb(model="text-embedding-3-small"):
    kb = MagicMock()
    kb.embedding_model = model
    first = MagicMock()
    first.scalar_one_or_none.return_value = kb
    counts = MagicMock()
    counts.all.return_value = [(4,), (6,)]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[first, counts])
    db.commit = AsyncMock()
    return db, kb


def _body(model, dry=False):
    from app.routers.knowledge_v2 import ReembedRequest

    return ReembedRequest(embedding_model=model, dry_run=dry)


def _json(resp):
    return json.loads(resp.body)


@pytest.mark.asyncio
async def test_reembed_endpoint_rejects_unknown_models():
    from app.routers.knowledge_v2 import reembed_kb

    db, _kb = _db_with_kb()
    resp = await reembed_kb(uuid.UUID(KB), _body("voyage-3"), MagicMock(), _user(), db)
    assert resp.status_code == 400
    assert "local-hashing-v1" in _json(resp)["error"]["message"]


@pytest.mark.asyncio
async def test_reembed_endpoint_queues_and_leaves_the_model_to_the_worker():
    from app.routers.knowledge_v2 import reembed_kb

    db, kb = _db_with_kb()
    job = uuid.uuid4()
    with patch(
        "app.workers.kb_reembed.get_status", AsyncMock(return_value=None)
    ), patch(
        "app.workers.kb_reembed.enqueue_reembed", AsyncMock(return_value=job)
    ) as enq, patch(
        "app.routers.knowledge_v2.log_action", AsyncMock()
    ):
        resp = await reembed_kb(
            uuid.UUID(KB), _body("text-embedding-3-large"), MagicMock(), _user(), db
        )
    assert resp.status_code == 202
    data = _json(resp)["data"]
    assert data["job_id"] == str(job) and data["chunks_to_reembed"] == 10
    assert kb.embedding_model == "text-embedding-3-small"
    assert enq.await_args.kwargs["new_model"] == "text-embedding-3-large"


@pytest.mark.asyncio
async def test_reembed_endpoint_refuses_a_second_live_job():
    from datetime import datetime, timezone

    from app.routers.knowledge_v2 import reembed_kb

    db, _kb = _db_with_kb()
    live = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    with patch("app.workers.kb_reembed.get_status", AsyncMock(return_value=live)):
        resp = await reembed_kb(
            uuid.UUID(KB), _body("text-embedding-3-large"), MagicMock(), _user(), db
        )
    assert resp.status_code == 409


def test_stale_jobs_do_not_block():
    from datetime import datetime, timedelta, timezone

    from app.routers.knowledge_v2 import _job_is_live

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    assert _job_is_live({"status": "queued", "queued_at": old}) is False
    assert _job_is_live({"status": "running", "started_at": old}) is True
    assert _job_is_live({"status": "completed"}) is False


def test_supported_models_all_fit_the_index():
    import embedding_models as em

    assert em.DIM == 1536
    assert "local-hashing-v1" in em.SUPPORTED
    assert all(re.match(r"^[a-z0-9-]+$", m) for m in em.SUPPORTED)
