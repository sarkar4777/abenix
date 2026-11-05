"""The upload and listing routes against real Postgres and a real storage directory."""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import kb_pg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from kb_pg import make_kb, make_tenant
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server_url():
    import os

    if os.environ.get("KB_SCALE_TEST_URL"):
        yield os.environ["KB_SCALE_TEST_URL"]
        return
    if not kb_pg.docker_works():
        pytest.skip("docker is not available")
    name = f"abenix-kbapi-test-{uuid.uuid4().hex[:8]}"
    port = kb_pg.free_port()
    kb_pg.run_postgres(name, port)
    url = f"postgresql://postgres:test@127.0.0.1:{port}/abenix"
    try:
        kb_pg.wait_for_postgres(url)
        yield url
    finally:
        subprocess.run([kb_pg.docker(), "rm", "-f", name], capture_output=True)


@pytest.fixture(scope="module")
def api_url(server_url):
    import psycopg2
    from sqlalchemy import create_engine, text

    sys.path.insert(0, str(ROOT / "packages" / "db"))
    import chunks_store as cs
    import models  # noqa: F401
    from bootstrap import _create_missing_enums_sync
    from models.base import Base

    name = f"api_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(server_url)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    admin.close()
    url = server_url.rsplit("/", 1)[0] + f"/{name}"
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        _create_missing_enums_sync(conn)
        Base.metadata.create_all(bind=conn)
        for stmt in cs.startup_plan(None, "0.8.0"):
            conn.execute(text(stmt))
        state = conn.execute(text(cs.STATE_SQL)).first()
        conn.execute(text(cs.hnsw_plan(state[0], state[1])))
    engine.dispose()
    return url


@pytest.fixture
def world(api_url, monkeypatch, tmp_path):
    import psycopg2

    from app.core.deps import get_current_user, get_db
    from app.routers import knowledge, knowledge_ingest
    from engine import storage as storage_pkg
    from engine.storage import service

    monkeypatch.setattr(service, "STORAGE_LOCAL_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_instance", None)
    assert storage_pkg

    conn = psycopg2.connect(api_url)
    conn.autocommit = True
    cur = conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant, model="m")
    user = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant),
        role=SimpleNamespace(value="admin"),
    )
    dispatched: list[dict] = []
    monkeypatch.setattr(
        knowledge, "_dispatch_processing", lambda **kw: dispatched.append(kw) or True
    )

    async def allow(*a, **k):
        return True

    for mod in (knowledge, knowledge_ingest):
        monkeypatch.setattr(mod, "user_can_access_collection", allow)
        monkeypatch.setattr(mod, "user_can_edit_collection", allow)

    async def no_quota(*a, **k):
        return None

    from app.services import kb_quota

    monkeypatch.setattr(kb_quota, "quota_error", no_quota)

    app = FastAPI()
    app.include_router(knowledge.router)
    app.include_router(knowledge_ingest.router)
    async_url = api_url.replace("postgresql://", "postgresql+asyncpg://")
    statements: list[str] = []

    async def db_dep():
        engine = create_async_engine(async_url)

        def log(conn_, cursor, statement, params, context, many):
            statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", log)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
        await engine.dispose()

    app.dependency_overrides[get_db] = db_dep
    app.dependency_overrides[get_current_user] = lambda: user
    yield SimpleNamespace(
        app=app,
        kb=kb,
        cur=cur,
        tmp=tmp_path,
        dispatched=dispatched,
        statements=statements,
        tenant=tenant,
        url=async_url,
        user=user,
    )
    conn.close()


def call(world, fn):
    async def go():
        transport = ASGITransport(app=world.app)
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            return await fn(client)

    return asyncio.run(go())


def _files(world):
    return [p for p in world.tmp.rglob("*") if p.is_file()]


def test_upload_stores_the_file_records_its_hash_and_a_repeat_is_a_duplicate(world):
    body = b"hello large world" * 1000

    async def two(client):
        one = await client.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": ("a.txt", body, "text/plain")},
        )
        again = await client.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": ("copy-of-a.txt", body, "text/plain")},
        )
        return one, again

    one, again = call(world, two)
    assert one.status_code == 201
    doc = one.json()["data"]
    assert doc["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert doc["duplicate"] is False
    assert again.status_code == 200
    assert again.json()["data"]["duplicate"] is True
    assert again.json()["data"]["id"] == doc["id"]
    assert len(world.dispatched) == 1
    assert len(_files(world)) == 1
    assert _files(world)[0].read_bytes() == body


@pytest.mark.parametrize(
    "name,ctype",
    [
        (
            "a.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("a.html", "text/html"),
        ("a.msg", "application/vnd.ms-outlook"),
        ("b.msg", "application/octet-stream"),
        ("c.pptx", "application/octet-stream"),
        ("c.xlsx", "application/octet-stream"),
        ("c.html", "application/octet-stream"),
    ],
)
def test_wider_file_types_are_accepted(world, name, ctype):
    resp = call(
        world,
        lambda c: c.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": (name, uuid.uuid4().bytes, ctype)},
        ),
    )
    assert resp.status_code == 201, resp.text


def test_an_unknown_type_is_refused_with_the_list(world):
    resp = call(
        world,
        lambda c: c.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": ("a.exe", b"x", "application/x-msdownload")},
        ),
    )
    assert resp.status_code == 400 and "PPTX" in resp.text


def test_a_failed_document_uploaded_again_resumes_instead_of_refusing(world):
    body = b"failed once" * 100

    async def go(client):
        first = await client.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": ("a.txt", body, "text/plain")},
        )
        world.cur.execute(
            "UPDATE documents SET status = 'FAILED', error_message = 'x', "
            "ingest_checkpoint = 40, ingest_attempts = 6 WHERE id = %s",
            (first.json()["data"]["id"],),
        )
        return await client.post(
            f"/api/knowledge-bases/{world.kb}/upload",
            files={"file": ("a.txt", body, "text/plain")},
        )

    resp = call(world, go)
    data = resp.json()["data"]
    assert data["resumed"] is True and data["status"] == "processing"
    assert data["ingest_checkpoint"] == 40
    world.cur.execute(
        "SELECT ingest_attempts FROM documents WHERE id = %s", (data["id"],)
    )
    assert world.cur.fetchone()[0] == 0
    assert len(world.dispatched) == 2


def test_bulk_route_answers_per_file(world):
    same = b"twice"

    async def go(client):
        return await client.post(
            f"/api/knowledge-bases/{world.kb}/upload-bulk",
            files=[
                ("files", ("a.txt", same, "text/plain")),
                ("files", ("b.txt", same, "text/plain")),
                ("files", ("c.exe", b"x", "application/x-msdownload")),
                ("files", ("d.md", b"# other", "text/markdown")),
            ],
        )

    resp = call(world, go)
    assert resp.status_code == 200
    payload = resp.json()
    assert [r["status"] for r in payload["data"]] == [201, 200, 400, 201]
    assert payload["meta"]["created"] == 2 and payload["meta"]["duplicates"] == 1
    assert payload["meta"]["failed"] == 1


def test_plan_then_stream_stores_through_the_api(world):
    body = b"streamed bytes " * 5000
    sha = hashlib.sha256(body).hexdigest()

    async def go(client):
        plan = await client.post(
            f"/api/knowledge-bases/{world.kb}/uploads",
            json={"files": [{"filename": "big.txt", "size": len(body), "sha256": sha}]},
        )
        step = plan.json()["data"][0]
        assert step["mode"] == "stream"
        put = await client.put(step["url"], content=body)
        later = await client.post(
            f"/api/knowledge-bases/{world.kb}/uploads",
            json={
                "files": [{"filename": "big2.txt", "size": len(body), "sha256": sha}]
            },
        )
        return put, later

    put, later = call(world, go)
    assert put.status_code == 201
    assert put.json()["data"]["content_sha256"] == sha
    assert later.json()["data"][0]["mode"] == "duplicate"
    assert any(p.read_bytes() == body for p in _files(world))


def test_stream_with_the_wrong_size_or_hash_stores_nothing(world):
    async def go(client):
        plan = await client.post(
            f"/api/knowledge-bases/{world.kb}/uploads",
            json={"files": [{"filename": "x.txt", "size": 99}]},
        )
        return await client.put(plan.json()["data"][0]["url"], content=b"short")

    resp = call(world, go)
    assert resp.status_code == 400 and "Expected 99" in resp.text
    assert _files(world) == []


def test_a_forged_or_foreign_token_is_refused(world):
    from app.services import kb_ingest

    other_kb = str(uuid.uuid4())
    token = kb_ingest.sign_upload(
        {"tenant": world.tenant, "kb": other_kb, "doc": str(uuid.uuid4()), "size": 1}
    )

    async def go(client):
        wrong_kb = await client.put(
            f"/api/knowledge-bases/{world.kb}/uploads/{token}/content", content=b"x"
        )
        forged = await client.put(
            f"/api/knowledge-bases/{world.kb}/uploads/{token[:-1]}0/content",
            content=b"x",
        )
        return wrong_kb, forged

    wrong_kb, forged = call(world, go)
    assert wrong_kb.status_code == 400 and forged.status_code == 400


def test_direct_plan_when_storage_is_object_storage(world, monkeypatch):
    storage = MagicMock()
    storage.supports_direct_upload.return_value = True

    async def start(tenant, path, size, ctype):
        return {
            "kind": "s3_multipart",
            "uri": f"s3://b/{tenant}/{path}",
            "upload_id": "secret-id",
            "part_size": 64,
            "parts": [{"part_number": 1, "url": "https://s3/1"}],
        }

    async def finish(plan, parts):
        assert plan["upload_id"] == "secret-id"
        assert parts == [{"part_number": 1, "etag": "e"}]
        return plan["uri"]

    async def size_of(uri):
        return 500 * 1024**2

    storage.start_direct_upload = start
    storage.finish_direct_upload = finish
    storage.size_of = size_of
    from app.services import kb_ingest

    monkeypatch.setattr(kb_ingest, "_storage", lambda: storage)

    async def go(client):
        plan = await client.post(
            f"/api/knowledge-bases/{world.kb}/uploads",
            json={"files": [{"filename": "big.pdf", "size": 500 * 1024**2}]},
        )
        step = plan.json()["data"][0]
        assert step["mode"] == "direct"
        assert "upload_id" not in step["upload"]
        return await client.post(
            step["complete_url"], json={"parts": [{"part_number": 1, "etag": "e"}]}
        )

    resp = call(world, go)
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["file_size"] == 500 * 1024**2
    assert world.dispatched[-1]["verify_content"] is True


def test_a_file_past_2gb_fits_the_column(world):
    world.cur.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, "
        "status, storage_url, version_number, is_current) VALUES "
        "(%s, %s, 'x', 'txt', %s, 0, 'READY', '', 1, true)",
        (str(uuid.uuid4()), world.kb, 5 * 1024**3),
    )
    resp = call(world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}"))
    assert resp.json()["data"]["total_size"] == 5 * 1024**3


def _docs(world, n):
    for i in range(n):
        world.cur.execute(
            "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, "
            "status, storage_url, version_number, is_current) VALUES "
            "(%s, %s, %s, 'txt', 10, 3, %s, '', 1, true)",
            (str(uuid.uuid4()), world.kb, f"f{i}", "DEGRADED" if i == 0 else "READY"),
        )


def test_get_reads_one_page_and_rolls_up_in_sql(world):
    _docs(world, 250)
    resp = call(world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}?doc_limit=20"))
    data = resp.json()["data"]
    assert len(data["documents"]) == 20
    assert data["documents_total"] == 250
    assert data["chunk_count"] == 750 and data["total_size"] == 2500
    assert data["degraded_doc_count"] == 1 and data["status"] == "degraded"
    assert data["search_language"] == "simple" and data["rerank_mode"] == "auto"


def test_no_route_reads_every_document_row(world):
    _docs(world, 120)

    async def go(client):
        world.statements.clear()
        await client.get(f"/api/knowledge-bases/{world.kb}?doc_limit=10")
        await client.get("/api/knowledge-bases")
        await client.get(f"/api/knowledge-bases/{world.kb}/documents?limit=10")

    call(world, go)
    selects = [
        s
        for s in world.statements
        if "FROM documents" in s and "documents.filename" in s
    ]
    assert selects, world.statements
    assert all("LIMIT" in s and "LIMIT ALL" not in s for s in selects), selects


def test_deleting_a_document_counts_the_rest_in_sql(world, monkeypatch):
    from app.routers import knowledge

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(knowledge, "_delete_file", nothing)
    monkeypatch.setattr(knowledge, "_delete_pinecone_vectors", lambda *a, **k: None)
    _docs(world, 40)
    world.cur.execute("SELECT id FROM documents WHERE kb_id = %s LIMIT 1", (world.kb,))
    doc = world.cur.fetchone()[0]

    async def go(client):
        world.statements.clear()
        return await client.delete(f"/api/knowledge-bases/{world.kb}/documents/{doc}")

    assert call(world, go).status_code == 200
    assert not [
        s
        for s in world.statements
        if "documents.filename" in s and "documents.id !=" in s
    ]
    world.cur.execute(
        "SELECT doc_count FROM knowledge_collections WHERE id = %s", (world.kb,)
    )
    assert world.cur.fetchone()[0] == 39


def test_documents_list_pages_and_counts(world):
    _docs(world, 30)

    async def go(client):
        return await client.get(
            f"/api/knowledge-bases/{world.kb}/documents?limit=10&offset=25"
        )

    payload = call(world, go).json()
    assert len(payload["data"]) == 5
    assert payload["meta"]["total"] == 30 and payload["meta"]["count"] == 5
    first = call(
        world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}/documents?limit=10")
    ).json()
    assert len(first["data"]) == 10 and first["meta"]["total"] == 30


def test_a_bad_language_is_refused():
    from pydantic import ValidationError

    from app.schemas.knowledge import CreateKnowledgeBaseRequest

    assert CreateKnowledgeBaseRequest(name="a", search_language="french")
    with pytest.raises(ValidationError):
        CreateKnowledgeBaseRequest(name="a", search_language="klingon")


def test_settings_can_change_and_a_full_collection_can_not_defer(world):
    from app.routers.knowledge import _deferred_refusal
    from models.knowledge_base import KnowledgeBase

    async def go(client):
        changed = await client.put(
            f"/api/knowledge-bases/{world.kb}",
            json={"search_language": "french", "rerank_mode": "off"},
        )
        return changed

    resp = call(world, go)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["search_language"] == "french" and data["rerank_mode"] == "off"
    world.cur.execute(
        "INSERT INTO documents (id, kb_id, filename, file_type, file_size, chunk_count, "
        "status, storage_url, version_number, is_current) VALUES "
        "(%s, %s, 'x', 'txt', 1, 1, 'READY', '', 1, true) RETURNING id",
        (str(uuid.uuid4()), world.kb),
    )
    doc = world.cur.fetchone()[0]
    world.cur.execute(
        "INSERT INTO chunks (id, collection_id, document_id, chunk_index, content) "
        "VALUES (%s, %s, %s, 0, 'x')",
        (str(uuid.uuid4()), world.kb, doc),
    )

    async def refused():
        engine = create_async_engine(world.url)
        async with AsyncSession(engine) as session:
            kb = await session.get(KnowledgeBase, uuid.UUID(world.kb))
            out = await _deferred_refusal(session, kb)
        await engine.dispose()
        return out

    assert "empty" in asyncio.run(refused())


def test_build_route_only_runs_for_a_deferred_collection(world, monkeypatch):
    import celery

    sent = []

    class FakeCelery:
        def __init__(self, broker=None):
            pass

        def send_task(self, name, args=None, queue=None):
            sent.append((name, args, queue))

    monkeypatch.setattr(celery, "Celery", FakeCelery)
    url = f"/api/knowledge-bases/{world.kb}/index/build"
    assert call(world, lambda c: c.post(url)).status_code == 409
    world.cur.execute(
        "UPDATE knowledge_collections SET index_mode = 'deferred' WHERE id = %s",
        (world.kb,),
    )
    resp = call(world, lambda c: c.post(url))
    assert resp.status_code == 202
    assert sent == [("worker.tasks.kb_index.build", [world.kb], "documents")]
    state = call(world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}/index"))
    assert state.json()["data"]["index_mode"] == "building"
    assert state.json()["data"]["partitioned"] is True


def test_a_restricted_document_stays_out_of_the_page_and_is_counted(world):
    _docs(world, 5)
    world.cur.execute(
        "SELECT id FROM documents WHERE kb_id = %s ORDER BY filename LIMIT 2",
        (world.kb,),
    )
    restricted = [r[0] for r in world.cur.fetchall()]
    other_user = str(uuid.uuid4())
    for doc in restricted:
        world.cur.execute(
            "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, "
            "subject_id, permission) VALUES (%s, %s, %s, 'user', %s, 'read')",
            (str(uuid.uuid4()), doc, world.tenant, other_user),
        )
    world.user.role = SimpleNamespace(value="user")
    payload = call(
        world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}/documents")
    ).json()
    assert payload["meta"]["total"] == 3 and payload["meta"]["hidden"] == 2
    assert not {d["id"] for d in payload["data"]} & set(restricted)
    # the granted user sees theirs, through the same predicate
    world.user.id = uuid.UUID(other_user)
    payload = call(
        world, lambda c: c.get(f"/api/knowledge-bases/{world.kb}/documents")
    ).json()
    assert payload["meta"]["total"] == 5 and payload["meta"]["hidden"] == 0
