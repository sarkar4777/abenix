"""Settings: profile validation, avatar upload, and notification preferences honoured centrally."""

from __future__ import annotations

import io
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.datastructures import UploadFile

from app.core import notifications as notif
from app.core.object_storage import LocalObjectStorage
from app.routers import settings as settings_router
from app.schemas.settings import NotificationSettingsRequest, UpdateProfileRequest
from models.user import UserRole

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    def __init__(self, *, user=None, tenant=None):
        self.user = user
        self.tenant = tenant
        self.added: list = []

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or []
        d = descs[0] if descs else {}
        if d.get("name") == "notification_settings":
            return FakeResult([self.user.notification_settings] if self.user else [])
        name = getattr(d.get("entity"), "__name__", "")
        if name == "User":
            return FakeResult([self.user] if self.user else [])
        if name == "Tenant":
            return FakeResult([self.tenant] if self.tenant else [])
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None


def _user(prefs=None, avatar=None):
    tid = uuid.uuid4()
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tid,
        email="u@acme.test",
        full_name="Ada",
        avatar_url=avatar,
        role=UserRole.USER,
        created_at=None,
        notification_settings=prefs,
    )


def _request():
    return SimpleNamespace(client=None, headers={})


def _body(resp):
    return json.loads(resp.body)


async def _put_profile(user, **fields):
    return await settings_router.update_profile(
        body=UpdateProfileRequest(**fields), request=_request(), user=user, db=FakeDB(user=user)
    )


@pytest.mark.asyncio
async def test_avatar_rejects_non_urls_and_markup():
    u = _user(avatar="https://img.example/a.png")
    for bad in ("not a url <script>", "javascript:alert(1)", "ftp://x/y.png", "https://x/a b.png"):
        resp = await _put_profile(u, avatar_url=bad)
        assert resp.status_code == 400
        assert _body(resp)["error"]["details"] == {"field": "avatar_url"}
    assert u.avatar_url == "https://img.example/a.png"


@pytest.mark.asyncio
async def test_avatar_explicit_null_or_blank_clears_it():
    u = _user(avatar="not a url <script>")
    resp = await _put_profile(u, avatar_url=None)
    assert resp.status_code == 200
    assert u.avatar_url is None
    u.avatar_url = "https://img.example/a.png"
    await _put_profile(u, avatar_url="  ")
    assert u.avatar_url is None


@pytest.mark.asyncio
async def test_leaving_avatar_out_keeps_it():
    u = _user(avatar="https://img.example/a.png")
    resp = await _put_profile(u, full_name="  Grace  ")
    assert resp.status_code == 200
    assert u.full_name == "Grace"
    assert u.avatar_url == "https://img.example/a.png"


@pytest.mark.asyncio
async def test_blank_name_is_refused():
    u = _user()
    resp = await _put_profile(u, full_name="   ")
    assert resp.status_code == 400
    assert u.full_name == "Ada"


def test_uploaded_avatar_path_only_for_its_owner():
    u = _user()
    mine = f"/api/settings/avatars/{u.id}/{'a' * 32}.png"
    assert settings_router.check_avatar_url(mine, str(u.id)) == (mine, None)
    other = f"/api/settings/avatars/{uuid.uuid4()}/{'a' * 32}.png"
    assert settings_router.check_avatar_url(other, str(u.id))[1]


@pytest.mark.asyncio
async def test_avatar_upload_stores_and_serves_the_picture(tmp_path):
    u = _user()
    store = LocalObjectStorage(tmp_path)
    with patch("app.core.object_storage.get_object_storage", return_value=store):
        resp = await settings_router.upload_avatar(
            request=_request(),
            file=UploadFile(io.BytesIO(PNG), filename="me.png"),
            user=u,
            db=FakeDB(user=u),
        )
        assert resp.status_code == 200
        url = u.avatar_url
        assert url.startswith(f"/api/settings/avatars/{u.id}/") and url.endswith(".png")
        owner, name = url.rsplit("/", 2)[-2:]
        served = await settings_router.get_avatar(owner, name)
        assert served.status_code == 200
        assert served.media_type == "image/png"
        assert b"".join([c async for c in served.body_iterator]) == PNG
        missing = await settings_router.get_avatar(owner, "b" * 32 + ".png")
        assert missing.status_code == 404

        # replacing the picture drops the old file
        await settings_router.upload_avatar(
            request=_request(),
            file=UploadFile(io.BytesIO(PNG), filename="me2.png"),
            user=u,
            db=FakeDB(user=u),
        )
        assert not (tmp_path / "avatars" / owner / name).exists()


@pytest.mark.asyncio
async def test_avatar_upload_refuses_non_images():
    u = _user()
    resp = await settings_router.upload_avatar(
        request=_request(),
        file=UploadFile(io.BytesIO(b"<svg onload=alert(1)>"), filename="x.svg"),
        user=u,
        db=FakeDB(user=u),
    )
    assert resp.status_code == 415
    assert u.avatar_url is None


@pytest.mark.asyncio
async def test_notification_prefs_merge_and_drop_dead_toggles():
    u = _user(prefs={"weekly_report": True, "marketing": True, "email_for_info": True})
    resp = await settings_router.update_notifications(
        body=NotificationSettingsRequest(execution_complete=False, channels={"slack": False}),
        user=u,
        db=FakeDB(user=u),
    )
    data = _body(resp)["data"]
    assert data["execution_complete"] is False
    assert data["execution_failed"] is True
    assert data["channels"] == {"slack": False, "email": True}
    assert data["delivery"]["slack_available"] is False
    assert "weekly_report" not in u.notification_settings
    assert "marketing" not in u.notification_settings
    assert u.notification_settings["email_for_info"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ntype,pref",
    [
        ("execution_complete", "execution_complete"),
        ("execution_failed", "execution_failed"),
        ("agent_shared", "team_updates"),
        ("agent_comment", "team_updates"),
    ],
)
async def test_opted_out_types_are_not_created(ntype, pref):
    u = _user(prefs={pref: False})
    db = FakeDB(user=u)
    ws = AsyncMock()
    with patch.object(notif.ws_manager, "send_to_user", ws):
        n = await notif.create_notification(
            db, tenant_id=u.tenant_id, user_id=u.id, type=ntype, title="t", message="m"
        )
    assert n is None
    assert db.added == []
    ws.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_needed_types_ignore_opt_outs():
    u = _user(prefs={k: False for k in settings_router.NOTIFICATION_DEFAULTS})
    db = FakeDB(user=u)
    with patch.object(notif.ws_manager, "send_to_user", AsyncMock()):
        for ntype in ("approval_pending", "system_alert"):
            n = await notif.create_notification(
                db, tenant_id=u.tenant_id, user_id=u.id, type=ntype, title="t", message="m"
            )
            assert n is not None
    assert len(db.added) == 2


@pytest.mark.asyncio
async def test_direct_producers_check_the_same_preferences():
    from models.notification import NotificationType

    u = _user(prefs={"execution_failed": False, "billing_alerts": False})
    db = FakeDB(user=u)
    assert not await notif.user_wants_notification(db, u.id, NotificationType.EXECUTION_FAILED)
    assert not await notif.user_wants_notification(db, u.id, "usage_warning")
    assert await notif.user_wants_notification(db, u.id, NotificationType.SYSTEM_ALERT)
    u.notification_settings = None
    assert await notif.user_wants_notification(db, u.id, "execution_failed")
