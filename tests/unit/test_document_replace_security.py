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

    async def flush(self):
        pass

    async def execute(self, stmt, params=None):
        if params is not None:
            return _Res(None)
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


def _doc(**kw):
    base = dict(
        id=uuid.uuid4(),
        kb_id=KB,
        is_current=True,
        parent_document_id=None,
        version_number=1,
        superseded_by=None,
        chunk_count=0,
        filename="new.pdf",
        file_type="pdf",
        storage_url=f"{T}/kb/{KB}/new.pdf",
    )
    return SimpleNamespace(**{**base, **kw})


class _Session:
    def __init__(self, kb, docs):
        self.kb = kb
        self.docs = {d.id: d for d in docs}

    async def flush(self):
        pass

    async def execute(self, stmt, params=None):
        if params is not None:
            self.grants_copied = params
            return None
        wanted = (
            next(
                (
                    c.right.value
                    for c in stmt.whereclause.clauses
                    if c.left.key == "id" and c.left.table.name == "documents"
                ),
                None,
            )
            if "documents" in str(stmt)
            else None
        )
        return _Res(self.docs.get(wanted) if wanted else self.kb)

    def add(self, obj):
        self.added = obj

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass


@pytest.fixture
def allowed(monkeypatch):
    import app.services.kb_access as acc

    async def yes(*a, **k):
        return True

    monkeypatch.setattr(acc, "user_can_access_collection", yes)
    monkeypatch.setattr(acc, "user_can_edit_collection", yes)
    monkeypatch.setattr(kv2, "log_action", lambda *a, **k: _noop())
    sent = []
    import app.routers.knowledge as knowledge

    monkeypatch.setattr(knowledge, "_dispatch_processing", lambda **kw: sent.append(kw))
    return sent


async def _noop():
    return None


def _kb():
    return SimpleNamespace(
        id=KB,
        tenant_id=T,
        chunk_size=500,
        chunk_overlap=50,
        vector_backend="pgvector",
        embedding_generation=0,
    )


USER = SimpleNamespace(id=uuid.uuid4(), tenant_id=T)


@pytest.mark.asyncio
async def test_replace_works_from_the_document_id_an_upload_returned(allowed):
    old, new = _doc(version_number=2), _doc()
    body = kv2.ReplaceDocumentRequest(new_document_id=new.id)
    resp = await kv2.replace_document(
        KB, old.id, body, None, USER, _Session(_kb(), [old, new])
    )
    assert resp.status_code == 201
    data = json.loads(resp.body)["data"]
    assert data == {
        "id": str(new.id),
        "version_number": 3,
        "parent_document_id": str(old.id),
        "supersedes": str(old.id),
    }
    assert old.is_current is False and old.superseded_by == new.id
    assert new.parent_document_id == old.id and new.is_current is True
    # the upload already queued it
    assert allowed == []


@pytest.mark.asyncio
async def test_replace_by_id_refuses_itself_and_other_collections(allowed):
    old = _doc()
    session = _Session(_kb(), [old])
    same = kv2.ReplaceDocumentRequest(new_document_id=old.id)
    resp = await kv2.replace_document(KB, old.id, same, None, USER, session)
    assert resp.status_code == 409
    other = kv2.ReplaceDocumentRequest(new_document_id=uuid.uuid4())
    resp = await kv2.replace_document(KB, old.id, other, None, USER, session)
    assert resp.status_code == 404
    assert old.is_current is True


@pytest.mark.asyncio
async def test_replace_by_id_refuses_a_document_with_a_history(allowed):
    old, new = _doc(), _doc(parent_document_id=uuid.uuid4())
    body = kv2.ReplaceDocumentRequest(new_document_id=new.id)
    resp = await kv2.replace_document(
        KB, old.id, body, None, USER, _Session(_kb(), [old, new])
    )
    assert resp.status_code == 409
    assert old.is_current is True


@pytest.mark.asyncio
async def test_the_stored_file_form_still_works_and_queues_the_file(allowed):
    old = _doc()
    body = _body(f"s3://b/{T}/kb/{KB}/b.pdf")
    resp = await kv2.replace_document(
        KB, old.id, body, None, USER, _Session(_kb(), [old])
    )
    assert resp.status_code == 201
    assert allowed[0]["file_path"] == f"s3://b/{T}/kb/{KB}/b.pdf"


def test_a_body_needs_one_form_or_the_other():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        kv2.ReplaceDocumentRequest()
    with pytest.raises(ValidationError):
        kv2.ReplaceDocumentRequest(new_filename="a.pdf")
    with pytest.raises(ValidationError):
        kv2.ReplaceDocumentRequest(
            new_document_id=uuid.uuid4(),
            new_filename="a",
            new_storage_url="u",
            new_file_type="pdf",
            new_file_size=1,
        )


@pytest.mark.asyncio
async def test_a_new_version_keeps_the_grants_of_the_old_one():
    seen = {}

    class Capture:
        async def execute(self, stmt, params):
            seen["sql"], seen["params"] = str(stmt), params

    old, new = uuid.uuid4(), uuid.uuid4()
    await kv2._copy_grants(Capture(), old, new)
    assert "INSERT INTO document_grants" in seen["sql"]
    assert seen["params"] == {"old_id": old, "new_id": new}
