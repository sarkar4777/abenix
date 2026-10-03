"""/api/sources: validation, tenant scoping, pause and resume, check now and settings."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.routers import sources as R
from app.services import source_watch as SW
from models.source_watch import WatchSource

TENANT = uuid.uuid4()


class Result:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar(self):
        return self.value

    def first(self):
        return self.value

    def all(self):
        return self.rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows, __iter__=lambda: iter(self.rows))


class FakeSession:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.added: list = []
        self.deleted: list = []
        self.commits = 0
        self.closed = False

    async def execute(self, stmt):
        return self.results.pop(0) if self.results else Result()

    async def get(self, model, key):
        return None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    async def delete(self, obj):
        self.deleted.append(obj)

    async def close(self):
        self.closed = True


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, email="a@b.test", role="admin"
    )


def _body(resp) -> dict:
    return json.loads(resp.body)


def _source(**kw):
    s = WatchSource(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Guidance",
        url="https://93.184.216.34/g",
        kind="html",
        cadence_minutes=60,
        active=True,
        headers={},
        tags=[],
        risk_tier="low",
        consecutive_failures=0,
        check_count=0,
    )
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.delenv("SOURCE_WATCH_ALLOW_PRIVATE_TARGETS", raising=False)
    monkeypatch.setattr(R, "log_action", AsyncMock())
    monkeypatch.setattr(
        SW, "tenant_settings", AsyncMock(return_value=SW.clean_settings({}))
    )


def _create(body: dict, *results):
    db = FakeSession(*results)
    resp = asyncio.run(R.create_source(R.SourceIn(**body), None, _user(), db))
    return resp, db


def test_create_refuses_private_targets():
    resp, db = _create({"name": "x", "url": "http://10.0.0.5/admin"})
    assert resp.status_code == 400 and "private" in _body(resp)["error"]["message"]
    assert not db.added


def test_create_refuses_secret_headers_and_bad_selectors():
    resp, _ = _create(
        {
            "name": "x",
            "url": "https://93.184.216.34/",
            "headers": {"Authorization": "Bearer x"},
        }
    )
    assert resp.status_code == 400 and "credential" in _body(resp)["error"]["message"]
    resp, _ = _create(
        {
            "name": "x",
            "url": "https://93.184.216.34/",
            "kind": "json",
            "selector": "data.items",
        }
    )
    assert resp.status_code == 400 and "JSON pointer" in _body(resp)["error"]["message"]
    resp, _ = _create(
        {
            "name": "x",
            "url": "https://93.184.216.34/",
            "credentials_key": "DATABASE_URL",
        }
    )
    assert resp.status_code == 400


def test_create_rejects_duplicate_names():
    resp, _ = _create(
        {"name": "Guidance", "url": "https://93.184.216.34/"},
        Result(value=(uuid.uuid4(),)),
    )
    assert resp.status_code == 409


def test_create_saves_and_schedules_the_first_check():
    resp, db = _create(
        {
            "name": " Carrier tariff ",
            "url": "https://93.184.216.34/g",
            "tags": ["tariff", "tariff", " freight "],
            "cadence_minutes": 120,
        }
    )
    assert resp.status_code == 201
    s = db.added[0]
    assert (
        s.name == "Carrier tariff"
        and s.tenant_id == TENANT
        and s.tags == ["tariff", "freight"]
    )
    assert s.next_check_at is not None and db.commits == 1
    data = _body(resp)["data"]
    assert data["health"] == "new" and data["host"] == "93.184.216.34"
    R.log_action.assert_awaited()


def test_cadence_has_a_floor():
    with pytest.raises(Exception):
        R.SourceIn(name="x", url="https://a.test", cadence_minutes=1)


def test_other_tenants_sources_are_not_found():
    db = FakeSession(Result(value=None))
    resp = asyncio.run(R.get_source(uuid.uuid4(), _user(), db))
    assert resp.status_code == 404


def test_pause_and_resume():
    s = _source()
    resp = asyncio.run(
        R.pause_source(
            s.id,
            R.PauseIn(reason="site redesign"),
            None,
            _user(),
            FakeSession(Result(value=s)),
        )
    )
    assert (
        resp.status_code == 200 and not s.active and s.paused_reason == "site redesign"
    )
    assert _body(resp)["data"]["health"] == "paused"
    s.consecutive_failures = 4
    resp = asyncio.run(
        R.resume_source(s.id, None, _user(), FakeSession(Result(value=s)))
    )
    assert s.active and s.paused_reason is None and s.consecutive_failures == 0
    assert s.next_check_at is not None


def test_check_now_reports_kill_switch_as_conflict():
    s = _source()
    with patch.object(
        SW,
        "check_source",
        AsyncMock(return_value={"status": "stopped", "error": "Stopped."}),
    ):
        resp = asyncio.run(R.check_now(s.id, _user(), FakeSession(Result(value=s))))
    assert (
        resp.status_code == 409 and _body(resp)["error"]["error_code"] == "KILL_SWITCH"
    )


def test_check_now_returns_the_outcome():
    s = _source()
    out = {
        "status": "changed",
        "change_id": "c1",
        "summary": "1 line added and 0 removed.",
    }
    with patch.object(SW, "check_source", AsyncMock(return_value=out)) as chk:
        resp = asyncio.run(
            R.check_now(s.id, _user(), FakeSession(Result(value=s), Result(value=s)))
        )
    assert resp.status_code == 200
    assert _body(resp)["data"]["outcome"]["change_id"] == "c1"
    chk.assert_awaited_once()
    assert chk.await_args.kwargs["manual"] is True


def test_settings_reject_non_hosts():
    db = FakeSession()
    resp = asyncio.run(
        R.put_settings(
            R.SettingsIn(host_allowlist=["https://x.test/path"]), None, _user(), db
        )
    )
    assert resp.status_code == 400


def test_health_labels():
    assert R.health(_source(last_status="stopped")) == "stopped"
    assert R.health(_source(active=False)) == "paused"
    assert (
        R.health(_source(consecutive_failures=2, last_checked_at=SW.now_utc()))
        == "failing"
    )
    assert R.health(_source(last_checked_at=SW.now_utc())) == "ok"


def test_list_with_no_sources():
    db = FakeSession(Result(rows=[]))
    resp = asyncio.run(R.list_sources("", _user(), db))
    assert resp.status_code == 200 and _body(resp)["data"] == []
