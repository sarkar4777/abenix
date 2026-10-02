"""Team invites end to end: the link comes back, the token is single use, expiry holds."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.routers import auth, team
from app.schemas.settings import InviteMemberRequest
from models.team_invite import InviteStatus, TeamInvite
from models.user import User, UserRole

pytestmark = pytest.mark.asyncio

TENANT = uuid.uuid4()


class FakeSession:
    """Hands back queued results in order, records what was added."""

    def __init__(self, *results) -> None:
        self.results = list(results)
        self.statements: list = []
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        value = self.results.pop(0) if self.results else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()


def _request(origin: str | None = "https://app.example.com") -> Request:
    headers = [(b"origin", origin.encode())] if origin else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def _body(resp) -> dict:
    return json.loads(resp.body)


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role=UserRole.ADMIN)


def _invite(
    *, role="creator", status=InviteStatus.PENDING, expires_in=timedelta(days=7)
):
    return TeamInvite(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        invited_by=uuid.uuid4(),
        email="new.hire@example.com",
        role=role,
        status=status,
        token="tok-" + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc) + expires_in,
    )


def _accept(token: str, password: str = "s3cretpass", full_name: str = "New Hire"):
    return auth.AcceptInviteRequest(token=token, full_name=full_name, password=password)


@pytest.fixture(autouse=True)
def _no_web_base(monkeypatch):
    monkeypatch.delenv("WEB_BASE_URL", raising=False)


@pytest.fixture
def tokens():
    with patch.object(auth, "create_access_token", lambda *a: "access"), patch.object(
        auth, "create_refresh_token", lambda *a: "refresh"
    ), patch.object(auth, "log_action", AsyncMock()):
        yield


async def test_invite_returns_accept_url_from_origin():
    db = FakeSession(None, None)
    resp = await team.invite_member(
        InviteMemberRequest(email="New.Hire@example.com", role="creator"),
        _request(),
        _admin(),
        db,
    )
    assert resp.status_code == 201
    data = _body(resp)["data"]
    invite = db.added[0]
    assert invite.tenant_id == TENANT
    assert invite.email == "new.hire@example.com"
    assert data["invite_url"] == (
        f"https://app.example.com/auth/accept-invite?token={invite.token}"
    )


async def test_invite_url_prefers_web_base_url(monkeypatch):
    monkeypatch.setenv("WEB_BASE_URL", "https://abenix.example/")
    assert (
        team.invite_url(_request("https://other.example"), "abc")
        == "https://abenix.example/auth/accept-invite?token=abc"
    )


async def test_invite_rejects_email_owned_by_another_workspace():
    other = SimpleNamespace(tenant_id=uuid.uuid4())
    resp = await team.invite_member(
        InviteMemberRequest(email="x@example.com", role="user"),
        _request(),
        _admin(),
        FakeSession(other),
    )
    assert resp.status_code == 409


async def test_non_admin_cannot_invite():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, role=UserRole.USER)
    resp = await team.invite_member(
        InviteMemberRequest(email="x@example.com", role="user"),
        _request(),
        user,
        FakeSession(),
    )
    assert resp.status_code == 403


async def test_get_invite_info_without_auth():
    inv = _invite()
    tenant = SimpleNamespace(name="Acme Labs")
    resp = await auth.get_invite(inv.token, FakeSession(inv, tenant))
    assert _body(resp)["data"] == {
        "email": "new.hire@example.com",
        "tenant_name": "Acme Labs",
        "role": "creator",
        "status": "pending",
        "expired": False,
        "used": False,
    }


async def test_get_invite_reports_expiry():
    inv = _invite(expires_in=timedelta(hours=-1))
    resp = await auth.get_invite(inv.token, FakeSession(inv, None))
    assert _body(resp)["data"]["expired"] is True


async def test_get_unknown_invite_is_404():
    resp = await auth.get_invite("nope", FakeSession(None))
    assert resp.status_code == 404


async def test_accept_creates_user_in_inviting_tenant_with_role(tokens):
    inv = _invite(role="creator")
    db = FakeSession(inv, None)
    resp = await auth.accept_invite(_accept(inv.token), _request(), db)
    assert resp.status_code == 201
    body = _body(resp)["data"]
    assert body["access_token"] == "access"
    assert body["refresh_token"] == "refresh"
    assert body["token_type"] == "bearer"
    assert body["user"]["tenant_id"] == str(TENANT)
    assert body["user"]["role"] == "creator"
    created = [o for o in db.added if isinstance(o, User)]
    assert len(created) == 1
    assert created[0].tenant_id == TENANT
    assert created[0].role == UserRole.CREATOR
    assert created[0].email == "new.hire@example.com"
    assert inv.status == InviteStatus.ACCEPTED
    # looked up by token, the tenant comes from the invite row
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "team_invites.token" in sql


async def test_token_is_single_use(tokens):
    inv = _invite()
    first = await auth.accept_invite(
        _accept(inv.token), _request(), FakeSession(inv, None)
    )
    assert first.status_code == 201
    second = await auth.accept_invite(
        _accept(inv.token), _request(), FakeSession(inv, None)
    )
    assert second.status_code == 410
    assert "already been used" in _body(second)["error"]["message"]


async def test_expired_invite_rejected(tokens):
    inv = _invite(expires_in=timedelta(minutes=-5))
    db = FakeSession(inv, None)
    resp = await auth.accept_invite(_accept(inv.token), _request(), db)
    assert resp.status_code == 410
    assert "expired" in _body(resp)["error"]["message"]
    assert db.added == []


async def test_cancelled_invite_rejected(tokens):
    inv = _invite(status=InviteStatus.EXPIRED)
    resp = await auth.accept_invite(
        _accept(inv.token), _request(), FakeSession(inv, None)
    )
    assert resp.status_code == 410


async def test_short_password_rejected(tokens):
    inv = _invite()
    resp = await auth.accept_invite(
        _accept(inv.token, password="short"), _request(), FakeSession(inv, None)
    )
    assert resp.status_code == 400
    assert inv.status == InviteStatus.PENDING


async def test_existing_account_rejected(tokens):
    inv = _invite()
    resp = await auth.accept_invite(
        _accept(inv.token),
        _request(),
        FakeSession(inv, SimpleNamespace(id=uuid.uuid4())),
    )
    assert resp.status_code == 409
    assert inv.status == InviteStatus.PENDING
