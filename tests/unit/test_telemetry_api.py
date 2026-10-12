"""/api/telemetry: connections, device reads, health, the stream hub and governed commands."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import me as ME
from app.routers import telemetry as R
from app.telemetry import access
from app.telemetry import keys as K
from app.telemetry import sparkplug as sp
from app.telemetry import stream as S
from models.telemetry import TelemetryConnection
from telemetry_fakes import FakeRedis

TENANT = uuid.uuid4()
G, N = "groundwork", "ipc-ex1"


class Result:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalar(self):
        return self.value

    def first(self):
        return self.value

    def all(self):
        return self.rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class FakeSession:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.added: list = []
        self.deleted: list = []
        self.commits = 0
        self.closed = False

    async def execute(self, stmt):
        return self.results.pop(0) if self.results else Result()

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def refresh(self, obj):
        return None

    async def delete(self, obj):
        self.deleted.append(obj)

    async def close(self):
        self.closed = True


def _user(role="admin", **kw):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT, email="a@b.test", role=role, **kw
    )


def _conn(**kw):
    c = TelemetryConnection(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Site broker",
        broker_url="mqtt://abenix-mosquitto:1883",
        topics=["spBv1.0/#"],
        raw_topics=[],
        protocol="sparkplug_b",
        enabled=True,
        shared_subscription=False,
        password=None,
        username=None,
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _scope(conns, everything=True, visible=(), commandable=(), teams=None):
    return access.Scope(
        everything=everything,
        visible=set(visible),
        commandable=set(commandable),
        teams=teams or {},
        connections=list(conns),
    )


def _body(resp):
    return json.loads(resp.body)


@pytest.fixture
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(R, "redis", lambda: r)
    monkeypatch.setattr(R, "log_action", AsyncMock())
    monkeypatch.setattr(
        R.Q,
        "for_tenant",
        AsyncMock(
            return_value={
                "max_connections": 2,
                "max_devices": 5000,
                "max_msgs_per_sec": 20000,
                "retention_days": 7,
            }
        ),
    )
    R._health_cache.clear()
    access.forget()
    return r


def _grant(monkeypatch, *caps):
    async def has(db, user, cap):
        return cap in caps or "*" in caps

    monkeypatch.setattr(access, "has", has)


async def _seed_node(r, conn_id, online="1", devices=("engine",)):
    await r.hset(
        K.device(TENANT, G, N, ""),
        mapping={
            "_online": online,
            "_conn": conn_id,
            "_offline_at": "1791720000000",
            "_last_seen": "1",
        },
    )
    await r.sadd(K.node_devices(TENANT, G, N), "", *devices)
    await r.hset(
        K.index(TENANT),
        f"{G}/{N}/",
        json.dumps(
            {
                "group": G,
                "node": N,
                "device": "",
                "online": online == "1",
                "connection_id": conn_id,
            }
        ),
    )
    for d in devices:
        await r.hset(
            K.device(TENANT, G, N, d),
            mapping={
                "_online": online,
                "_conn": conn_id,
                "m:Safety/Hold": K.pack_metric(False, "Boolean", 1, "good"),
                "m:Engine/Speed_rpm": K.pack_metric(1450.5, "Double", 2, "good"),
            },
        )
        await r.hset(
            K.index(TENANT),
            f"{G}/{N}/{d}",
            json.dumps(
                {
                    "group": G,
                    "node": N,
                    "device": d,
                    "online": online == "1",
                    "connection_id": conn_id,
                    "metric_count": 2,
                }
            ),
        )


# connections


def test_members_cannot_change_brokers(fake, monkeypatch):
    _grant(monkeypatch, "telemetry.view")
    resp = asyncio.run(
        R.create_connection(
            None, {"name": "x", "broker_url": "mqtt://a"}, _user("user"), FakeSession()
        )
    )
    assert resp.status_code == 403
    err = _body(resp)["error"]
    assert (
        err["error_code"] == "FORBIDDEN"
        and "Manage telemetry brokers" in err["message"]
    )


def test_create_validates_in_plain_words(fake, monkeypatch):
    _grant(monkeypatch, "*")
    resp = asyncio.run(
        R.create_connection(
            None, {"name": "x", "broker_url": "http://a"}, _user(), FakeSession()
        )
    )
    assert resp.status_code == 422
    assert "mqtt://" in _body(resp)["error"]["message"]
    resp = asyncio.run(
        R.create_connection(
            None,
            {"name": "x", "broker_url": "mqtt://a", "topics": ["a/#/b"]},
            _user(),
            FakeSession(),
        )
    )
    assert resp.status_code == 422 and "#" in _body(resp)["error"]["message"]


def test_create_enforces_the_connection_quota(fake, monkeypatch):
    _grant(monkeypatch, "*")
    db = FakeSession(Result(value=2))
    resp = asyncio.run(
        R.create_connection(
            None, {"name": "x", "broker_url": "mqtt://a:1883"}, _user(), db
        )
    )
    assert resp.status_code == 429
    err = _body(resp)["error"]
    assert err["error_code"] == "QUOTA_EXCEEDED" and "limit is 2" in err["message"]


def test_create_masks_the_password_and_tells_the_ingest(fake, monkeypatch):
    _grant(monkeypatch, "*")
    user = _user()

    async def scope_for(db, u, fresh=False):
        return _scope([])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(access, "share_counts", AsyncMock(return_value={}))
    db = FakeSession(Result(value=0))
    resp = asyncio.run(
        R.create_connection(
            None,
            {
                "name": "Site broker",
                "broker_url": "mqtt://abenix-mosquitto:1883",
                "username": "u",
                "password": "secret",
            },
            user,
            db,
        )
    )
    assert resp.status_code == 201, _body(resp)
    row = _body(resp)["data"]
    assert row["password"] == R.MASK and row["has_password"] is True
    assert (
        row["topics"] == ["spBv1.0/#"]
        and row["team_id"] is None
        and row["team_name"] is None
    )
    assert row["share_count"] == 0 and row["status"] == "error"
    assert "ingest service is not running" in row["last_error"]
    assert db.added[0].created_by == user.id
    assert any(ch == K.CHANGED for ch, _ in fake.published)


def test_patch_keeps_the_password_when_given_the_mask(fake, monkeypatch):
    _grant(monkeypatch, "*")
    c = _conn(password="stored")

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(access, "share_counts", AsyncMock(return_value={str(c.id): 3}))
    db = FakeSession(Result(value=c))
    resp = asyncio.run(
        R.update_connection(
            c.id, None, {"password": R.MASK, "enabled": False}, _user(), db
        )
    )
    assert resp.status_code == 200
    assert c.password == "stored" and c.enabled is False
    row = _body(resp)["data"]
    assert row["status"] == "disabled" and row["share_count"] == 3


def test_connection_rows_carry_live_status_and_team(fake, monkeypatch):
    team = uuid.uuid4()
    c = _conn(team_id=team)
    now = int(time.time() * 1000)
    asyncio.run(
        fake.hset(
            K.conn_status(c.id),
            "rep-a",
            json.dumps(
                {
                    "status": "connected",
                    "messages_per_second": 412.5,
                    "last_message_at": now,
                    "at": now,
                    "dropped": 0,
                }
            ),
        )
    )

    async def scope_for(db, u, fresh=False):
        return _scope([c], teams={str(team): "Site North"})

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(access, "share_counts", AsyncMock(return_value={}))
    resp = asyncio.run(
        R.list_connections("", "", "", 200, 0, _user("user"), FakeSession())
    )
    body = _body(resp)
    row = body["data"][0]
    assert row["status"] == "connected" and row["messages_per_second"] == 412.5
    assert row["team_name"] == "Site North" and row["last_message_at"] == now
    assert body["meta"]["total"] == 1


def test_shares_accept_telemetry_connections():
    assert "telemetry_connection" in ME._SHAREABLE_KINDS


# reads


def test_devices_list_filters_and_counts(fake, monkeypatch):
    c1, c2 = _conn(), _conn(name="Other", team_id=uuid.uuid4())
    asyncio.run(_seed_node(fake, str(c1.id)))
    asyncio.run(
        fake.hset(
            K.index(TENANT),
            "other/n2/",
            json.dumps(
                {
                    "group": "other",
                    "node": "n2",
                    "device": "",
                    "online": False,
                    "connection_id": str(c2.id),
                    "team_id": str(c2.team_id),
                }
            ),
        )
    )

    async def scope_for(db, u, fresh=False):
        return _scope([c1, c2], everything=False, visible={str(c1.id)})

    monkeypatch.setattr(access, "scope_for", scope_for)
    resp = asyncio.run(
        R.list_devices("", "", "", "", "", 500, 0, _user("user"), FakeSession())
    )
    body = _body(resp)
    assert body["meta"]["total"] == 2, "the other team's machine stays hidden"
    assert {d["device"] for d in body["data"]} == {"", "engine"}
    assert body["data"][0]["team_name"] is None
    resp = asyncio.run(
        R.list_devices("eng", "", "", "online", "", 1, 0, _user("user"), FakeSession())
    )
    assert _body(resp)["meta"]["total"] == 1 and len(_body(resp)["data"]) == 1
    resp = asyncio.run(
        R.list_devices("", "", "", "sideways", "", 1, 0, _user("user"), FakeSession())
    )
    assert resp.status_code == 422


def test_node_detail_and_visibility(fake, monkeypatch):
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    _grant(monkeypatch, "telemetry.view")
    doc = _body(asyncio.run(R.get_node(G, N, None, _user(), FakeSession())))["data"]
    assert doc["online"] is True and doc["connection_name"] == "Site broker"
    eng = doc["devices"][0]
    assert eng["device"] == "engine"
    assert [m["name"] for m in eng["metrics"]] == ["Engine/Speed_rpm", "Safety/Hold"]
    assert eng["metrics"][0] == {
        "name": "Engine/Speed_rpm",
        "value": 1450.5,
        "type": "Double",
        "ts": 2,
        "quality": "good",
    }
    assert doc["can_command"] is False
    one = _body(asyncio.run(R.get_node(G, N, "engine", _user(), FakeSession())))["data"]
    assert len(one["devices"]) == 1

    async def hidden(db, u, fresh=False):
        return _scope([c], everything=False, visible=set())

    monkeypatch.setattr(access, "scope_for", hidden)
    assert (
        asyncio.run(R.get_node(G, N, None, _user("user"), FakeSession())).status_code
        == 404
    )


def test_node_read_is_fast(fake, monkeypatch):
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id), devices=tuple(f"ecu{i}" for i in range(8))))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    _grant(monkeypatch, "*")
    took = []
    for _ in range(50):
        t0 = time.perf_counter()
        asyncio.run(R.get_node(G, N, None, _user(), FakeSession()))
        took.append(time.perf_counter() - t0)
    assert sorted(took)[len(took) // 2] < 0.05


# commands


def test_command_needs_the_capability(fake, monkeypatch):
    _grant(monkeypatch, "telemetry.view")
    body = R.CommandIn(
        group=G,
        node=N,
        device="safety",
        metric="Safety/Hold",
        value=True,
        reason="operator in zone",
    )
    resp = asyncio.run(R.send_command(body, None, _user("user"), FakeSession()))
    assert resp.status_code == 403
    err = _body(resp)["error"]
    assert err["error_code"] == "FORBIDDEN" and "Machine operators" in err["message"]


def test_api_key_scopes_can_grant_commands():
    key_user = SimpleNamespace(
        _api_key_scopes={"allowed_actions": ["telemetry.command"]}
    )
    assert access.api_key_grants(key_user, "telemetry.command")
    assert access.api_key_grants(
        SimpleNamespace(_api_key_scopes=["telemetry.*"]), "telemetry.command"
    )
    assert not access.api_key_grants(
        SimpleNamespace(_api_key_scopes={"allowed_actions": ["execute"]}),
        "telemetry.command",
    )
    assert not access.api_key_grants(SimpleNamespace(), "telemetry.command")


def test_command_refuses_an_offline_node_in_plain_words(fake, monkeypatch):
    _grant(monkeypatch, "*")
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id), online="0"))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    body = R.CommandIn(
        group=G,
        node=N,
        device="engine",
        metric="Safety/Hold",
        value=True,
        reason="operator in zone",
    )
    resp = asyncio.run(R.send_command(body, None, _user(), FakeSession()))
    assert resp.status_code == 409
    err = _body(resp)["error"]
    assert err["error_code"] == "NODE_OFFLINE" and "offline since" in err["message"]


def test_command_checks_team_access(fake, monkeypatch):
    _grant(monkeypatch, "telemetry.command", "telemetry.view")
    c = _conn(team_id=uuid.uuid4())
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c], everything=False, visible={str(c.id)}, commandable=set())

    monkeypatch.setattr(access, "scope_for", scope_for)
    body = R.CommandIn(
        group=G,
        node=N,
        device="engine",
        metric="Safety/Hold",
        value=True,
        reason="operator in zone",
    )
    resp = asyncio.run(R.send_command(body, None, _user("user"), FakeSession()))
    assert resp.status_code == 403 and _body(resp)["error"]["error_code"] == "FORBIDDEN"


def test_command_publishes_a_dcmd_and_is_audited(fake, monkeypatch):
    _grant(monkeypatch, "*")
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    sent = []

    async def publish(conn_id, url, user, pw, topic, payload):
        sent.append((topic, payload))

    monkeypatch.setattr(R.brokers.publisher, "publish", publish)
    user = _user()
    db = FakeSession()
    body = R.CommandIn(
        group=G,
        node=N,
        device="engine",
        metric="Safety/Hold",
        value="true",
        reason="person in the swing radius",
    )
    resp = asyncio.run(R.send_command(body, None, user, db))
    assert resp.status_code == 200, _body(resp)
    data = _body(resp)["data"]
    assert data["published"] is True and data["at"]
    assert data["topic"] == f"spBv1.0/{G}/DCMD/{N}/engine"
    topic, payload = sent[0]
    m = sp.decode(payload).metrics[0]
    assert (
        m.name == "Safety/Hold"
        and m.datatype == sp.TYPE_IDS["Boolean"]
        and m.boolean_value is True
    )
    call = R.log_action.await_args
    assert call.args[3] == "telemetry.command"
    details = call.args[4]
    assert (
        details["reason"] == "person in the swing radius" and details["value"] is True
    )
    assert details["metric"] == "Safety/Hold" and db.commits == 1


def test_command_without_device_is_an_ncmd_and_dry_run_sends_nothing(fake, monkeypatch):
    _grant(monkeypatch, "*")
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(
        R.brokers.publisher,
        "publish",
        AsyncMock(side_effect=AssertionError("dry run sent")),
    )
    body = R.CommandIn(
        group=G,
        node=N,
        device="",
        metric="Mode/Set",
        value="safe",
        reason="",
        dry_run=True,
    )
    data = _body(asyncio.run(R.send_command(body, None, _user(), FakeSession())))[
        "data"
    ]
    assert data["published"] is False and data["topic"] == f"spBv1.0/{G}/NCMD/{N}"
    assert data["payload"]["metrics"][0]["value"] == "safe"


def test_command_rate_limit_is_20_a_second_per_node(fake, monkeypatch):
    _grant(monkeypatch, "*")
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(R.brokers.publisher, "publish", AsyncMock())
    body = R.CommandIn(
        group=G,
        node=N,
        device="engine",
        metric="Safety/Hold",
        value=True,
        reason="burst test",
    )
    asyncio.run(fake.set(K.command_rate(TENANT, G, N, int(time.time())), 20))
    resp = asyncio.run(R.send_command(body, None, _user(), FakeSession()))
    if resp.status_code == 200:
        # the second rolled over between the two calls, try once more
        asyncio.run(fake.set(K.command_rate(TENANT, G, N, int(time.time())), 20))
        resp = asyncio.run(R.send_command(body, None, _user(), FakeSession()))
    assert (
        resp.status_code == 429 and _body(resp)["error"]["error_code"] == "RATE_LIMITED"
    )


def test_command_needs_a_reason(fake, monkeypatch):
    _grant(monkeypatch, "*")
    body = R.CommandIn(
        group=G, node=N, device="engine", metric="Safety/Hold", value=True, reason=" "
    )
    resp = asyncio.run(R.send_command(body, None, _user(), FakeSession()))
    assert resp.status_code == 422 and "why" in _body(resp)["error"]["message"]


# health and the live stream


def test_health_endpoint(fake, monkeypatch):
    c = _conn()
    asyncio.run(_seed_node(fake, str(c.id)))

    async def scope_for(db, u, fresh=False):
        return _scope([c])

    monkeypatch.setattr(access, "scope_for", scope_for)
    doc = _body(asyncio.run(R.get_health(_user(), FakeSession())))["data"]
    assert doc["ingest_up"] is False and doc["nodes_total"] == 1
    assert (
        doc["quota"]["max_connections"] == 2
        and doc["quota"]["used"]["connections"] == 1
    )
    assert doc["connections"][0]["status"] == "error"


def test_hub_fans_one_message_out_to_matching_viewers():
    hub = S.Hub()
    everyone = S.Viewer(tenant="t", scope=_scope([]))
    one_node = S.Viewer(tenant="t", scope=_scope([]), nodes={(G, N)})
    hidden = S.Viewer(tenant="t", scope=_scope([], everything=False, visible=set()))
    hub.by_pattern[K.tenant_channels("t")] |= {everyone, hidden}
    hub.by_channel[K.channel("t", G, N)].add(one_node)
    doc = {
        "type": "metrics",
        "group": G,
        "node": N,
        "device": "engine",
        "connection_id": "c1",
        "metrics": [],
    }
    hub.dispatch(
        {
            "type": "pmessage",
            "pattern": K.tenant_channels("t"),
            "channel": K.channel("t", G, N),
            "data": json.dumps(doc),
        }
    )
    hub.dispatch(
        {"type": "message", "channel": K.channel("t", G, N), "data": json.dumps(doc)}
    )
    assert (
        everyone.queue.qsize() == 1
        and one_node.queue.qsize() == 1
        and hidden.queue.qsize() == 0
    )


def test_a_slow_viewer_drops_the_oldest():
    v = S.Viewer(tenant="t", scope=_scope([]))
    for i in range(S.QUEUE_MAX + 5):
        v.offer("metrics", {"i": i})
    assert v.dropped == 5 and v.queue.get_nowait()[1]["i"] == 5


def test_coalescer_holds_a_device_to_ten_a_second():
    co = S.Coalescer()
    mk = lambda v: {
        "group": G,
        "node": N,
        "device": "engine",
        "metrics": [{"name": "Engine/Speed_rpm", "value": v}],
    }  # noqa: E731
    co.add(mk(1))
    assert len(co.due(now=100.0)) == 1
    co.add(mk(2))
    co.add(mk(3))
    assert co.due(now=100.05) == []
    out = co.due(now=100.11)
    assert len(out) == 1 and out[0]["metrics"][0]["value"] == 3


def test_parse_nodes():
    assert S.parse_nodes("groundwork/ipc-ex1, groundwork/ipc-tc1", None, None) == {
        (G, "ipc-ex1"),
        (G, "ipc-tc1"),
    }
    assert S.parse_nodes(None, G, N) == {(G, N)}
    assert S.parse_nodes(None, G, None) is None
    with pytest.raises(ValueError):
        S.parse_nodes("nogroup", None, None)


def test_stream_caps_live_views_per_person(fake, monkeypatch):
    user = _user()

    async def scope_for(db, u, fresh=False):
        return _scope([])

    monkeypatch.setattr(access, "scope_for", scope_for)
    import app.core.platform_settings as PS

    monkeypatch.setattr(PS, "get_int_setting", AsyncMock(return_value=2))
    asyncio.run(fake.zadd(K.sse_viewers(user.id), {"a": time.time(), "b": time.time()}))
    db = FakeSession()
    resp = asyncio.run(R.stream(SimpleNamespace(), None, None, None, None, user, db))
    assert db.closed and resp.status_code == 429
    assert _body(resp)["error"]["error_code"] == "RATE_LIMITED"


def _sample(f):
    if f.kind == "list":
        return ["things/#"]
    if f.kind == "int":
        return 1
    if f.kind == "bool":
        return True
    if f.kind == "select":
        return f.options[0] if f.options else "x"
    if f.kind == "url":
        return "mqtt://broker:1883" if f.key == "broker_url" else "tcp://host:1234"
    return "host:1234" if f.kind != "secret" else "s3cret"


def _transports():
    from app.telemetry import registry

    return sorted(registry.connectors())


@pytest.mark.parametrize("transport", _transports())
def test_every_transport_can_be_created_and_patched(fake, monkeypatch, transport):
    from app.telemetry import registry

    _grant(monkeypatch, "*")

    async def scope_for(db, u, fresh=False):
        return _scope([])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(access, "share_counts", AsyncMock(return_value={}))
    cls = registry.connectors()[transport]
    cfg = {f.key: _sample(f) for f in cls.config_fields if f.required}
    body = {"name": f"{transport} source", "transport": transport, "config": cfg}
    db = FakeSession(Result(value=0))
    resp = asyncio.run(R.create_connection(None, body, _user(), db))
    assert resp.status_code == 201, _body(resp)
    row = _body(resp)["data"]
    assert row["transport"] == transport and row["decoder"]
    assert not any(v != R.MASK for v in row["secrets"].values())
    c = db.added[0]
    resp = asyncio.run(
        R.update_connection(
            c.id,
            None,
            {"enabled": False, "config": dict(cfg)},
            _user(),
            FakeSession(Result(value=c)),
        )
    )
    assert resp.status_code == 200, _body(resp)
    assert _body(resp)["data"]["enabled"] is False


@pytest.mark.parametrize("shape", ["top", "config"])
def test_subjects_are_taken_at_the_top_or_inside_config(fake, monkeypatch, shape):
    from app.telemetry import pipeline

    _grant(monkeypatch, "*")

    async def scope_for(db, u, fresh=False):
        return _scope([])

    monkeypatch.setattr(access, "scope_for", scope_for)
    monkeypatch.setattr(access, "share_counts", AsyncMock(return_value={}))
    body = {"name": "Payments", "transport": "http_push", "config": {}}
    if shape == "top":
        body["subjects"] = ["payments.orders"]
    else:
        body["config"]["subjects"] = ["payments.orders"]
    db = FakeSession(Result(value=0))
    resp = asyncio.run(R.create_connection(None, body, _user(), db))
    assert resp.status_code == 201, _body(resp)
    c = db.added[0]
    assert c.topics == ["payments.orders"]
    assert pipeline.connection_row(c)["config"]["subjects"] == ["payments.orders"]
    c.topics = []
    c.config = {"subjects": ["kept"]}
    assert pipeline.connection_row(c)["config"]["subjects"] == ["kept"]


def test_rules_mode_is_a_choice_setting():
    from app.core.platform_settings import DEFAULTS
    from app.routers import admin_settings as A

    meta = DEFAULTS["telemetry.rules_mode"]
    assert meta["kind"] == "choice" and meta["value"] in meta["choices"]
    user = SimpleNamespace(role="admin", is_superuser=True, id=uuid.uuid4())

    async def go():
        res = await A.update_setting(
            "telemetry.rules_mode", {"value": "elsewhere"}, user, AsyncMock()
        )
        assert res.status_code == 400
        assert b"inprocess, pool" in res.body

    asyncio.run(go())
