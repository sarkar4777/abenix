"""http_push: the token, signature, size and type checks, the durable stream and acks after storing."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.routers import telemetry as R
from app.routers import telemetry_streams as RS
from app.telemetry import keys as K
from app.telemetry.connectors import http_push as HP
from app.telemetry.connectors.base import RunContext
from models.telemetry import TelemetryConnection
from telemetry_fakes import FakeRedis

TENANT = uuid.uuid4()


class Result:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0) if self.results else Result()


class Req:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self._body = body
        self.headers = {k.lower(): v for k, v in headers.items()}

    async def body(self):
        return self._body


def _conn(token: str, **kw):
    c = TelemetryConnection(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Payments",
        broker_url="",
        topics=[],
        raw_topics=[],
        transport="http_push",
        enabled=True,
        config={"subject": "payments/orders"},
        secrets={},
        decoder="json",
        ingest_token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    for k, v in kw.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(RS, "redis", lambda: r)
    import app.core.platform_settings as PS

    monkeypatch.setattr(PS, "get_int_setting", AsyncMock(return_value=1024))
    return r


def _post(c, body, headers, subject=None):
    return asyncio.run(
        RS.ingest(c.id, Req(body, headers), subject, FakeSession(Result(c)))
    )


def test_declared_as_shared_push():
    d = HP.HttpPushConnector.describe()
    assert d["capabilities"]["receive"] == "push" and d["scale_mode"] == "shared"
    assert {f["key"]: f["kind"] for f in d["config_fields"]}[
        "signing_secret"
    ] == "secret"


def test_token_is_needed_and_checked(fake):
    c = _conn("tpk_right")
    r = _post(c, b"{}", {})
    assert r.status_code == 401 and "Bearer" in json.loads(r.body)["error"]["message"]
    r = _post(c, b"{}", {"Authorization": "Bearer tpk_wrong"})
    assert (
        r.status_code == 401
        and json.loads(r.body)["error"]["error_code"] == "UNAUTHORIZED"
    )


def test_accepts_into_the_stream_with_202(fake):
    c = _conn("tpk_right")
    r = _post(
        c,
        b'{"amount": 12.5}\n{"amount": 7}\n',
        {
            "Authorization": "Bearer tpk_right",
            "Content-Type": "application/x-ndjson",
            "Idempotency-Key": "abc",
        },
        subject="payments/refunds",
    )
    assert r.status_code == 202
    data = json.loads(r.body)["data"]
    assert data["accepted"] and data["bytes"] == 31
    st = fake.data[K.push_stream(c.id)]
    _, _, fields = st["entries"][0]
    assert fields["subject"] == "payments/refunds" and fields["msg_id"] == "abc"


def test_size_type_and_disabled(fake):
    c = _conn("tpk_x")
    h = {"Authorization": "Bearer tpk_x"}
    assert _post(c, b"x" * 2000, h).status_code == 413
    assert (
        _post(c, b"<a/>", {**h, "Content-Type": "application/xml"}).status_code == 415
    )
    c.enabled = False
    r = _post(c, b"{}", h)
    assert (
        r.status_code == 409 and "turned off" in json.loads(r.body)["error"]["message"]
    )


def test_signature_when_a_secret_is_set(fake):
    c = _conn("tpk_x", secrets={"signing_secret": "s3cret"})
    body = b'{"a": 1}'
    h = {"Authorization": "Bearer tpk_x"}
    r = _post(c, body, h)
    assert (
        r.status_code == 401
        and json.loads(r.body)["error"]["error_code"] == "BAD_SIGNATURE"
    )
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert _post(c, body, {**h, "X-Abenix-Signature": sig}).status_code == 202


def test_connector_reads_the_group_and_acks_after_storing(monkeypatch):
    r = FakeRedis()

    async def go():
        await HP.enqueue(
            r, "c1", b'{"a": 1}', subject="s/x", headers={}, msg_id="m1", t_recv=1.0
        )
        conn = HP.HttpPushConnector()
        conn._r = r
        ctx = RunContext(
            connection_id="c1",
            tenant="t",
            name="p",
            config={},
            secrets={},
            replica="rep",
            shared=True,
        )
        task = asyncio.create_task(conn.run(ctx))
        for _ in range(50):
            if ctx.queue:
                break
            await asyncio.sleep(0.01)
        ctx.stopping.set()
        await asyncio.wait_for(task, 3)
        env = ctx.queue[0]
        assert (
            env.subject == "s/x" and env.payload == b'{"a": 1}' and env.msg_id == "m1"
        )
        stream = r.data[K.push_stream("c1")]
        assert stream["groups"]["ingest"]["pending"]
        await conn.commit([env.offset_token])
        assert not stream["groups"]["ingest"]["pending"] and not stream["entries"]

    asyncio.run(go())


def test_rotating_gives_a_new_token_once(fake, monkeypatch):
    c = _conn("tpk_old")
    monkeypatch.setattr(RS, "log_action", AsyncMock())

    async def has(db, user, cap):
        return True

    monkeypatch.setattr(RS.access, "has", has)
    monkeypatch.setattr(RS, "_conn", AsyncMock(return_value=c))
    db = SimpleNamespace(commit=AsyncMock())
    out = json.loads(
        asyncio.run(
            RS.rotate_token(
                c.id, None, SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT), db
            )
        ).body
    )["data"]
    assert out["ingest_token"].startswith("tpk_")
    assert (
        c.ingest_token_hash == hashlib.sha256(out["ingest_token"].encode()).hexdigest()
    )
    assert R.new_ingest_token()[0] != out["ingest_token"]


def test_gzip_bodies_are_inflated_with_a_hard_cap(fake):
    import gzip

    c = _conn("tpk_x")
    h = {
        "Authorization": "Bearer tpk_x",
        "Content-Encoding": "gzip",
        "Content-Type": "application/json",
    }
    r = _post(c, gzip.compress(b'{"a": 1}'), h)
    assert r.status_code == 202
    _, _, fields = fake.data[K.push_stream(c.id)]["entries"][0]
    import base64

    assert base64.b64decode(fields["payload"]) == b'{"a": 1}'
    # a bomb: 50 MB of zeros squeezed under the 1 KB compressed cap
    bomb = gzip.compress(b"0" * 50_000_000, compresslevel=9)
    assert len(bomb) < 60_000
    r = _post(c, bomb[:1000], h)
    assert r.status_code in (400, 413)
    with pytest.raises(OverflowError):
        RS.inflate(bomb, 1024)
    big = _post(c, gzip.compress(b"[" + b"1," * 2000 + b"1]"), h)
    assert (
        big.status_code == 413
        and "after decompression" in json.loads(big.body)["error"]["message"]
    )
    bad = _post(c, bytes([0x1F, 0x8B]) + b"not really gzip", h)
    assert (
        bad.status_code == 400
        and json.loads(bad.body)["error"]["error_code"] == "BAD_ENCODING"
    )
    other = _post(c, b"{}", {**h, "Content-Encoding": "br"})
    assert other.status_code == 415


def test_a_full_backlog_answers_503_and_keeps_nothing(fake, monkeypatch):
    c = _conn("tpk_x")
    monkeypatch.setattr(HP, "BACKLOG_MAX", 2)
    h = {"Authorization": "Bearer tpk_x"}
    assert _post(c, b"{}", h).status_code == 202
    assert _post(c, b"{}", h).status_code == 202
    r = _post(c, b"{}", h)
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert json.loads(r.body)["error"]["error_code"] == "BACKLOG_FULL"
