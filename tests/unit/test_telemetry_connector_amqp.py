"""AMQP connector: settings, plain errors, acking after the store flush."""

from __future__ import annotations

import asyncio
import functools
import socket
from types import SimpleNamespace

import pytest

pytest.importorskip("aio_pika")

import aiormq.exceptions as AE  # noqa: E402

from app.telemetry.connectors import amqp as A  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402


def arun(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


CFG = {
    "host": "rabbitmq.abenix-testbed.svc.cluster.local",
    "username": "abenix",
    "mode": "exchange",
    "exchange": "logistics.events",
    "subjects": ["shipment.#"],
}


def test_declares_plain_fields():
    d = A.AmqpConnector.describe()
    assert d["transport"] == "amqp" and d["scale_mode"] == "shared"
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["host"]["required"] and keys["password"]["kind"] == "secret"
    assert keys["mode"]["options"] == ["queue", "exchange"]
    assert keys["prefetch"]["default"] == "500"
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


@pytest.mark.parametrize(
    "exc,expect",
    [
        (
            AE.ProbableAuthenticationError("ACCESS_REFUSED - Login was refused"),
            "refused the user name or password",
        ),
        (
            AE.ConnectionNotAllowed("NOT_ALLOWED - vhost / not found"),
            "may not use virtual host /",
        ),
        (
            AE.ChannelNotFoundEntity("NOT_FOUND - no queue 'orders.in' in vhost '/'"),
            "There is no queue orders.in",
        ),
        (
            AE.ChannelAccessRefused("ACCESS_REFUSED - access to queue 'x' refused"),
            "not allowed to read or configure",
        ),
        (
            AE.ChannelPreconditionFailed(
                "PRECONDITION_FAILED - inequivalent arg 'durable'"
            ),
            "already exists with other settings",
        ),
        (
            AE.InvalidFrameError(
                "Expected one of ['Connection.OpenOk'], got <Connection.Close>"
            ),
            "may not use virtual host",
        ),
        (
            AE.ConnectionInternalError(
                "Feature `transient_nonexcl_queues` is deprecated"
            ),
            "temporary shared queues",
        ),
        (
            socket.gaierror(-2, "Name or service not known"),
            "Could not find a host called rabbitmq.abenix-testbed",
        ),
        (
            ConnectionRefusedError(),
            "Nothing answered at rabbitmq.abenix-testbed.svc.cluster.local:5672",
        ),
        (asyncio.TimeoutError(), "No answer from"),
    ],
)
def test_errors_in_plain_words(exc, expect):
    assert expect in A.words(exc, CFG)


class Msg:
    def __init__(self, channel, tag):
        self.channel = channel
        self.delivery_tag = tag
        self.acked: list[bool] = []

    async def ack(self, multiple=False):
        self.acked.append(multiple)


@arun
async def test_commit_acks_the_newest_per_channel_with_multiple():
    ch1, ch2 = object(), object()
    a, b, c, d = Msg(ch1, 1), Msg(ch1, 2), Msg(ch1, 3), Msg(ch2, 9)
    await A.AmqpConnector().commit([a, b, c, None, d])
    assert c.acked == [True] and d.acked == [True]
    assert a.acked == [] and b.acked == []


@arun
async def test_commit_on_a_closed_channel_is_skipped():
    class Dead(Msg):
        async def ack(self, multiple=False):
            raise AE.ChannelInvalidStateError("closed")

    await A.AmqpConnector().commit([Dead(object(), 4)])


def test_headers_carry_routing_and_properties():
    import datetime as dt

    m = SimpleNamespace(
        headers={"tenant": b"acme"},
        routing_key="shipment.delivered",
        exchange="logistics.events",
        content_type="application/json",
        type="shipment.status",
        app_id="logistics-sim",
        timestamp=dt.datetime(2026, 10, 11, tzinfo=dt.timezone.utc),
        redelivered=True,
    )
    h = A.headers_of(m)
    assert h["tenant"] == "acme" and h["amqp.routing_key"] == "shipment.delivered"
    assert h["amqp.redelivered"] == "true" and h["content-type"] == "application/json"


class FakeChannel:
    def __init__(self, missing=False):
        self.missing = missing
        self.declared = []
        self.bound = []

    async def get_queue(self, name, ensure=True):
        if self.missing:
            raise AE.ChannelNotFoundEntity(
                f"NOT_FOUND - no queue '{name}' in vhost '/'"
            )
        return SimpleNamespace(name=name)

    async def get_exchange(self, name, ensure=True):
        return SimpleNamespace(name=name)

    async def declare_queue(self, name, **kw):
        self.declared.append((name, kw))
        q = SimpleNamespace(name=name)

        async def bind(ex, routing_key=""):
            self.bound.append((ex.name, routing_key))

        q.bind = bind
        return q


@arun
async def test_exchange_mode_binds_a_durable_queue_per_connection():
    ch = FakeChannel()
    q, keys = await A.bind_queue(
        ch, {**CFG, "queue_max_length": "1000"}, ["shipment.#", "parcel.*"], "abenix.c1"
    )
    assert q.name == "abenix.c1"
    name, kw = ch.declared[0]
    assert kw["durable"] is True and kw["arguments"]["x-max-length"] == 1000
    assert ch.bound == [
        ("logistics.events", "shipment.#"),
        ("logistics.events", "parcel.*"),
    ]


@arun
async def test_queue_mode_needs_an_existing_queue():
    with pytest.raises(ConnectorError, match="Enter the queue"):
        await A.bind_queue(FakeChannel(), {"mode": "queue"}, [], "x")
    with pytest.raises(AE.ChannelNotFoundEntity) as ei:
        await A.bind_queue(
            FakeChannel(missing=True), {"mode": "queue", "queue": "orders.in"}, [], "x"
        )
    assert "There is no queue orders.in" in A.words(ei.value, CFG)


@arun
async def test_run_reports_a_refused_password_and_stops_cleanly(monkeypatch):
    async def refuse(*a, **kw):
        raise AE.ProbableAuthenticationError("ACCESS_REFUSED - Login was refused")

    monkeypatch.setattr(A, "connect", refuse)
    ctx = RunContext(
        connection_id="c1",
        tenant="t1",
        name="Shipments",
        config=dict(CFG),
        secrets={"password": "pw-123456"},
        replica="r1",
        shared=True,
    )
    task = asyncio.create_task(A.AmqpConnector().run(ctx))
    for _ in range(100):
        if ctx.status == "error":
            break
        await asyncio.sleep(0.01)
    assert (
        ctx.status == "error" and "refused the user name or password" in ctx.last_error
    )
    ctx.stopping.set()
    await asyncio.wait_for(task, 3)
    assert ctx.status == "disabled"


@arun
async def test_test_without_host_is_plain():
    out = await A.AmqpConnector().test({}, {})
    assert out["ok"] is False and "Enter the broker host" in out["error"]


@arun
async def test_write_needs_a_routing_key():
    with pytest.raises(ConnectorError, match="routing key"):
        await A.AmqpConnector().write(CFG, {}, {"exchange": "x"}, 1)
