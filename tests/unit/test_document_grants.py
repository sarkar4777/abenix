"""Document grants: only collection editors share, subjects must be real, and
a conflict resolution must pick one of the two sides and reach the graph."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.routers import document_grants as dg
from app.routers.document_grants import GrantRequest

KB, DOC = uuid.uuid4(), uuid.uuid4()


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.tenant_id = uuid.uuid4()
    return u


def _status(resp):
    return resp.status_code, json.loads(resp.body)


def test_team_and_role_subjects_are_not_accepted():
    for kind in ("team", "role"):
        with pytest.raises(ValidationError):
            GrantRequest(subject_type=kind, subject_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_readers_cannot_share_documents():
    with patch.object(
        dg, "_load", AsyncMock(return_value=(MagicMock(), MagicMock()))
    ), patch.object(
        dg, "user_can_access_collection", AsyncMock(return_value=True)
    ), patch.object(
        dg, "user_can_edit_collection", AsyncMock(return_value=False)
    ):
        resp = await dg.create_grant(
            KB,
            DOC,
            GrantRequest(subject_type="user", subject_id=uuid.uuid4()),
            MagicMock(),
            _user(),
            MagicMock(),
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_other_tenants_collection_is_not_found():
    with patch.object(dg, "_load", AsyncMock(return_value=(None, None))):
        resp = await dg.list_grants(KB, DOC, _user(), MagicMock())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subject_must_exist_and_expiry_be_future():
    common = (
        patch.object(dg, "_load", AsyncMock(return_value=(MagicMock(), MagicMock()))),
        patch.object(dg, "user_can_access_collection", AsyncMock(return_value=True)),
        patch.object(dg, "user_can_edit_collection", AsyncMock(return_value=True)),
    )
    with common[0], common[1], common[2], patch.object(
        dg, "_subject_in_tenant", AsyncMock(return_value=False)
    ):
        resp = await dg.create_grant(
            KB,
            DOC,
            GrantRequest(subject_type="agent", subject_id=uuid.uuid4()),
            MagicMock(),
            _user(),
            MagicMock(),
        )
    assert resp.status_code == 400
    past = datetime.now(timezone.utc) - timedelta(days=1)
    with common[0], common[1], common[2], patch.object(
        dg, "_subject_in_tenant", AsyncMock(return_value=True)
    ):
        resp = await dg.create_grant(
            KB,
            DOC,
            GrantRequest(subject_type="user", subject_id=uuid.uuid4(), expires_at=past),
            MagicMock(),
            _user(),
            MagicMock(),
        )
    code, body = _status(resp)
    assert code == 400 and "future" in body["error"]["message"]


def _conflict():
    c = MagicMock()
    c.status = "open"
    c.property_name = "entity_type"
    c.source_a_value = "organization"
    c.source_b_value = "product"
    c.knowledge_base_id = KB
    c.entity_canonical_name = "Acme"
    return c


def _admin():
    from models.user import UserRole

    u = _user()
    u.role = UserRole.ADMIN
    return u


@pytest.mark.asyncio
async def test_resolution_must_pick_a_side():
    from app.routers.knowledge_v2 import ResolveConflictRequest, resolve_conflict

    found = MagicMock()
    found.scalar_one_or_none.return_value = _conflict()
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    resp = await resolve_conflict(
        uuid.uuid4(),
        ResolveConflictRequest(resolved_value="person"),
        MagicMock(),
        _admin(),
        db,
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_resolution_is_written_to_the_graph():
    from app.routers.knowledge_v2 import ResolveConflictRequest, resolve_conflict

    c = _conflict()
    found = MagicMock()
    found.scalar_one_or_none.return_value = c
    db = MagicMock()
    db.execute = AsyncMock(return_value=found)
    db.commit = AsyncMock()
    apply = AsyncMock(return_value=True)
    with patch("app.routers.knowledge_v2._apply_entity_type", apply), patch(
        "app.routers.knowledge_v2.log_action", AsyncMock()
    ):
        resp = await resolve_conflict(
            uuid.uuid4(),
            ResolveConflictRequest(resolved_value="product"),
            MagicMock(),
            _admin(),
            db,
        )
    code, body = _status(resp)
    assert code == 200 and body["data"]["applied_to_graph"] is True
    assert c.status == "resolved" and c.resolved_value == "product"
    apply.assert_awaited_once_with(db, KB, "Acme", "product")
