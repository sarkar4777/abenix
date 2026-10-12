"""The mqtt connector: declarations, plain errors, write-back and the subscription it makes."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.telemetry import brokers
from app.telemetry.connectors import mqtt as MQ
from app.telemetry.connectors.base import RunContext


def _ctx(cfg, shared=False):
    return RunContext(
        connection_id="c1234567",
        tenant="t1",
        name="Site broker",
        config=cfg,
        secrets={},
        replica="rep-a",
        shared=shared,
    )


def test_declares_its_form():
    d = MQ.MqttConnector.describe()
    keys = {f["key"] for f in d["config_fields"]}
    assert {
        "broker_url",
        "subjects",
        "password",
        "tls_ca",
        "tls_key",
        "qos",
        "protocol_version",
    } <= keys
    kinds = {f["key"]: f["kind"] for f in d["config_fields"]}
    assert kinds["password"] == "secret" and kinds["tls_key"] == "secret"
    assert d["capabilities"] == {"receive": "subscribe", "write": True}
    assert d["default_decoder"] == "sparkplug_b"


def test_a_bad_address_is_said_plainly():
    ctx = _ctx({"broker_url": "http://nope"})

    async def go():
        task = asyncio.create_task(MQ.MqttConnector().run(ctx))
        await asyncio.sleep(0.05)
        ctx.stopping.set()
        await task

    asyncio.run(go())
    assert ctx.status == "error" and "mqtt://" in ctx.last_error


def test_unreachable_broker_test_is_plain():
    out = asyncio.run(
        MQ.MqttConnector().test(
            {"broker_url": "mqtt://127.0.0.1:1", "subjects": ["#"]}, {}
        )
    )
    assert out["ok"] is False and out["subjects_seen"] == []
    assert "Could not reach the broker at 127.0.0.1:1" in out["error"]


def test_write_publishes_through_the_shared_client(monkeypatch):
    pub = AsyncMock()
    monkeypatch.setattr(brokers.publisher, "publish", pub)
    out = asyncio.run(
        MQ.MqttConnector().write(
            {"broker_url": "mqtt://b:1883", "_connection_id": "c1"},
            {"password": "pw"},
            {"topic": "plant/pump1/set", "payload": '{"sp": 5}'},
            5,
        )
    )
    assert out["published"] is True
    args = pub.await_args.args
    assert args[0] == "c1" and args[4] == "plant/pump1/set" and args[5] == b'{"sp": 5}'


def test_write_needs_a_topic():
    from app.telemetry.connectors.base import ConnectorError

    with pytest.raises(ConnectorError):
        asyncio.run(MQ.MqttConnector().write({"broker_url": "mqtt://b"}, {}, {}, 1))


def test_shared_connections_subscribe_with_share(monkeypatch):
    subs = []

    class FakeClient:
        def __init__(self, *a, **k):
            self.on_connect = None

        def username_pw_set(self, *a):
            pass

        def max_inflight_messages_set(self, *a):
            pass

        def max_queued_messages_set(self, *a):
            pass

        def reconnect_delay_set(self, *a):
            pass

        def connect_async(self, *a, **k):
            pass

        def loop_start(self):
            self.on_connect(self, None, None, 0)

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

        def subscribe(self, topic, qos=0):
            subs.append((topic, qos))

    import paho.mqtt.client as pm

    monkeypatch.setattr(pm, "Client", FakeClient)
    ctx = _ctx(
        {
            "broker_url": "mqtt://b:1883",
            "subjects": ["spBv1.0/#", "+/+/can/raw"],
            "qos": "1",
        },
        shared=True,
    )

    async def go():
        task = asyncio.create_task(MQ.MqttConnector().run(ctx))
        await asyncio.sleep(0.05)
        ctx.stopping.set()
        await task

    asyncio.run(go())
    assert subs == [("$share/abenix/spBv1.0/#", 1), ("$share/abenix/+/+/can/raw", 1)]
    assert ctx.status == "connected"
