"""KB re-embed, Pinecone vacuum and their wiring into the worker and the API."""

from __future__ import annotations

import json
import re
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from worker.celery_app import celery_app
from worker.tasks import document_processor as dp
from worker.tasks import pinecone_vacuum

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


# re-embed runs on real Postgres in test_kb_reembed_resumable.py


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
        [(KB, 0, False)],
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


def test_vacuum_drops_old_generations_and_leaves_a_running_reembed_alone():
    busy = str(uuid.uuid4())

    class _Index:
        def __init__(self):
            self.deleted = []

        def describe_index_stats(self):
            return {"namespaces": {KB: {}, f"{KB}.g2": {}, f"{busy}.g1": {}}}

        def list(self, namespace):
            yield [f"{D1}_0", f"{D1}_5"]

        def delete(self, **kw):
            self.deleted.append(kw)

    cur = MagicMock()
    cur.fetchall.side_effect = [
        [(KB, 2, False), (busy, 0, True)],
        [(KB, D1, 1, "READY"), (busy, D2, 1, "READY")],
        [],
    ]
    index = _Index()
    out = pinecone_vacuum.vacuum(index, cur)
    assert {"delete_all": True, "namespace": KB} in index.deleted
    assert {"ids": [f"{D1}_5"], "namespace": f"{KB}.g2"} in index.deleted
    assert not any(d.get("namespace") == f"{busy}.g1" for d in index.deleted)
    assert out["namespaces_dropped"] == 1


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


def test_supported_models_all_fit_the_index():
    import embedding_models as em

    assert em.DIM == 1536
    assert "local-hashing-v1" in em.SUPPORTED
    assert all(re.match(r"^[a-z0-9-]+$", m) for m in em.SUPPORTED)
