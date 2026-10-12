"""Alertmanager webhook: token gate, Redis dedupe, telemetry grouping, cap, background delivery."""

from __future__ import annotations

import inspect
import json
import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core import notifications as notif
from app.routers import admin_alerts

TOKEN = "s3cret-token"
HDRS = {"authorization": f"Bearer {TOKEN}"}


def _request(headers: dict | None = None):
    return SimpleNamespace(headers=headers or {})


def _alert(status="firing", fingerprint="abc123", name="HighErrorRate", labels=None):
    return {
        "status": status,
        "labels": {"alertname": name, "severity": "critical", **(labels or {})},
        "annotations": {"summary": "Abenix API error rate > 5%"},
        "startsAt": "2026-10-01T10:00:00Z",
        "endsAt": (
            "0001-01-01T00:00:00Z" if status == "firing" else "2026-10-01T10:30:00Z"
        ),
        "fingerprint": fingerprint,
    }


def _device(i: int, conn: str = "line-1", status: str = "firing", tenant: str = "t1"):
    return _alert(
        status=status,
        fingerprint=f"dev{conn}{i}",
        name="TelemetryDeviceOffline",
        labels={
            "severity": "warning",
            "tenant_id": tenant,
            "connection": conn,
            "group": "g",
            "node": f"n{i}",
            "device": "-",
        },
    )


def _payload(*alerts):
    return {"version": "4", "receiver": "abenix-api", "alerts": list(alerts)}


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    # every test uses the in-process dedupe so nothing reaches a real Redis
    async def boom():
        raise ConnectionError("no redis in unit tests")

    import app.core.hitl as hitl

    monkeypatch.setattr(hitl, "get_redis", boom)
    admin_alerts._local_seen.clear()
    yield
    admin_alerts._local_seen.clear()


@pytest.fixture
def queued(monkeypatch):
    batches: list[list[dict]] = []

    def fake_enqueue(events):
        batches.append(events)
        return True

    monkeypatch.setattr(admin_alerts, "enqueue", fake_enqueue)
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", TOKEN)
    return batches


async def _post(payload, headers=HDRS):
    resp = await admin_alerts.alert_webhook(payload, _request(headers))
    return json.loads(resp.body)["data"]


@pytest.mark.asyncio
async def test_token_required():
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": TOKEN}):
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(_payload(_alert()), _request())
        assert exc.value.status_code == 401
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(
                _payload(_alert()), _request({"authorization": "Bearer nope"})
            )
        assert exc.value.status_code == 401
    with patch.dict(os.environ, {"ALERT_WEBHOOK_TOKEN": ""}):
        with pytest.raises(HTTPException) as exc:
            await admin_alerts.alert_webhook(
                _payload(_alert()), _request({"x-alert-token": "anything"})
            )
        assert exc.value.status_code == 503


def test_webhook_takes_no_request_db_session():
    # the request pool is never touched by an alert storm
    assert "db" not in inspect.signature(admin_alerts.alert_webhook).parameters


@pytest.mark.asyncio
async def test_firing_alert_is_queued(queued):
    body = await _post(_payload(_alert()))
    assert body == {"received": 1, "queued": 1, "skipped": 0, "dropped": 0}
    ev = queued[0][0]
    assert ev["name"] == "HighErrorRate"
    assert ev["severity"] == "critical"
    assert ev["status"] == "firing"
    assert ev["fingerprint"] == "abc123"
    assert ev["since"] == "2026-10-01T10:00:00Z"


@pytest.mark.asyncio
async def test_resolved_alert_uses_ends_at(queued):
    await _post(_payload(_alert(status="resolved")))
    assert queued[0][0]["status"] == "resolved"
    assert queued[0][0]["since"] == "2026-10-01T10:30:00Z"


@pytest.mark.asyncio
async def test_dedupe_by_fingerprint_and_status(queued):
    assert (await _post(_payload(_alert())))["queued"] == 1
    again = await _post(_payload(_alert()))
    assert again == {"received": 1, "queued": 0, "skipped": 1, "dropped": 0}
    # a resolve is a different event
    assert (await _post(_payload(_alert(status="resolved"))))["queued"] == 1
    # a different fingerprint for the same rule is not deduped
    assert (await _post(_payload(_alert(fingerprint="zzz999"))))["queued"] == 1


@pytest.mark.asyncio
async def test_redis_dedupe_uses_set_nx_ex(monkeypatch):
    calls = []

    class Pipe:
        def set(self, key, val, nx, ex):
            calls.append((key, nx, ex))

        async def execute(self):
            return [True, None]

    class R:
        def pipeline(self, transaction):
            return Pipe()

    async def redis():
        return R()

    import app.core.hitl as hitl

    monkeypatch.setattr(hitl, "get_redis", redis)
    events, _, _ = admin_alerts.plan_batch(
        [_alert(), _alert(fingerprint="other")], cap=10
    )
    out = await admin_alerts.claim_events(events, 1800)
    assert out == [True, False]
    assert calls[0] == ("alerts:seen:firing:fp:abc123", True, 1800)


@pytest.mark.asyncio
async def test_telemetry_offline_grouped_per_connection(queued):
    alerts = [_device(i, "line-1") for i in range(3000)]
    alerts += [_device(i, "line-2") for i in range(2000)]
    body = await _post(_payload(*alerts))
    assert body == {"received": 5000, "queued": 2, "skipped": 0, "dropped": 0}
    by_conn = {ev["labels"]["connection"]: ev for ev in queued[0]}
    assert by_conn["line-1"]["summary"].startswith(
        "3000 devices on line-1 went offline"
    )
    assert by_conn["line-1"]["labels"]["devices"] == "3000"
    assert by_conn["line-1"]["labels"]["tenant_id"] == "t1"
    # the next wave inside the window is folded into the one already sent
    again = await _post(_payload(*[_device(i, "line-1") for i in range(10)]))
    assert again["queued"] == 0 and again["skipped"] == 1


@pytest.mark.asyncio
async def test_grouped_resolve_reads_well(queued):
    await _post(_payload(*[_device(i, status="resolved") for i in range(4)]))
    ev = queued[0][0]
    assert ev["status"] == "resolved"
    assert ev["summary"] == "Offline alert for 4 devices on line-1 (n0, n1, n2, n3)"


@pytest.mark.asyncio
async def test_cap_per_request(queued, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_MAX_ALERTS", "200")
    alerts = [_alert(fingerprint=f"f{i}", name=f"A{i}") for i in range(500)]
    body = await _post(_payload(*alerts))
    assert body == {"received": 500, "queued": 200, "skipped": 0, "dropped": 300}


@pytest.mark.asyncio
async def test_full_queue_drops_and_still_answers(monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_TOKEN", TOKEN)
    monkeypatch.setattr(admin_alerts, "enqueue", lambda events: False)
    body = await _post(_payload(_alert()))
    assert body == {"received": 1, "queued": 0, "skipped": 0, "dropped": 1}


@pytest.mark.asyncio
async def test_storm_of_5000_answers_fast(queued):
    alerts = [_device(i, f"c{i % 7}") for i in range(4000)]
    alerts += [_alert(fingerprint=f"f{i}", name=f"A{i}") for i in range(1000)]
    t0 = time.perf_counter()
    body = await _post(_payload(*alerts))
    took = time.perf_counter() - t0
    assert body["received"] == 5000
    assert body["queued"] == 200 and body["dropped"] == 807
    assert took < 1.0


@pytest.mark.asyncio
async def test_enqueue_runs_one_worker_and_bounds_the_queue(monkeypatch):
    import asyncio

    delivered = []

    async def fake_deliver(events):
        delivered.append(events)

    monkeypatch.setattr(admin_alerts, "deliver_events", fake_deliver)
    monkeypatch.setenv("ALERT_WEBHOOK_QUEUE_MAX", "2")
    monkeypatch.setattr(admin_alerts, "_queue", None)
    monkeypatch.setattr(admin_alerts, "_worker", None)
    assert admin_alerts.enqueue([{"n": 1}])
    assert admin_alerts.enqueue([{"n": 2}])
    assert not admin_alerts.enqueue([{"n": 3}])
    await asyncio.wait_for(admin_alerts._queue.join(), 2)
    assert delivered == [[{"n": 1}], [{"n": 2}]]
    admin_alerts._worker.cancel()


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.added = []
        self.flushes = 0
        self.stmts = []
        self.admins = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        self.stmts.append(str(stmt))

        class R:
            def __init__(self, rows):
                self.rows = rows

            def all(self):
                return self.rows

            def scalars(self):
                return self

        return R(self.admins)

    def add_all(self, rows):
        self.added.extend(rows)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_deliver_events_one_transaction_on_background_pool(monkeypatch):
    import app.core.deps as deps

    sess = FakeSession()
    monkeypatch.setattr(deps, "bg_session", lambda: sess)
    fanout = AsyncMock(return_value=3)
    monkeypatch.setattr(notif, "notify_platform_alert", fanout)
    events, _, _ = admin_alerts.plan_batch(
        [_alert(), _alert(fingerprint="b")] + [_device(i) for i in range(5)], cap=50
    )
    assert await admin_alerts.deliver_events(events) == 9
    assert sess.commits == 1
    caches = {id(c.kwargs["admins_cache"]) for c in fanout.await_args_list}
    assert len(caches) == 1
    links = [c.kwargs["link"] for c in fanout.await_args_list]
    assert links == ["/alerts", "/alerts", "/telemetry"]


@pytest.mark.asyncio
async def test_platform_alert_bulk_writes_and_scopes_to_tenant(monkeypatch):
    tenant = uuid.uuid4()
    sess = FakeSession()
    sess.admins = [(uuid.uuid4(), tenant), (uuid.uuid4(), tenant)]
    monkeypatch.setattr(notif.ws_manager, "send_to_user", AsyncMock())
    monkeypatch.delenv("ABENIX_SLACK_WEBHOOK_URL", raising=False)
    cache: dict = {}
    n = await notif.notify_platform_alert(
        sess,
        name="TelemetryDeviceOffline",
        severity="warning",
        summary="3 devices on line-1 went offline",
        since=None,
        labels={"tenant_id": str(tenant), "connection": "line-1"},
        admins_cache=cache,
    )
    assert n == 2
    assert sess.flushes == 1 and len(sess.added) == 2
    assert all(r.type == "system_alert" for r in sess.added)
    assert "users.tenant_id" in sess.stmts[0]
    # the second alert reuses the admin list
    before = len([s for s in sess.stmts if "FROM users" in s])
    await notif.notify_platform_alert(
        sess,
        name="TelemetryDeviceOffline",
        severity="warning",
        summary="x",
        since=None,
        labels={"tenant_id": str(tenant)},
        admins_cache=cache,
    )
    assert len([s for s in sess.stmts if "FROM users" in s]) == before


@pytest.mark.asyncio
async def test_platform_alert_without_tenant_goes_to_every_admin(monkeypatch):
    sess = FakeSession()
    sess.admins = [(uuid.uuid4(), uuid.uuid4())]
    monkeypatch.setattr(notif.ws_manager, "send_to_user", AsyncMock())
    monkeypatch.delenv("ABENIX_SLACK_WEBHOOK_URL", raising=False)
    await notif.notify_platform_alert(
        sess, name="RedisDown", severity="critical", summary="", since=None
    )
    assert "users.tenant_id =" not in sess.stmts[0]


@pytest.mark.asyncio
async def test_retention_deletes_in_batches(monkeypatch):
    import app.core.deps as deps
    import app.core.platform_settings as ps

    calls = []
    expired = [5000, 5000, 12]

    class S(FakeSession):
        async def execute(self, stmt, params=None):
            sql = str(stmt)
            calls.append((sql, params))

            class R:
                rowcount = 0

                def all(self_inner):
                    return [("u1",)] if "FROM users" in sql else []

            r = R()
            if "created_at < :cutoff" in sql:
                r.rowcount = expired.pop(0)
            elif "OFFSET :keep" in sql:
                r.rowcount = 7
            return r

    monkeypatch.setattr(deps, "bg_session", lambda: S())

    async def setting(key, fallback):
        return fallback

    monkeypatch.setattr(ps, "get_int_setting", setting)
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    monkeypatch.setattr(notif, "ensure_alert_indexes", AsyncMock(return_value=["ix"]))
    out = await notif.prune_system_alerts()
    assert out == {"expired": 10012, "over_cap": 7, "indexes_built": 1}
    assert all("LIMIT :n" in sql for sql, _ in calls if sql.startswith("DELETE"))
    cap_call = [p for sql, p in calls if "OFFSET :keep" in sql][0]
    assert cap_call["keep"] == 500 and cap_call["u"] == "u1"
    # the per person cap runs before the scan by age, so a storm shrinks through the index
    deletes = [sql for sql, _ in calls if sql.startswith("DELETE")]
    assert "OFFSET :keep" in deletes[0] and "created_at < :cutoff" in deletes[-1]


@pytest.mark.asyncio
async def test_retention_keeps_going_when_a_step_times_out(monkeypatch):
    import app.core.deps as deps
    import app.core.platform_settings as ps

    class S(FakeSession):
        async def execute(self, stmt, params=None):
            sql = str(stmt)

            class R:
                rowcount = 3

                def all(self_inner):
                    return [("u1",), ("u2",)]

            if "user_id = :u" in sql and params["u"] == "u1":
                raise RuntimeError("canceling statement due to statement timeout")
            return R()

    monkeypatch.setattr(deps, "bg_session", lambda: S())

    async def setting(key, fallback):
        return fallback

    monkeypatch.setattr(ps, "get_int_setting", setting)
    monkeypatch.setattr(
        notif, "ensure_alert_indexes", AsyncMock(side_effect=RuntimeError("busy"))
    )
    out = await notif.prune_system_alerts()
    assert out == {"over_cap": 3, "expired": 3}


def test_migration_builds_indexes_concurrently_and_never_blocks_a_deploy():
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[2]
        / "packages/db/alembic/versions/fix259a01_notification_alert_indexes.py"
    ).read_text()
    assert (
        "autocommit_block" in src and "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in src
    )
    assert 'down_revision = "agt258a01"' in src


def test_retention_job_registered():
    from app.core import job_runs, platform_settings, scheduler

    src = inspect.getsource(scheduler.start_scheduler)
    assert '_tracked("alert_notification_retention"' in src
    assert job_runs.CATALOGUE["alert_notification_retention"].destructive
    d = platform_settings.DEFAULTS["notifications.system_alert_retention_days"]
    assert d["value"] == "14"


def test_auth_paths_use_priority_pool():
    from app.core import deps
    from app.routers import auth

    for fn in (auth.login, auth.login_two_factor, auth.refresh):
        assert inspect.signature(fn).parameters["db"].default.dependency is (
            deps.get_priority_db
        )
    me_dep = inspect.signature(auth.me).parameters["user"].default.dependency
    assert me_dep is deps.get_current_user_priority
    assert deps.priority_engine is not deps.engine
    assert deps.bg_engine is not deps.engine


@pytest.mark.asyncio
async def test_session_touch_does_not_wait_for_the_pool(monkeypatch):
    import asyncio

    from app.core import sessions

    gate = asyncio.Event()

    async def slow(sid):
        await gate.wait()

    monkeypatch.setattr(sessions, "_write_touch", slow)
    sessions._touched.clear()
    await asyncio.wait_for(sessions.touch(uuid.uuid4()), 0.5)
    gate.set()


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


# gap 3: alerts page filters


def _shaped(name, state, **labels):
    return {
        "name": name,
        "state": state,
        "summary": f"{name} summary",
        "labels": {"alertname": name, **labels},
    }


def test_alert_filters():
    alerts = [
        _shaped("TelemetryRule", "firing", rule_id="r1", node="press-4"),
        _shaped("TelemetryRule", "firing", rule_id="r2", node="press-5"),
        _shaped("HighErrorRate", "pending", severity="critical"),
        _shaped("RedisDown", "silenced"),
    ]
    f = admin_alerts.filter_alerts
    assert [a["labels"].get("rule_id") for a in f(alerts, rule_id="r1")] == ["r1"]
    assert len(f(alerts, alertname="telemetryrule")) == 2
    assert len(f(alerts, alertname="TelemetryRule,RedisDown")) == 3
    assert [a["name"] for a in f(alerts, status="pending")] == ["HighErrorRate"]
    assert [a["labels"]["node"] for a in f(alerts, labels=["node:press-5"])] == [
        "press-5"
    ]
    assert [a["name"] for a in f(alerts, q="critical")] == ["HighErrorRate"]
    assert len(f(alerts, q="press")) == 2
    assert len(f(alerts)) == 4


def test_firing_alert_has_no_resolve_time():
    shaped = admin_alerts._shape_am_alert(
        {
            "labels": {"alertname": "TelemetryRule"},
            "startsAt": "2026-10-01T10:00:00Z",
            "endsAt": "2026-10-01T10:05:00Z",
            "status": {"state": "active", "silencedBy": [], "inhibitedBy": []},
        }
    )
    assert shaped["state"] == "firing" and shaped["ends_at"] is None


@pytest.mark.asyncio
async def test_list_alerts_applies_filters(monkeypatch):
    rows = [
        _shaped("TelemetryRule", "firing", rule_id="r1"),
        _shaped("HighErrorRate", "firing"),
    ]
    monkeypatch.setattr(
        admin_alerts, "fetch_alertmanager_alerts", AsyncMock(return_value=rows)
    )
    admin = SimpleNamespace(role="admin", is_admin=True)
    resp = await admin_alerts.list_alerts(
        admin, q="", alertname="", status="", label=[], rule_id="r1"
    )
    data = json.loads(resp.body)["data"]
    assert data["matched"] == 1 and data["total"] == 2 and data["counts"]["firing"] == 2


# busy answers carry a code the web client retries on


def test_busy_answers_carry_a_retry_code():
    from app.core import principal

    exc = principal._busy()
    assert exc.status_code == 503 and exc.detail["error_code"] == "BUSY"


@pytest.mark.asyncio
async def test_database_timeouts_answer_503_service_unavailable():
    from sqlalchemy.exc import OperationalError

    from app import main

    req = SimpleNamespace(method="GET", url=SimpleNamespace(path="/api/x"), headers={})
    resp = await main._db_unavailable_handler(
        req,
        OperationalError(
            "SELECT 1", {}, Exception("canceling statement due to statement timeout")
        ),
    )
    body = json.loads(resp.body)
    assert (
        resp.status_code == 503 and body["error"]["error_code"] == "SERVICE_UNAVAILABLE"
    )
    assert resp.headers["retry-after"] == "2"
