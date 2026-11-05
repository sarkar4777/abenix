"""What POST /gateways/{id}/deploy promises: deployed only when the gateway said so."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import app.routers.edge as edge

TENANT = uuid.uuid4()
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeDb:
    def __init__(self) -> None:
        self.executed: list = []
        self.agent = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT, slug="pump")

    async def execute(self, stmt):
        self.executed.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.agent)

    async def commit(self) -> None:
        pass


def gateway(endpoint=None, settings=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        gateway_id="gw-1",
        endpoint_url=endpoint,
        deployed_agents=[],
        settings=settings or {},
    )


def run(monkeypatch, g, mqtt, http):
    db = FakeDb()
    pushed: list[tuple] = []
    cleared: list[str] = []

    async def can(*_a):
        return True

    async def gw(*_a):
        return g

    async def compile_bundle(**_k):
        return b"bundle", "digest"

    async def deliver(*_a):
        return mqtt

    async def push(*a):
        pushed.append(a)
        return http

    async def clear(_gw, slug):
        cleared.append(slug)

    monkeypatch.setattr(edge, "_can_manage", can)
    monkeypatch.setattr(edge, "_gateway_or_404", gw)
    monkeypatch.setattr(edge, "compile_agent_bundle", compile_bundle)
    monkeypatch.setattr(edge, "_signing_key_or_503", lambda: KEY)
    monkeypatch.setattr(edge, "_mqtt_deliver", deliver)
    monkeypatch.setattr(edge, "_push_bundle_http", push)
    monkeypatch.setattr(edge, "_mqtt_clear", clear)
    resp = asyncio.run(
        edge.deploy_to_gateway(
            gateway_pk=str(g.id),
            body={"agent_id": str(db.agent.id)},
            db=db,
            user=SimpleNamespace(tenant_id=TENANT),
        )
    )
    body = json.loads(resp.body)
    data = body["data"] or body["error"]["details"]
    return resp.status_code, data, body, pushed, cleared, db


NO_MQTT = {"attempted": False, "published": False, "acked": False}
ACK = {"attempted": True, "published": True, "acked": True, "qos": 1, "retained": True}
PUBLISHED = {"attempted": True, "published": True, "acked": False, "error": None}
NO_HTTP = {"attempted": False, "delivered": False, "status": None, "error": None}


def test_mqtt_confirmed_skips_http(monkeypatch):
    code, d, _, pushed, _, _ = run(monkeypatch, gateway("http://gw:8080"), ACK, NO_HTTP)
    assert code == 200 and d["deployed"] is True and d["delivered_via"] == "mqtt"
    assert d["queued"] is False and d["gateway_reachable"] is True
    assert pushed == []


def test_broker_accepted_alone_is_not_deployed(monkeypatch):
    code, d, _, _, cleared, db = run(monkeypatch, gateway(), PUBLISHED, NO_HTTP)
    assert code == 200
    assert d["deployed"] is False and d["delivered_via"] is None
    assert d["queued"] is True and d["gateway_reachable"] is False
    assert "next connects" in d["message"]
    assert cleared == []
    assert db.executed, "the queued agent is remembered"


def test_unconfirmed_mqtt_falls_back_to_http(monkeypatch):
    http = {"attempted": True, "delivered": True, "status": 200, "error": None}
    code, d, _, pushed, _, _ = run(
        monkeypatch, gateway("http://gw:8080"), PUBLISHED, http
    )
    assert code == 200 and d["deployed"] is True and d["delivered_via"] == "http"
    assert len(pushed) == 1


def test_http_token_is_the_gateways_push_token(monkeypatch):
    http = {"attempted": True, "delivered": True, "status": 200, "error": None}
    g = gateway("http://gw:8080", {"push_token_enc": "plain-when-no-kek"})
    _, _, _, pushed, _, _ = run(monkeypatch, g, NO_MQTT, http)
    assert pushed[0][3] == "plain-when-no-kek"


def test_http_only_gateway_down_says_so(monkeypatch):
    http = {
        "attempted": True,
        "delivered": False,
        "status": None,
        "error": "could not reach http://gw:8080 ConnectError",
    }
    code, d, body, _, _, db = run(monkeypatch, gateway("http://gw:8080"), NO_MQTT, http)
    assert code == 502 and body["error"]["error_code"] == "GATEWAY_UNREACHABLE"
    assert d["deployed"] is False and d["gateway_reachable"] is False
    assert "could not reach" in d["message"]
    assert db.executed == [] or all("UPDATE" not in str(s) for s in db.executed)


def test_nothing_to_try_is_a_clear_error(monkeypatch):
    code, d, body, _, _, _ = run(monkeypatch, gateway(), NO_MQTT, NO_HTTP)
    assert code == 502 and d["deployed"] is False and d["gateway_reachable"] is None
    assert "MQTT_URL" in d["message"] and "endpoint_url" in d["message"]


def test_refusal_over_mqtt_clears_the_retained_bundle(monkeypatch):
    mqtt = {**PUBLISHED, "gateway_error": "bundle tenant_id x does not match"}
    code, d, body, pushed, cleared, _ = run(monkeypatch, gateway(), mqtt, NO_HTTP)
    assert code == 422 and body["error"]["error_code"] == "GATEWAY_REFUSED"
    assert d["deployed"] is False and d["queued"] is False and d["refused"] is True
    assert cleared == ["pump"] and pushed == []


def test_refusal_over_http_clears_the_retained_bundle(monkeypatch):
    http = {"attempted": True, "delivered": False, "status": 400, "error": "tampered"}
    code, d, _, _, cleared, _ = run(
        monkeypatch, gateway("http://gw:8080"), PUBLISHED, http
    )
    assert code == 422 and cleared == ["pump"]
    assert "tampered" in d["message"]


def test_wrong_token_with_a_queued_bundle_keeps_it_queued(monkeypatch):
    http = {
        "attempted": True,
        "delivered": False,
        "status": 401,
        "error": "the gateway refused the token, set push_token",
    }
    code, d, _, _, cleared, _ = run(
        monkeypatch, gateway("http://gw:8080"), PUBLISHED, http
    )
    assert code == 200 and d["queued"] is True and d["deployed"] is False
    assert d["http"]["error"].startswith("the gateway refused the token")
    assert cleared == []


def test_push_bundle_http_sends_the_bearer(monkeypatch):
    import httpx

    seen = {}

    def handler(req):
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(401, json={"error": "unauthorized"})

    real = httpx.AsyncClient

    def client(**kw):
        return real(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(edge.httpx, "AsyncClient", client)
    out = asyncio.run(edge._push_bundle_http("http://gw:8080", "pump", b"x", "tok"))
    assert seen["auth"] == "Bearer tok"
    assert out["status"] == 401 and "push_token" in out["error"]


def test_push_token_never_shows_in_the_gateway_view():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    g = SimpleNamespace(
        id=uuid.uuid4(),
        gateway_id="gw",
        name="n",
        description="",
        endpoint_url=None,
        status="online",
        roles=["agents"],
        deployed_agents=[],
        registered_at=now,
        last_seen_at=now,
        enrolled_at=None,
        enroll_expires_at=None,
        revoked_at=None,
        first_data_at=None,
        version=None,
        platform=None,
        hostname=None,
        config_version=1,
        applied_version=0,
        telemetry_connection_id=None,
        collectors=[],
        health={},
        settings={"push_token_enc": "secret", "heartbeat_s": 5},
    )
    out = edge._serialize_gateway(g, full=True)
    assert "secret" not in json.dumps(out)
    assert out["push_token_set"] is True and out["settings"]["heartbeat_s"] == 5


@pytest.mark.parametrize(
    "fn,want",
    [
        (edge._deploy_topic, "edge/gw/deploy/pump"),
        (edge._ack_topic, "edge/gw/ack/pump"),
    ],
)
def test_topics_match_the_runtimes(fn, want):
    assert fn("gw", "pump") == want


def test_install_commands_carry_the_agent_token():
    from app.services import edge_collectors as EC

    cmds = EC.install("gw", "http://a", "etk_x", [], agent_token="tok123")
    for k in ("docker_run", "compose", "kubernetes", "systemd"):
        assert "EDGE_AUTH_TOKEN" in cmds[k] and "tok123" in cmds[k], k
    plain = EC.install("gw", "http://a", "etk_x", [])
    assert "EDGE_AUTH_TOKEN" not in plain["docker_run"]
