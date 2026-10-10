"""Expired shares and grants stop granting access.

Every access query that reads resource_shares or user_collection_grants must
carry the expiry clause. The fake session records each statement so the tests
can check the compiled SQL without a database.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.core.permissions import (
    accessible_resource_ids,
    parse_share_expiry,
    share_expiry_fields,
)
from models.collection_grant import UserCollectionGrant
from models.resource_share import ResourceShare, SharePermission
from models.user import UserRole

T = uuid.uuid4()


def _user(role=UserRole.USER):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=T, role=role, email="u@x.io")


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect())).lower()


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def all(self):
        return self.value or []

    def first(self):
        return None

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.value or [])


class _DB:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.answers.pop(0) if self.answers else None)

    async def get(self, model, key):
        return self.answers.pop(0) if self.answers else None


def _has_expiry(stmt, table: str) -> bool:
    sql = _sql(stmt)
    return f"{table}.expires_at is null" in sql and f"{table}.expires_at > now()" in sql


# ── helpers ───────────────────────────────────────────────────────────


def test_live_clause_checks_null_or_future():
    assert "resource_shares.expires_at is null" in _sql(ResourceShare.live())
    assert "resource_shares.expires_at > now()" in _sql(ResourceShare.live())
    assert "user_collection_grants.expires_at > now()" in _sql(
        UserCollectionGrant.live()
    )


def test_is_expired():
    now = datetime.now(timezone.utc)
    assert not ResourceShare(expires_at=None).is_expired()
    assert not ResourceShare(expires_at=now + timedelta(hours=1)).is_expired()
    assert ResourceShare(expires_at=now - timedelta(seconds=1)).is_expired()
    naive_past = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert ResourceShare(expires_at=naive_past).is_expired()


def test_parse_share_expiry():
    assert parse_share_expiry(None) == (None, None)
    assert parse_share_expiry("") == (None, None)
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    exp, err = parse_share_expiry(future)
    assert err is None and exp is not None and exp.tzinfo is not None
    exp, err = parse_share_expiry("2020-01-01T00:00:00Z")
    assert exp is None and "future" in err
    exp, err = parse_share_expiry("next tuesday")
    assert exp is None and "ISO" in err


def test_share_expiry_fields_flags_expired():
    now = datetime.now(timezone.utc)
    assert share_expiry_fields(None) == {"expires_at": None, "expired": False}
    assert share_expiry_fields(now - timedelta(minutes=1))["expired"] is True
    assert share_expiry_fields(now + timedelta(minutes=1))["expired"] is False


# ── access paths ──────────────────────────────────────────────────────


def test_accessible_resource_ids_skips_expired():
    db = _DB([])
    asyncio.run(
        accessible_resource_ids(
            db, _user(), kind="agent", minimum_permission=SharePermission.VIEW
        )
    )
    assert _has_expiry(db.statements[0], "resource_shares")


def test_atlas_share_lookup_skips_expired():
    from app.routers.atlas import _share_for

    db = _DB(None)
    asyncio.run(_share_for(db, _user(), uuid.uuid4()))
    assert _has_expiry(db.statements[0], "resource_shares")


def test_kb_read_honours_live_grants_and_shares_only():
    from app.services import kb_access

    kb = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=T,
        created_by=uuid.uuid4(),
        default_visibility="private",
        project_id=None,
    )
    db = _DB(None, None)
    ok = asyncio.run(kb_access.user_can_access_collection(db, user=_user(), kb=kb))
    assert ok is False
    assert _has_expiry(db.statements[0], "user_collection_grants")
    assert _has_expiry(db.statements[1], "resource_shares")


def test_kb_read_granted_by_a_live_share():
    from app.services import kb_access

    kb = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=T,
        created_by=uuid.uuid4(),
        default_visibility="private",
        project_id=None,
    )
    db = _DB(None, SharePermission.VIEW)
    assert asyncio.run(kb_access.user_can_access_collection(db, user=_user(), kb=kb))


def test_kb_edit_needs_live_edit_share():
    from app.services import kb_access

    kb = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, created_by=uuid.uuid4())
    db = _DB(None, SharePermission.VIEW)
    assert not asyncio.run(kb_access.user_can_edit_collection(db, user=_user(), kb=kb))
    assert _has_expiry(db.statements[0], "user_collection_grants")
    assert _has_expiry(db.statements[1], "resource_shares")
    db = _DB(None, SharePermission.EDIT)
    assert asyncio.run(kb_access.user_can_edit_collection(db, user=_user(), kb=kb))


def test_collection_access_skips_expired_grants():
    from app.services import collection_access

    kb = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, created_by=uuid.uuid4())
    db = _DB(kb)
    asyncio.run(
        collection_access.assert_collection_access(
            db, user_id=uuid.uuid4(), tenant_id=T, collection_id=kb.id
        )
    )
    assert _has_expiry(db.statements[0], "user_collection_grants")


def test_document_acl_ignores_expired_collection_grants():
    from engine.knowledge.document_acl import _HIDDEN_SQL

    assert "ucg.expires_at IS NULL OR ucg.expires_at > now()" in _HIDDEN_SQL
    assert "g.expires_at IS NULL OR g.expires_at > now()" in _HIDDEN_SQL


def test_expired_document_grant_keeps_document_restricted():
    from engine.knowledge.document_acl import _HIDDEN_SQL

    restricted, _, _ = _HIDDEN_SQL.partition("AND (CAST(:uid")
    # any grant restricts the document, live or not
    assert "expires_at" not in restricted


def test_collection_grant_refuses_past_expiry(monkeypatch):
    from app.routers import collection_grants as cg

    kb = SimpleNamespace(id=uuid.uuid4(), tenant_id=T, created_by=None)

    async def admin_on(*a, **k):
        return kb

    monkeypatch.setattr(cg, "_require_admin_on", admin_on)
    body = cg.GrantUserRequest(
        user_id=uuid.uuid4(),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    resp = asyncio.run(cg.grant_user(kb.id, body, _user(UserRole.ADMIN), _DB()))
    assert resp.status_code == 400


def test_share_routes_read_expiry():
    import inspect

    from app.routers import agent_sharing, me

    assert "parse_share_expiry" in inspect.getsource(me.create_share)
    assert "parse_share_expiry" in inspect.getsource(agent_sharing.share_agent)
    assert "ResourceShare.live()" in inspect.getsource(agent_sharing.shared_with_me)
    assert "ResourceShare.live()" in inspect.getsource(me.list_shares_received)
