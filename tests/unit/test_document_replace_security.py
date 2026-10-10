"""The document replace route stays inside the caller's tenant and collection."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.routers import knowledge_v2 as kv2

T = uuid.uuid4()
KB = uuid.uuid4()


def test_owned_storage_url_accepts_own_prefix():
    assert kv2._owned_storage_url(f"s3://bucket/{T}/kb/{KB}/a.pdf", T, KB)
    assert kv2._owned_storage_url(f"az://c/{T}/kb/{KB}/a.pdf", T, KB)
    assert kv2._owned_storage_url(f"./data/uploads/{T}/{KB}/a.pdf", T, KB)
    assert kv2._owned_storage_url(f"C:\\data\\uploads\\{T}\\{KB}\\a.pdf", T, KB)


def test_owned_storage_url_refuses_other_tenant_or_collection():
    other = uuid.uuid4()
    assert not kv2._owned_storage_url(f"s3://bucket/{other}/kb/{KB}/a.pdf", T, KB)
    assert not kv2._owned_storage_url(f"s3://bucket/{T}/kb/{other}/a.pdf", T, KB)
    assert not kv2._owned_storage_url("/etc/passwd", T, KB)
    assert not kv2._owned_storage_url(f"s3://b/{T}/kb/{KB}/../../{other}/x", T, KB)


class _Res:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v


class _DB:
    def __init__(self, kb):
        self.kb = kb

    async def execute(self, stmt):
        return _Res(self.kb)


def _body(url):
    return kv2.ReplaceDocumentRequest(
        new_filename="b.pdf", new_storage_url=url, new_file_type="pdf", new_file_size=1
    )


@pytest.mark.asyncio
async def test_other_tenants_collection_is_not_found():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=T)
    resp = await kv2.replace_document(
        KB, uuid.uuid4(), _body(f"s3://b/{T}/kb/{KB}/b.pdf"), None, user, _DB(None)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_foreign_storage_path_is_refused(monkeypatch):
    import app.services.kb_access as acc

    async def yes(*a, **k):
        return True

    monkeypatch.setattr(acc, "user_can_access_collection", yes)
    monkeypatch.setattr(acc, "user_can_edit_collection", yes)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=T)
    kb = SimpleNamespace(id=KB, tenant_id=T, chunk_size=500, chunk_overlap=50)
    resp = await kv2.replace_document(
        KB,
        uuid.uuid4(),
        _body(f"s3://b/{uuid.uuid4()}/kb/{KB}/b.pdf"),
        None,
        user,
        _DB(kb),
    )
    assert resp.status_code == 400
    assert "uploaded to this collection" in json.loads(resp.body)["error"]["message"]


@pytest.mark.asyncio
async def test_read_only_member_cannot_replace(monkeypatch):
    import app.services.kb_access as acc

    async def yes(*a, **k):
        return True

    async def no(*a, **k):
        return False

    monkeypatch.setattr(acc, "user_can_access_collection", yes)
    monkeypatch.setattr(acc, "user_can_edit_collection", no)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=T)
    kb = SimpleNamespace(id=KB, tenant_id=T, chunk_size=500, chunk_overlap=50)
    resp = await kv2.replace_document(
        KB, uuid.uuid4(), _body(f"s3://b/{T}/kb/{KB}/b.pdf"), None, user, _DB(kb)
    )
    assert resp.status_code == 403
