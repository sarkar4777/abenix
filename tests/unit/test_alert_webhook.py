"""Alertmanager webhook: token gate, firing + resolved fan-out, fingerprint dedupe."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.core import notifications as notif
from app.routers import admin_alerts

TOKEN = "s3cret-token"


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Answers the dedupe query from `recent`, a set of (fingerprint, status)."""

    def __init__(self):
        self.recent: set[tuple[str, str]] = set()
        self.commits = 0

    async def execute(self, stmt, params=None):
        text = str(
            stmt.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for fp, status in self.recent:
            if f"'{fp}'" in text and f"'{status}'" in text:
                return FakeResult([("row",)])
        return FakeResult([])

    async def commit(self):
        self.commits += 1


def _request(headers: dict | None = None):
    return SimpleNamespace(headers=headers or {})


def _alert(status="firing", fingerprint="abc123", name="HighErrorRate"):
    return {
        "status": status,
        "labels": {"alertname": name, "severity": "critical"},
        "annotations": {"summary": "Abenix API error rate > 5%"},
        "startsAt": "2026-10-01T10:00:00Z",
        "endsAt": (
            "0001-01-01T00:00:00Z" if status == "firing" else "2026-10-01T10:30:00Z"
        ),
        "fingerprint": fingerprint,
    }


def _payload(*alerts):
    return {
        "version": "4",
        "groupKey": '{}:{alertname="HighErrorRate"}',
        "status": alerts[0]["status"] if alerts else "firing",
        "receiver": "abenix-api",
        "alerts": list(alerts),
    }


@pytest.mark.asyncio
async def test_token_required():
    db = FakeDB()
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": TOKEN}):
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(_payload(_alert()), _request(), db=db)
        assert exc.value.status_code == 401
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(
                _payload(_alert()), _request({"authorization": "Bearer nope"}), db=db
            )
        assert exc.value.status_code == 401
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": ""}):
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(
                _payload(_alert()), _request({"x-alert-token": "anything"}), db=db
            )
        assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_firing_alert_notifies():
    db = FakeDB()
    fanout = AsyncMock(return_value=2)
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": TOKEN}), patch.object(
        notif, "notify_platform_alert", fanout
    ):
        resp = await admin_alerts.alert_webhook(
            _payload(_alert()), _request({"authorization": f"Bearer {TOKEN}"}), db=db
        )
    body = json.loads(resp.body)["data"]
    assert body == {"received": 1, "notified": 2, "skipped": 0}
    fanout.assert_awaited_once()
    kwargs = fanout.await_args.kwargs
    assert kwargs["name"] == "HighErrorRate"
    assert kwargs["severity"] == "critical"
    assert kwargs["status"] == "firing"
    assert kwargs["fingerprint"] == "abc123"
    assert kwargs["source"] == "alertmanager"
    assert kwargs["since"] == "2026-10-01T10:00:00Z"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_resolved_alert_notifies():
    db = FakeDB()
    fanout = AsyncMock(return_value=1)
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": TOKEN}), patch.object(
        notif, "notify_platform_alert", fanout
    ):
        resp = await admin_alerts.alert_webhook(
            _payload(_alert(status="resolved")),
            _request({"x-alert-token": TOKEN}),
            db=db,
        )
    assert json.loads(resp.body)["data"]["notified"] == 1
    kwargs = fanout.await_args.kwargs
    assert kwargs["status"] == "resolved"
    assert kwargs["since"] == "2026-10-01T10:30:00Z"


@pytest.mark.asyncio
async def test_dedupe_by_fingerprint_within_window():
    db = FakeDB()
    fanout = AsyncMock(return_value=1)
    headers = {"authorization": f"Bearer {TOKEN}"}
    with patch.dict(
        os.environ,
        {"ALERT_WEBHOOK_TOKEN": TOKEN, "PLATFORM_ALERT_DEDUPE_MINUTES": "30"},
    ), patch.object(notif, "notify_platform_alert", fanout):
        await admin_alerts.alert_webhook(_payload(_alert()), _request(headers), db=db)
        db.recent.add(("abc123", "firing"))
        resp = await admin_alerts.alert_webhook(
            _payload(_alert()), _request(headers), db=db
        )
        assert json.loads(resp.body)["data"] == {
            "received": 1,
            "notified": 0,
            "skipped": 1,
        }
        # A resolve for the same fingerprint is a different event, it goes out.
        resp = await admin_alerts.alert_webhook(
            _payload(_alert(status="resolved")), _request(headers), db=db
        )
        assert json.loads(resp.body)["data"]["notified"] == 1
        # A different fingerprint for the same rule is not deduped.
        resp = await admin_alerts.alert_webhook(
            _payload(_alert(fingerprint="zzz999")), _request(headers), db=db
        )
        assert json.loads(resp.body)["data"]["notified"] == 1
    assert fanout.await_count == 3


def test_alertmanager_shape_marks_silenced():
    shaped = admin_alerts._shape_am_alert(
        {
            "labels": {"alertname": "RedisDown", "severity": "critical"},
            "annotations": {"summary": "Redis is unreachable"},
            "startsAt": "2026-10-01T10:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "f1",
            "status": {"state": "suppressed", "silencedBy": ["s1"], "inhibitedBy": []},
        }
    )
    assert shaped["state"] == "silenced"
    assert shaped["silenced"] is True
    assert shaped["ends_at"] is None
    assert shaped["fingerprint"] == "f1"
