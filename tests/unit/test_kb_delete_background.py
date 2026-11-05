"""Collection delete: search stops at once, a resumable worker removes everything."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from kb_pg import make_doc, make_kb, make_tenant

from app.routers import knowledge
from models.user import UserRole
from worker.tasks import document_processor as dp
from worker.tasks import kb_delete


def _user(tenant):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant),
        role=UserRole.ADMIN,
        email="a@example.com",
    )


@pytest.fixture
def session_factory(kb_db_url):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core import kb_tombstone

    kb_tombstone.install()
    engine = create_async_engine(
        kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def _delete(session_factory, kb, tenant):
    with patch("app.services.kb_lifecycle.send_task") as send, patch(
        "engine.knowledge.search_cache.invalidate_tenant", AsyncMock()
    ):
        async with session_factory() as db:
            resp = await knowledge.delete_knowledge_base(
                uuid.UUID(kb), force=True, user=_user(tenant), db=db
            )
    return resp, send


def _job_id(resp):
    import json

    return json.loads(resp.body)["data"]["job_id"]


@pytest.mark.asyncio
async def test_delete_hides_at_once_and_the_data_stays_until_the_worker(
    kb_conn, kb_db_url, session_factory, monkeypatch
):
    from sqlalchemy import select

    from engine.knowledge import hybrid_search
    from engine.knowledge.kb_state import live_generations
    from models.knowledge_base import KnowledgeBase

    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["the quick brown fox", "jumps over"])
    url = kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    monkeypatch.setenv("DATABASE_URL", url)

    found = await hybrid_search._keyword_search_pg("quick fox", [kb], 5)
    assert found, "searchable before the delete"

    resp, send = await _delete(session_factory, kb, tenant)
    assert resp.status_code == 200
    send.assert_called_once()
    assert send.call_args[0][0] == "worker.tasks.kb_delete.run"

    assert await hybrid_search._keyword_search_pg("quick fox", [kb], 5) == []
    assert kb not in await live_generations([kb])
    async with session_factory() as db:
        assert (
            await db.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == uuid.UUID(kb))
            )
        ).scalar_one_or_none() is None
        assert await db.get(KnowledgeBase, uuid.UUID(kb)) is None
    cur.execute("SELECT count(*) FROM chunks WHERE collection_id = %s", (kb,))
    assert cur.fetchone()[0] == 2


@pytest.mark.asyncio
async def test_worker_removes_everything_in_resumable_slices(
    kb_conn, session_factory, tmp_path, monkeypatch
):
    monkeypatch.setattr(kb_delete, "CHUNK_BATCH", 2)
    monkeypatch.setattr(kb_delete, "_delete_graph", lambda cur, kb_id: 0)
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    plain = tmp_path / "plain.txt"
    with_scheme = tmp_path / "scheme.txt"
    plain.write_text("x")
    with_scheme.write_text("y")
    d1 = make_doc(cur, kb, [f"c{i}" for i in range(5)], url=str(plain))
    make_doc(cur, kb, ["c"], url=f"file://{with_scheme}")
    cur.execute(
        "INSERT INTO document_grants (id, document_id, tenant_id, subject_type, subject_id, "
        "permission) VALUES (%s, %s, %s, 'user', %s, 'read')",
        (str(uuid.uuid4()), d1, tenant, str(uuid.uuid4())),
    )
    cur.execute(
        "INSERT INTO cognify_jobs (id, tenant_id, kb_id, status, documents_processed, "
        "entities_extracted, entities_merged, relationships_extracted, tokens_used, cost_usd, "
        "anthropic_cost, openai_cost, google_cost, other_cost) VALUES (%s, %s, %s, 'PENDING', "
        "0, 0, 0, 0, 0, 0, 0, 0, 0, 0)",
        (str(uuid.uuid4()), tenant, kb),
    )
    resp, _send = await _delete(session_factory, kb, tenant)
    job = _job_id(resp)

    queue = []
    for _ in range(40):
        out = await asyncio.to_thread(
            kb_delete.delete_slice, job, slice_seconds=0, requeue=queue.append
        )
        if out["status"] != "continuing":
            break
    assert out["status"] == "completed"
    assert queue, "a zero slice has to hand over to the next one"

    for sql in (
        "SELECT count(*) FROM chunks WHERE collection_id = %s",
        "SELECT count(*) FROM documents WHERE kb_id = %s",
        "SELECT count(*) FROM knowledge_collections WHERE id = %s",
        "SELECT count(*) FROM cognify_jobs WHERE kb_id = %s",
    ):
        cur.execute(sql, (kb,))
        assert cur.fetchone()[0] == 0, sql
    cur.execute("SELECT count(*) FROM document_grants WHERE document_id = %s", (d1,))
    assert cur.fetchone()[0] == 0
    assert not plain.exists() and not with_scheme.exists()
    cur.execute(
        "SELECT status, chunks_deleted, documents_deleted, files_deleted, kb_name "
        "FROM kb_delete_jobs WHERE id = %s",
        (job,),
    )
    status, chunks, docs, files, name = cur.fetchone()
    assert (status, chunks, docs, files) == ("completed", 6, 2, 2)
    assert name


@pytest.mark.asyncio
async def test_a_graph_outage_waits_and_keeps_the_data(
    kb_conn, session_factory, monkeypatch
):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["c"])
    cur.execute(
        "INSERT INTO graph_entities (id, tenant_id, kb_id, canonical_name, entity_type, "
        "mention_count, access_count, confidence) VALUES (%s, %s, %s, 'X', 'thing', 1, 0, 1)",
        (str(uuid.uuid4()), tenant, kb),
    )
    resp, _send = await _delete(session_factory, kb, tenant)
    job = _job_id(resp)

    def down(cur_, kb_id):
        raise kb_delete.GraphUnavailable("Neo4j is unreachable")

    monkeypatch.setattr(kb_delete, "_delete_graph", down)
    out = await asyncio.to_thread(kb_delete.delete_slice, job, requeue=lambda _j: None)
    assert out["status"] == "waiting"
    cur.execute("SELECT count(*) FROM chunks WHERE collection_id = %s", (kb,))
    assert cur.fetchone()[0] == 1

    monkeypatch.setattr(kb_delete, "_delete_graph", lambda cur, kb_id: 3)
    done = await asyncio.to_thread(kb_delete.delete_slice, job, requeue=lambda _j: None)
    assert done["status"] == "completed"
    cur.execute("SELECT entities_deleted FROM kb_delete_jobs WHERE id = %s", (job,))
    assert cur.fetchone()[0] == 3


def test_graph_delete_uses_neo4j_when_reachable(kb_conn, monkeypatch):
    from engine.knowledge import graph_writer, neo4j_client

    calls = []

    async def graph(kb_id):
        calls.append(kb_id)
        return {"entities_deleted": 7}

    monkeypatch.setattr(graph_writer, "delete_kb_graph", graph)
    monkeypatch.setattr(
        neo4j_client, "is_neo4j_available", AsyncMock(return_value=True)
    )
    assert kb_delete._delete_graph(kb_conn.cursor(), "kb-1") == 7
    assert calls == ["kb-1"]


@pytest.mark.asyncio
async def test_delete_file_handles_s3_and_file_uris(
    minio_endpoint, tmp_path, monkeypatch
):
    from engine.storage import service

    s3 = boto3.client(
        "s3",
        endpoint_url=minio_endpoint["url"],
        aws_access_key_id=minio_endpoint["access"],
        aws_secret_access_key=minio_endpoint["secret"],
        region_name="us-east-1",
    )
    bucket = f"del-{uuid.uuid4().hex[:8]}"
    s3.create_bucket(Bucket=bucket)
    s3.put_object(Bucket=bucket, Key="kb/doc.txt", Body=b"x")
    monkeypatch.setattr(service, "STORAGE_S3_ENDPOINT", minio_endpoint["url"])
    monkeypatch.setattr(service, "STORAGE_S3_ACCESS_KEY", minio_endpoint["access"])
    monkeypatch.setattr(service, "STORAGE_S3_SECRET_KEY", minio_endpoint["secret"])
    monkeypatch.setattr(service, "_storage", None, raising=False)
    await knowledge._delete_file(f"s3://{bucket}/kb/doc.txt")
    assert "Contents" not in s3.list_objects_v2(Bucket=bucket)

    f = tmp_path / "a.txt"
    f.write_text("x")
    await knowledge._delete_file(f"file://{f}")
    assert not f.exists()
    g = tmp_path / "b.txt"
    g.write_text("x")
    await knowledge._delete_file(str(g))
    assert not g.exists()
    await knowledge._delete_file("agent://knowledge_store/abc")


def test_process_document_skips_a_deleted_collection(kb_conn, monkeypatch):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    assert dp._kb_generation(kb) == 0
    cur.execute(
        "UPDATE knowledge_collections SET deleted_at = now() WHERE id = %s", (kb,)
    )
    assert dp._kb_generation(kb) is None
