"""Tenant Slack webhook: encrypted at rest, masked on read, no operator fallback."""

from __future__ import annotations

import base64
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core import crypto
from app.core import notifications as notif
from app.routers import notifications as notif_router
from app.routers import settings as settings_router
from models.user import UserRole

KEK = base64.b64encode(b"k" * 32).decode()
HOOK = "https://hooks.slack.com/services/T000/B000/abcdef123456"


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)


class FakeDB:
    def __init__(self, *, tenant=None, user=None):
        self.tenant = tenant
        self.user = user
        self.added: list = []

    async def execute(self, stmt, params=None):
        descs = getattr(stmt, "column_descriptions", None) or []
        name = getattr(descs[0].get("entity"), "__name__", "") if descs else ""
        if name == "Tenant":
            return FakeResult([self.tenant] if self.tenant else [])
        if name == "User":
            return FakeResult([self.user] if self.user else [])
        return FakeResult([])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, obj):
        return None


def _tenant(url=None):
    return SimpleNamespace(
        id=uuid.uuid4(), name="Acme", slug="acme", slack_webhook_url=url
    )


def _user(tenant, role=UserRole.ADMIN):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        role=role,
        email="a@acme.test",
        notification_settings=None,
    )


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={})


def test_mask_shows_only_the_tail():
    masked = notif.mask_webhook(HOOK)
    assert masked.endswith("123456")
    assert "T000/B000" not in masked
    assert notif.mask_webhook("") == ""


def test_tenant_webhook_decrypts_with_kek():
    t = _tenant()
    with patch.dict(os.environ, {"ABENIX_DATA_KEY_KEK_BASE64": KEK}):
        t.slack_webhook_url = crypto.encrypt(t.id, HOOK)
        assert t.slack_webhook_url != HOOK
        assert notif.tenant_slack_webhook(t) == HOOK
    assert notif.tenant_slack_webhook(None) == ""


def test_tenant_webhook_plaintext_passthrough_without_kek():
    t = _tenant(HOOK)
    with patch.dict(os.environ, {"ABENIX_DATA_KEY_KEK_BASE64": ""}):
        assert notif.tenant_slack_webhook(t) == HOOK


@pytest.mark.asyncio
async def test_get_masks_for_admin_and_hides_for_members():
    t = _tenant(HOOK)
    admin = _user(t)
    resp = await settings_router.get_tenant_settings(user=admin, db=FakeDB(tenant=t))
    data = json.loads(resp.body)["data"]
    assert data["slack_webhook_url"] != HOOK
    assert data["slack_webhook_url"].endswith("123456")
    assert data["slack_webhook_is_set"] is True
    assert data["slack_webhook_url_source"] == "tenant"

    member = _user(t, role=UserRole.USER)
    resp = await settings_router.get_tenant_settings(user=member, db=FakeDB(tenant=t))
    data = json.loads(resp.body)["data"]
    assert data["slack_webhook_url"] == ""
    assert data["slack_webhook_is_set"] is True


@pytest.mark.asyncio
async def test_put_encrypts_and_ignores_masked_echo():
    t = _tenant()
    admin = _user(t)
    with patch.dict(os.environ, {"ABENIX_DATA_KEY_KEK_BASE64": KEK}):
        resp = await settings_router.update_tenant_settings(
            body={"slack_webhook_url": HOOK},
            request=_request(),
            user=admin,
            db=FakeDB(tenant=t),
        )
        assert resp.status_code == 200
        stored = t.slack_webhook_url
        assert stored != HOOK and stored.startswith("v1:")
        assert crypto.decrypt(t.id, stored) == HOOK

        masked = json.loads(resp.body)["data"]["slack_webhook_url"]
        await settings_router.update_tenant_settings(
            body={"slack_webhook_url": masked},
            request=_request(),
            user=admin,
            db=FakeDB(tenant=t),
        )
        assert t.slack_webhook_url == stored

        await settings_router.update_tenant_settings(
            body={"slack_webhook_url": ""},
            request=_request(),
            user=admin,
            db=FakeDB(tenant=t),
        )
        assert t.slack_webhook_url is None


@pytest.mark.asyncio
async def test_members_cannot_change_the_webhook():
    t = _tenant()
    resp = await settings_router.update_tenant_settings(
        body={"slack_webhook_url": HOOK},
        request=_request(),
        user=_user(t, role=UserRole.USER),
        db=FakeDB(tenant=t),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_tenant_notifications_never_fall_back_to_operator_channel():
    t = _tenant(None)
    u = _user(t)
    post = AsyncMock(return_value=True)
    with patch.dict(os.environ, {"ABENIX_SLACK_WEBHOOK_URL": "https://ops.example/hook"}), patch.object(
        notif, "_post_slack", post
    ), patch.object(notif.ws_manager, "send_to_user", AsyncMock()):
        await notif.create_notification(
            FakeDB(tenant=t, user=u),
            tenant_id=t.id,
            user_id=u.id,
            type="execution_complete",
            title="done",
            message="ok",
        )
    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_notifications_use_decrypted_tenant_hook():
    t = _tenant()
    u = _user(t)
    post = AsyncMock(return_value=True)
    with patch.dict(os.environ, {"ABENIX_DATA_KEY_KEK_BASE64": KEK}):
        t.slack_webhook_url = crypto.encrypt(t.id, HOOK)
        with patch.object(notif, "_post_slack", post), patch.object(
            notif.ws_manager, "send_to_user", AsyncMock()
        ):
            await notif.create_notification(
                FakeDB(tenant=t, user=u),
                tenant_id=t.id,
                user_id=u.id,
                type="execution_complete",
                title="done",
                message="ok",
            )
    post.assert_awaited_once()
    assert post.await_args.args[0] == HOOK


@pytest.mark.asyncio
async def test_test_channel_posts_with_the_real_signature():
    t = _tenant(HOOK)
    admin = _user(t)
    post = AsyncMock(return_value=True)
    with patch.object(notif, "_post_slack", post):
        resp = await notif_router.test_notification_channel(
            channel="slack", user=admin, db=FakeDB(tenant=t)
        )
    assert json.loads(resp.body)["data"] == {"channel": "slack", "delivered": True}
    assert post.await_args.args[0] == HOOK
    assert set(post.await_args.kwargs) == {"title", "message", "link"}


@pytest.mark.asyncio
async def test_test_channel_reports_missing_webhook():
    t = _tenant(None)
    resp = await notif_router.test_notification_channel(
        channel="slack", user=_user(t), db=FakeDB(tenant=t)
    )
    data = json.loads(resp.body)["data"]
    assert data["delivered"] is False
    assert data["reason"]
