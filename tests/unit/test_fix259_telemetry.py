"""2.5.9: testbed sign-ins, capture reasons, server-side test message, edge install defaults."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import telemetry_streams as RS
from app.routers import telemetry_testbed as TB
from app.services import edge_collectors as EC
from app.telemetry import access, reads
from app.telemetry import test_message as TM
from models.telemetry import TelemetryConnection
from telemetry_fakes import FakeRedis

T = str(uuid.uuid4())


def _conn(mapping=None, transport="http_push", decoder="json", enabled=True):
    return TelemetryConnection(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(T),
        name="Weather",
        broker_url="",
        topics=[],
        raw_topics=[],
        transport=transport,
        decoder=decoder,
        decoder_config={},
        config={},
        secrets={},
        enabled=enabled,
        shared_subscription=False,
        strict=False,
        mapping=mapping or {},
        team_id=None,
    )


def _body(resp):
    return json.loads(resp.body)


# W1


def test_testbed_services_carry_their_sign_in():
    services = [
        {
            "name": "Kafka (Redpanda)",
            "transport": "kafka",
            "address": "redpanda:9092",
            "reachable": True,
        },
        {
            "name": "Modbus",
            "transport": "modbus_tcp",
            "address": "meter:502",
            "reachable": True,
        },
        {"name": "MQTT", "transport": "mqtt", "address": "x:1883", "reachable": False},
    ]
    sources = [
        {
            "transport": "kafka",
            "config": {
                "bootstrap_servers": "redpanda:9092",
                "security_protocol": "SASL_PLAINTEXT",
                "sasl_mechanism": "SCRAM-SHA-256",
                "username": "abenix",
            },
            "secrets": {"password": "pw"},
            "subjects": ["shop.orders"],
            "decoder": "json",
        },
        {
            "transport": "kafka",
            "config": {"username": "other"},
            "secrets": {"password": "no"},
        },
        {
            "transport": "modbus_tcp",
            "config": {"host": "meter", "port": 502},
            "secrets": {},
            "decoder": "values",
        },
    ]
    out = TB.with_details(services, sources)
    k = out[0]
    assert (
        k["config"]["sasl_mechanism"] == "SCRAM-SHA-256"
        and k["config"]["username"] == "abenix"
    )
    assert k["secrets"] == {"password": "pw"} and k["subjects"] == ["shop.orders"]
    assert k["address"] == "redpanda:9092" and k["decoder"] == "json"
    assert out[1]["config"]["port"] == 502 and out[1]["secrets"] == {}
    assert out[2]["config"] == {} and "subjects" not in out[2]


def _status_user(role):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(T),
        role=SimpleNamespace(value=role),
        is_admin=False,
    )


@pytest.mark.parametrize("role,shown", [("admin", True), ("user", False)])
def test_testbed_sign_ins_are_for_admins_only(monkeypatch, role, shown):
    monkeypatch.setattr(
        TB,
        "probe",
        AsyncMock(
            return_value=[
                {
                    "name": "Kafka",
                    "transport": "kafka",
                    "address": "a:1",
                    "reachable": True,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        TB,
        "fetch_sources",
        AsyncMock(
            return_value=[
                {
                    "transport": "kafka",
                    "config": {"username": "abenix"},
                    "secrets": {"password": "pw"},
                }
            ]
        ),
    )
    monkeypatch.setattr(TB, "_testbed_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(access, "has", AsyncMock(return_value=True))
    data = _body(asyncio.run(TB.testbed_status(_status_user(role), None)))["data"]
    assert data["installed"] is True
    assert ("secrets" in data["services"][0]) is shown


# W2


@pytest.mark.parametrize(
    "status,code,http",
    [
        ({"status": "disabled"}, "SOURCE_OFF", 409),
        (
            {
                "status": "error",
                "last_error": "SASL authentication failed for user abenix",
            },
            "SIGN_IN_FAILED",
            408,
        ),
        (
            {"status": "error", "last_error": "connection refused"},
            "CANNOT_CONNECT",
            408,
        ),
        ({"status": "connecting", "last_error": None}, "CANNOT_CONNECT", 408),
        ({"status": "connected"}, "NOTHING_ARRIVED", 408),
        (None, "NOTHING_ARRIVED", 408),
    ],
)
def test_capture_says_why_nothing_came(status, code, http):
    resp = RS.capture_refusal(status, 20)
    err = _body(resp)["error"]
    assert resp.status_code == http and err["error_code"] == code
    assert err["message"] and ".." not in err["message"]


def test_capture_gives_up_at_its_limit_with_the_reason(monkeypatch):
    c = _conn(transport="kafka")
    r = FakeRedis()
    monkeypatch.setattr(RS, "redis", lambda: r)
    monkeypatch.setattr(
        reads,
        "connection_status",
        AsyncMock(return_value={str(c.id): {"status": "connected"}}),
    )
    row = {"tenant": T, "id": str(c.id)}
    doc, refused = asyncio.run(RS.capture_next(c, row, wait_s=0.3))
    assert doc is None and _body(refused)["error"]["error_code"] == "NOTHING_ARRIVED"


def test_capture_stops_at_once_for_a_source_that_is_off(monkeypatch):
    c = _conn(transport="kafka")
    monkeypatch.setattr(RS, "redis", lambda: FakeRedis())
    monkeypatch.setattr(
        reads,
        "connection_status",
        AsyncMock(return_value={str(c.id): {"status": "disabled"}}),
    )
    doc, refused = asyncio.run(
        RS.capture_next(c, {"tenant": T, "id": str(c.id)}, wait_s=10)
    )
    assert _body(refused)["error"]["error_code"] == "SOURCE_OFF"


def test_capture_route_waits_twenty_seconds():
    assert RS.CAPTURE_WAIT_S == 20.0


# W4


WEATHER = {
    "group": "weather",
    "node": "$.station",
    "device": "",
    "timestamp": {"path": "$.ts", "format": "iso"},
    "signals": {"exclude": ["station", "ts"], "units": {"temperature_c": "C"}},
}


def test_sample_follows_the_mapping():
    doc = TM.sample_doc(WEATHER)
    assert (
        doc["station"] == "test-asset"
        and "T" in doc["ts"]
        and doc["value"] == TM.TEST_VALUE
    )
    nested = TM.sample_doc(
        {
            "node": "{$.machine.id}",
            "records": "$.items",
            "signals": {"include": ["rpm"]},
        }
    )
    assert (
        nested["items"][0]["machine"]["id"] == "test-asset"
        and nested["items"][0]["rpm"] == TM.TEST_VALUE
    )
    raw, ctype = TM.encode(TM.sample_doc({}), "csv")
    assert ctype == "text/csv" and raw.decode().splitlines()[0]


def _setup_push(monkeypatch, c):
    r = FakeRedis()
    monkeypatch.setattr(RS, "redis", lambda: r)
    monkeypatch.setattr(RS, "_conn", AsyncMock(return_value=c))
    monkeypatch.setattr(RS, "log_action", AsyncMock())
    monkeypatch.setattr(access, "has", AsyncMock(return_value=True))
    queued = AsyncMock(return_value="1-0")
    monkeypatch.setattr(RS.http_push, "enqueue", queued)
    return queued


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.UUID(T))


def test_test_message_lands_as_an_asset(monkeypatch):
    c = _conn(WEATHER, decoder="json_lines")
    queued = _setup_push(monkeypatch, c)
    db = SimpleNamespace(commit=AsyncMock())
    data = _body(
        asyncio.run(RS.send_test_message(c.id, SimpleNamespace(), _user(), db))
    )["data"]
    assert data["stored"] is True
    assert (
        data["group"] == "weather"
        and data["node"] == "test-asset"
        and data["device"] is None
    )
    assert "Assets" in data["message"]
    queued.assert_awaited_once()
    assert queued.await_args.kwargs["headers"]["content-type"] == "application/x-ndjson"


def test_test_message_on_a_mapping_miss_says_why(monkeypatch):
    c = _conn({"group": "x", "node": "{subject.4}"})
    queued = _setup_push(monkeypatch, c)
    data = _body(
        asyncio.run(
            RS.send_test_message(c.id, SimpleNamespace(), _user(), SimpleNamespace())
        )
    )["data"]
    assert data["stored"] is False and "mapping" in data["message"]
    queued.assert_not_awaited()


def test_test_message_refuses_off_and_non_push_sources(monkeypatch):
    c = _conn(enabled=False)
    _setup_push(monkeypatch, c)
    resp = asyncio.run(
        RS.send_test_message(c.id, SimpleNamespace(), _user(), SimpleNamespace())
    )
    assert (
        resp.status_code == 409 and _body(resp)["error"]["error_code"] == "SOURCE_OFF"
    )
    k = _conn(transport="kafka")
    monkeypatch.setattr(RS, "_conn", AsyncMock(return_value=k))
    resp = asyncio.run(
        RS.send_test_message(k.id, SimpleNamespace(), _user(), SimpleNamespace())
    )
    assert _body(resp)["error"]["error_code"] == "NOT_PUSH"


# gap 12


def test_edge_images_match_on_every_page(monkeypatch):
    monkeypatch.delenv("EDGE_COLLECTOR_IMAGE", raising=False)
    monkeypatch.setenv(
        "ML_MODEL_SERVING_IMAGE", "localhost:5000/abenix/model-serving:latest"
    )
    monkeypatch.setenv("EDGE_IMAGE_TAG", "2.5.9")
    from app.routers import edge

    variants = _body(asyncio.run(edge.runtime_download()))["data"]["variants"]
    assert (
        variants[0]["image"] == EC.image() == "localhost:5000/abenix/edge-runtime:2.5.9"
    )
    assert variants[1]["image"] == "localhost:5000/abenix/edge-runtime-rust:2.5.9"
    for v in variants:
        assert v["docker_run"].endswith(v["image"]) and "agentforge/" not in json.dumps(
            v
        )


def test_edge_address_prefers_the_setting_then_the_request_host(monkeypatch):
    monkeypatch.delenv("PUBLIC_API_BASE_URL", raising=False)
    monkeypatch.setenv("INTERNAL_API_URL", "http://abenix-api:8000")
    urls = EC.platform_urls("https://abenix.example.com/", "http://localhost:3000")
    assert [u["url"] for u in urls] == [
        "https://abenix.example.com",
        "http://localhost:3000",
        "http://abenix-api:8000",
    ]
    assert EC.platform_urls("", "")[0]["url"] == "http://abenix-api:8000"
    from app.routers import edge

    req = SimpleNamespace(
        headers={"x-forwarded-host": "abenix.acme.io", "x-forwarded-proto": "https"},
        url=SimpleNamespace(scheme="http"),
    )
    assert edge.request_base(req) == "https://abenix.acme.io"
    req = SimpleNamespace(
        headers={"host": "localhost:8000"}, url=SimpleNamespace(scheme="http")
    )
    assert edge.request_base(req) == "http://localhost:8000"


def test_public_api_url_is_a_setting():
    from app.core import platform_settings as ps

    assert "platform.public_api_url" in ps.DEFAULTS


# gap 11


def test_replayed_letters_count_as_stored():
    counts = {"received": 5, "stored": 0, "dlq": 5, "mapping_failed": 5}
    out = reads.with_replayed(counts, {"stored": "5"})
    assert out["stored"] == 5 and out["dlq"] == 0 and out["mapping_failed"] == 0
    assert out["replayed"] == 5
    assert reads.with_replayed(counts, {}) is counts
    assert (
        reads.diagnose(True, {"status": "connected", "pipeline": out}, ["x"])["state"]
        == "ok"
    )


def test_connection_status_folds_in_a_replay():
    from app.telemetry import keys as K

    r = FakeRedis()
    c = _conn(transport="kafka")

    async def go():
        import time as _t

        await r.zadd(K.REPLICAS, {"rep-1": int(_t.time() * 1000)})
        await r.hset(
            K.conn_status(c.id),
            "rep-1",
            json.dumps(
                {
                    "at": int(_t.time() * 1000),
                    "status": "connected",
                    "pipeline": {"received": 3, "dlq": 3},
                }
            ),
        )
        await r.hincrby(K.conn_replayed(c.id), "stored", 3)
        return await reads.connection_status(
            r, [c], replicas=[{"replica": "rep-1", "pool": "default"}]
        )

    st = asyncio.run(go())[str(c.id)]
    assert st["pipeline"]["stored"] == 3 and st["pipeline"]["dlq"] == 0


# polish


def test_old_token_points_to_the_right_place():
    assert "Endpoint and token" in RS.old_token_words("tpk_abc")
    assert "Device keys" in RS.old_token_words("tdk_abc")


def test_one_message_is_singular():
    st = {"status": "connected", "pipeline": {"received": 1, "stored": 1}}
    assert reads.diagnose(True, st, ["x"])["message"] == "1 message stored."
    st["pipeline"] = {"received": 2, "stored": 2}
    assert reads.diagnose(True, st, ["x"])["message"] == "2 messages stored."


def test_source_kinds_come_in_a_sensible_order():
    from app.telemetry import registry

    names = [t["transport"] for t in registry.catalogue()["transports"]]
    assert names[:3] == ["mqtt", "http_push", "kafka"]
    assert names.index("opcua") < names.index("websocket")
