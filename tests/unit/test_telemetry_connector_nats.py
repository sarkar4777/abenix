"""NATS connector: settings, sign-in options, plain errors, JetStream consumer and acks."""

from __future__ import annotations

import asyncio
import functools
import socket
from types import SimpleNamespace

import pytest

pytest.importorskip("nats")

import nats.errors as NE  # noqa: E402
import nats.js.errors as JE  # noqa: E402
from nats.aio.client import RawCredentials  # noqa: E402
from nats.js.api import DeliverPolicy  # noqa: E402

from app.telemetry.connectors import nats as N  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


CFG = {
    "servers": "nats.abenix-testbed.svc.cluster.local:4222",
    "username": "abenix",
    "subjects": ["fleet.positions.>"],
}


def test_declares_plain_fields():
    d = N.NatsConnector.describe()
    assert d["transport"] == "nats" and d["scale_mode"] == "shared"
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["mode"]["options"] == ["core", "jetstream"]
    for k in ("password", "token", "creds", "nkey_seed", "tls_key"):
        assert keys[k]["kind"] == "secret", k
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


def test_sign_in_options():
    kw = N.connect_kwargs(CFG, {"password": "pw"}, "Fleet")
    assert kw["servers"] == ["nats://nats.abenix-testbed.svc.cluster.local:4222"]
    assert kw["user"] == "abenix" and kw["password"] == "pw"
    kw = N.connect_kwargs(
        {"servers": "tls://n:4222"}, {"creds": "-----BEGIN NATS USER JWT-----"}, "x"
    )
    assert isinstance(kw["user_credentials"], RawCredentials) and "tls" in kw
    kw = N.connect_kwargs(
        {"servers": "n"}, {"nkey_seed": " SUABC \n", "token": "t"}, "x"
    )
    assert kw["nkeys_seed_str"] == "SUABC" and kw["token"] == "t"
    with pytest.raises(ConnectorError, match="server address"):
        N.connect_kwargs({}, {}, "x")


@pytest.mark.parametrize(
    "exc,expect",
    [
        (NE.Error("nats: 'Authorization Violation'"), "refused the credentials"),
        (
            NE.Error(
                'nats: permissions violation for subscription to "fleet.positions.>"'
            ),
            "may not use subject fleet.positions.>",
        ),
        (JE.ServiceUnavailableError(), "JetStream is not turned on"),
        (JE.NotFoundError(), "No JetStream stream holds that subject"),
        (NE.SecureConnRequiredError(), "requires TLS"),
        (
            socket.gaierror(-2, "Name or service not known"),
            "Could not find a host called nats.abenix-testbed",
        ),
        (NE.NoServersError(), "Could not reach NATS"),
    ],
)
def test_errors_in_plain_words(exc, expect):
    assert expect in N.words(exc, CFG)


class FakeJS:
    def __init__(self, have=None):
        self.have = have
        self.added = []

    async def consumer_info(self, stream, durable):
        if self.have is None:
            raise JE.NotFoundError()
        return SimpleNamespace(config=self.have)

    async def add_consumer(self, stream, cfg):
        self.added.append((stream, cfg))


@arun
async def test_durable_consumer_is_created_then_kept():
    js = FakeJS()
    await N.ensure_consumer(
        js,
        "FLEET",
        "abenix-c1",
        ["fleet.positions.>"],
        {"deliver_policy": "all", "ack_wait": "45"},
    )
    stream, cfg = js.added[0]
    assert stream == "FLEET" and cfg.durable_name == "abenix-c1"
    assert (
        cfg.filter_subject == "fleet.positions.>"
        and cfg.deliver_policy == DeliverPolicy.ALL
    )
    assert cfg.ack_wait == 45.0
    same = FakeJS(have=cfg)
    await N.ensure_consumer(same, "FLEET", "abenix-c1", ["fleet.positions.>"], {})
    assert same.added == []
    moved = FakeJS(have=cfg)
    await N.ensure_consumer(
        moved, "FLEET", "abenix-c1", ["fleet.positions.>", "fleet.status.>"], {}
    )
    assert moved.added[0][1].filter_subjects == ["fleet.positions.>", "fleet.status.>"]
    assert moved.added[0][1].deliver_policy == DeliverPolicy.ALL


@arun
async def test_commit_acks_each_jetstream_message():
    acked = []

    class M:
        def __init__(self, i):
            self.i = i

        async def ack(self):
            if self.i == 2:
                raise NE.MsgAlreadyAckdError()
            acked.append(self.i)

    await N.NatsConnector().commit([M(1), None, M(2), M(3)])
    assert acked == [1, 3]


@arun
async def test_core_mode_emits_with_a_queue_group(monkeypatch):
    subs = []

    class FakeNC:
        async def subscribe(self, subject, queue="", cb=None, **kw):
            subs.append((subject, queue))
            await cb(
                SimpleNamespace(
                    subject="fleet.positions.nl.TRK-1",
                    data=b'{"lat":1}',
                    headers={"Nats-Msg-Id": "m1"},
                    reply="",
                )
            )

        async def flush(self, timeout=None):
            return None

        async def close(self):
            return None

    async def fake_connect(**kw):
        return FakeNC()

    monkeypatch.setattr(N.natslib, "connect", fake_connect)
    ctx = RunContext(
        connection_id="c1",
        tenant="t1",
        name="Fleet",
        config=dict(CFG),
        secrets={},
        replica="r1",
        shared=True,
    )
    task = asyncio.create_task(N.NatsConnector().run(ctx))
    for _ in range(100):
        if ctx.queue:
            break
        await asyncio.sleep(0.01)
    env = ctx.queue[0]
    assert subs == [("fleet.positions.>", "abenix-c1")]
    assert env.subject == "fleet.positions.nl.TRK-1" and env.msg_id == "m1"
    assert ctx.status == "connected"
    ctx.stopping.set()
    await asyncio.wait_for(task, 3)


@arun
async def test_no_subjects_is_a_plain_error():
    ctx = RunContext(
        connection_id="c1",
        tenant="t1",
        name="Fleet",
        config={"servers": "n"},
        secrets={},
        replica="r1",
        shared=False,
    )
    task = asyncio.create_task(N.NatsConnector().run(ctx))
    for _ in range(100):
        if ctx.status == "error":
            break
        await asyncio.sleep(0.01)
    assert "Pick at least one subject" in ctx.last_error
    ctx.stopping.set()
    await asyncio.wait_for(task, 3)


@arun
async def test_write_needs_a_subject():
    with pytest.raises(ConnectorError, match="no subject"):
        await N.NatsConnector().write(CFG, {}, {}, 1)


def test_subjects_are_a_list_field():
    keys = {f.key: f for f in N.NatsConnector.config_fields}
    assert keys["subjects"].kind == "list" and keys["subjects"].required
    assert N.servers_of({"servers": ["n1:4222", "tls://n2:4222"]}) == [
        "nats://n1:4222",
        "tls://n2:4222",
    ]
