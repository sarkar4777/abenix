"""Tenant knowledge limits, enforced with clear errors at the API and in the worker."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from kb_pg import make_doc, make_kb, make_tenant

import knowledge_quota as kq
from models.user import UserRole
from worker.tasks import document_processor as dp
from worker.tasks import kb_quota


@pytest.mark.parametrize(
    "limits,adding,word",
    [
        ({"max_documents": 5}, {"add_documents": 1}, "limit is 5"),
        ({"max_chunks": 10}, {"add_chunks": 11}, "11 chunks"),
        ({"max_storage_bytes": 1024**3}, {"add_bytes": 2 * 1024**3}, "1.0 GB"),
        ({"monthly_embedding_usd": 1}, {"add_embedding_usd": 2.0}, "resets on the 1st"),
        ({"monthly_cognify_usd": 0}, {"add_cognify_usd": 0.1}, "knowledge graphs"),
    ],
)
def test_each_limit_names_itself_and_where_to_raise_it(limits, adding, word):
    usage = kq.Usage(documents=5, chunks=0, storage_bytes=0)
    with pytest.raises(kq.KnowledgeQuotaExceeded) as e:
        kq.check(limits, usage, **adding)
    assert word in e.value.message and "Settings, Token Quotas" in e.value.message


def test_no_limit_or_nothing_added_never_refuses():
    kq.check(None, kq.Usage(documents=9), add_documents=1)
    kq.check({"max_documents": None}, kq.Usage(documents=9), add_documents=1)
    kq.check({"max_documents": 1}, kq.Usage(documents=9), add_chunks=0)


def test_embedding_cost_uses_the_model_rate(monkeypatch):
    import embedding_models as em

    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    tokens, usd = em.estimated_cost("text-embedding-3-large", ["x" * 4_000_000])
    assert tokens == 1_000_000 and abs(usd - 0.13) < 1e-9
    assert em.estimated_cost("local-hashing-v1", ["x" * 400])[1] == 0.0


@pytest_asyncio.fixture
async def db(kb_db_url):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(
        kb_db_url.replace("postgresql://", "postgresql+asyncpg://")
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


def _user(tenant, role=UserRole.ADMIN):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.UUID(tenant), role=role)


def _upload(name="a.txt", body=b"hello", content_type="text/plain"):
    import io

    from starlette.datastructures import Headers, UploadFile

    return UploadFile(
        file=io.BytesIO(body),
        filename=name,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_upload_past_the_document_limit_is_refused_with_429(kb_conn, db):
    from app.routers import knowledge

    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["x"])
    cur.execute(
        "INSERT INTO tenant_knowledge_quotas (tenant_id, max_documents) VALUES (%s, 1)",
        (tenant,),
    )
    resp = await knowledge.upload_document(
        uuid.UUID(kb), file=_upload(), user=_user(tenant), db=db
    )
    assert resp.status_code == 429
    body = json.loads(resp.body)
    assert (
        body["error"]["error_code"] == kq.ERROR_CODE
        or kq.ERROR_CODE in resp.body.decode()
    )
    assert "limit is 1" in resp.body.decode()


@pytest.mark.asyncio
async def test_settings_endpoints_show_usage_and_only_admins_write(
    kb_conn, kb_db_url, db
):
    from app.routers import admin_knowledge_quota as api
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from models.user import User

    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["a", "b"])
    user = _user(tenant)
    engine = create_engine(kb_db_url.replace("postgresql://", "postgresql+psycopg2://"))
    with Session(engine) as session:
        session.add(
            User(
                id=user.id,
                tenant_id=user.tenant_id,
                email=f"{user.id.hex}@x.example",
                full_name="A",
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        session.commit()
    engine.dispose()
    with pytest.raises(HTTPException) as denied:
        await api.set_knowledge_quota(
            api.QuotaBody(max_documents=5), user=_user(tenant, UserRole.USER), db=db
        )
    assert denied.value.status_code == 403
    resp = await api.set_knowledge_quota(
        api.QuotaBody(max_documents=5, monthly_embedding_usd=2.5), user=user, db=db
    )
    data = json.loads(resp.body)["data"]
    assert data["limits"]["max_documents"] == 5
    assert data["limits"]["monthly_embedding_usd"] == 2.5
    assert data["limits"]["max_chunks"] is None
    assert data["usage"]["documents"] == 1 and data["usage"]["chunks"] == 2


def test_worker_records_spend_and_refuses_before_paying(kb_conn):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant, model="text-embedding-3-small")
    cur.execute(
        "INSERT INTO tenant_knowledge_quotas (tenant_id, max_chunks, monthly_embedding_usd) "
        "VALUES (%s, 100, 0.005)",
        (tenant,),
    )
    text = ["x" * 400_000]
    assert dp._quota_refusal(kb, "text-embedding-3-small", text) is None
    dp._record_embedding_spend(kb, "text-embedding-3-small", text)
    dp._record_embedding_spend(kb, "text-embedding-3-small", text)
    cur.execute(
        "SELECT embedding_tokens, embedding_usd FROM knowledge_spend WHERE tenant_id = %s",
        (tenant,),
    )
    tokens, usd = cur.fetchone()
    assert tokens == 200_000 and float(usd) == pytest.approx(0.004)
    assert "Embedding has cost" in dp._quota_refusal(kb, "text-embedding-3-small", text)
    assert "needs 101 chunks" in dp._quota_refusal(kb, "local-hashing-v1", ["y"] * 101)


def test_deleted_collections_stop_counting(kb_conn):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    make_doc(cur, kb, ["a"])
    cur.execute(
        "INSERT INTO tenant_knowledge_quotas (tenant_id, max_documents) VALUES (%s, 1)",
        (tenant,),
    )
    assert kb_quota.limits_and_usage(cur, tenant)[1].documents == 1
    cur.execute(
        "UPDATE knowledge_collections SET deleted_at = now() WHERE id = %s", (kb,)
    )
    assert kb_quota.limits_and_usage(cur, tenant)[1].documents == 0


def test_cognify_spend_is_recorded(kb_conn):
    cur = kb_conn.cursor()
    tenant = make_tenant(cur)
    kb = make_kb(cur, tenant)
    kb_quota.record_for_kb(kb, cognify_usd=1.25)
    cur.execute(
        "SELECT cognify_usd FROM knowledge_spend WHERE tenant_id = %s", (tenant,)
    )
    assert float(cur.fetchone()[0]) == 1.25
