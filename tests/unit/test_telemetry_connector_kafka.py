"""Kafka connector: settings, plain errors, the consume loop and commit after the store flush."""

from __future__ import annotations

import asyncio
import functools
import socket
from types import SimpleNamespace

import pytest

pytest.importorskip("aiokafka")

from aiokafka import TopicPartition  # noqa: E402
from aiokafka import errors as KE  # noqa: E402

from app.telemetry.connectors import kafka as K  # noqa: E402
from app.telemetry.connectors.base import ConnectorError, RunContext  # noqa: E402


def arun(fn):
    """Runs an async test on its own loop, the unit suite has no asyncio plugin config."""

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))

    return wrapper


CFG = {
    "bootstrap_servers": "redpanda.abenix-testbed.svc.cluster.local:9092",
    "security_protocol": "SASL_PLAINTEXT",
    "sasl_mechanism": "SCRAM-SHA-512",
    "username": "abenix",
    "subjects": ["shop.orders"],
}
SECRETS = {"password": "s3cret-pass"}


def ctx(cfg=None, secrets=None, shared=True):
    return RunContext(
        connection_id="c1",
        tenant="t1",
        name="Payments",
        config=dict(cfg or CFG),
        secrets=dict(secrets or SECRETS),
        replica="r1",
        shared=shared,
        queue_max=100,
    )


def test_declares_plain_fields():
    d = K.KafkaConnector.describe()
    assert d["transport"] == "kafka" and d["scale_mode"] == "shared"
    assert d["capabilities"] == {"receive": "subscribe", "write": True}
    keys = {f["key"]: f for f in d["config_fields"]}
    assert keys["bootstrap_servers"]["required"]
    assert keys["password"]["kind"] == "secret" and keys["tls_key"]["kind"] == "secret"
    assert set(keys["sasl_mechanism"]["options"]) == {
        "PLAIN",
        "SCRAM-SHA-256",
        "SCRAM-SHA-512",
        "OAUTHBEARER",
    }
    assert keys["start_from"]["options"] == ["latest", "earliest"]
    for f in d["config_fields"]:
        assert f["label"] and f["description"], f["key"]


def test_client_kwargs_sasl_scram():
    kw = K.client_kwargs(CFG, SECRETS)
    assert kw["bootstrap_servers"] == ["redpanda.abenix-testbed.svc.cluster.local:9092"]
    assert kw["sasl_mechanism"] == "SCRAM-SHA-512"
    assert (
        kw["sasl_plain_username"] == "abenix"
        and kw["sasl_plain_password"] == "s3cret-pass"
    )
    assert "ssl_context" not in kw


def test_client_kwargs_tls_and_oauth():
    kw = K.client_kwargs(
        {
            **CFG,
            "security_protocol": "SASL_SSL",
            "sasl_mechanism": "OAUTHBEARER",
            "tls_verify": "false",
        },
        {"oauth_token": "tok"},
    )
    assert kw["ssl_context"].check_hostname is False
    assert isinstance(kw["sasl_oauth_token_provider"], K.OAuthToken)
    assert asyncio.run(kw["sasl_oauth_token_provider"].token()) == "tok"


def test_client_kwargs_refuses_half_settings():
    with pytest.raises(ConnectorError, match="bootstrap servers"):
        K.client_kwargs({}, {})
    with pytest.raises(ConnectorError, match="user name and password"):
        K.client_kwargs({**CFG, "username": ""}, {})
    with pytest.raises(ConnectorError, match="Security protocol"):
        K.client_kwargs({**CFG, "security_protocol": "SASL"}, {})
    with pytest.raises(ConnectorError, match="both the certificate"):
        K.client_kwargs({**CFG, "security_protocol": "SSL", "tls_cert": "x"}, {})


@pytest.mark.parametrize(
    "exc,expect",
    [
        (
            KE.SaslAuthenticationFailed("bad"),
            "refused the user name or password for SCRAM-SHA-512",
        ),
        (
            KE.UnsupportedSaslMechanismError(),
            "does not offer the SCRAM-SHA-512 sign-in",
        ),
        (KE.TopicAuthorizationFailedError(), "may not read shop.orders"),
        (KE.GroupAuthorizationFailedError(), "consumer group"),
        (KE.UnknownTopicOrPartitionError(), "does not exist"),
        (
            socket.gaierror(11001, "getaddrinfo failed"),
            "Could not find a host called redpanda.abenix-testbed",
        ),
        (ConnectionRefusedError(), "Nothing answered at"),
        (
            KE.KafkaConnectionError("Unable to bootstrap from [('x', 9092)]"),
            "Could not reach Kafka",
        ),
    ],
)
def test_errors_in_plain_words(exc, expect):
    assert expect in K.words(exc, CFG, ["shop.orders"])


def test_topic_globs_become_a_pattern():
    assert K.topic_pattern(["shop.orders"]) is None
    pat = K.topic_pattern(["shop.*", "plant.sensors"])
    import re

    assert re.fullmatch(pat, "shop.refunds") and re.fullmatch(pat, "plant.sensors")
    assert not re.fullmatch(pat, "other")


class FakeConsumer:
    """Stands in for AIOKafkaConsumer: two batches, then nothing."""

    instances: list["FakeConsumer"] = []

    def __init__(self, *topics, **kw):
        self.kw = kw
        self.committed: list[dict] = []
        self.subscribed = None
        self.started = self.stopped = False
        self.batches = [
            {
                TopicPartition("shop.orders", 0): [
                    msg(0, b'{"a":1}'),
                    msg(1, b'{"a":2}'),
                ]
            },
            {TopicPartition("shop.orders", 1): [msg(7, b'{"a":3}', partition=1)]},
        ]
        FakeConsumer.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def topics(self):
        return {"shop.orders", "plant.sensors"}

    def subscribe(self, topics=None, pattern=None):
        self.subscribed = topics or pattern

    def assignment(self):
        return {TopicPartition("shop.orders", 0), TopicPartition("shop.orders", 1)}

    async def getmany(self, timeout_ms=0, max_records=None):
        if self.batches:
            return self.batches.pop(0)
        await asyncio.sleep(timeout_ms / 1000)
        return {}

    async def commit(self, offsets):
        self.committed.append(dict(offsets))


def msg(offset, value, partition=0):
    return SimpleNamespace(
        topic="shop.orders",
        partition=partition,
        offset=offset,
        value=value,
        key=b"ord_1",
        headers=[("ce_type", b"order.created")],
        timestamp=1791720000000,
    )


async def _run_until(c, conn, want):
    task = asyncio.create_task(conn.run(c))
    for _ in range(200):
        if len(c.queue) >= want:
            break
        await asyncio.sleep(0.01)
    return task


@arun
async def test_run_emits_envelopes_and_commits_after_flush(monkeypatch):
    FakeConsumer.instances.clear()
    monkeypatch.setattr(K, "AIOKafkaConsumer", FakeConsumer)
    c = ctx()
    conn = K.KafkaConnector()
    task = await _run_until(c, conn, 3)
    envs = list(c.queue)
    assert [e.msg_id for e in envs] == [
        "shop.orders/0/0",
        "shop.orders/0/1",
        "shop.orders/1/7",
    ]
    assert (
        envs[0].headers["kafka.key"] == "ord_1"
        and envs[0].headers["ce_type"] == "order.created"
    )
    assert c.status == "connected"
    fc = FakeConsumer.instances[0]
    assert fc.kw["group_id"] == "abenix-c1" and fc.kw["enable_auto_commit"] is False
    # the pipeline commits after the store flush, the next offset per partition
    await conn.commit([e.offset_token for e in envs] + [(TopicPartition("gone", 0), 3)])
    assert fc.committed == [
        {TopicPartition("shop.orders", 0): 2, TopicPartition("shop.orders", 1): 8}
    ]
    c.stopping.set()
    await asyncio.wait_for(task, 3)
    assert fc.stopped and c.status == "disabled"


@arun
async def test_missing_topic_is_a_plain_error(monkeypatch):
    monkeypatch.setattr(K, "AIOKafkaConsumer", FakeConsumer)
    c = ctx({**CFG, "subjects": ["shop.nope"]})
    task = asyncio.create_task(K.KafkaConnector().run(c))
    for _ in range(100):
        if c.status == "error":
            break
        await asyncio.sleep(0.01)
    assert c.status == "error" and "shop.nope is not on" in c.last_error
    c.stopping.set()
    await asyncio.wait_for(task, 3)


@arun
async def test_test_reports_bad_settings_without_network():
    out = await K.KafkaConnector().test({}, {})
    assert out["ok"] is False and "bootstrap servers" in out["error"]


@arun
async def test_write_needs_a_topic():
    with pytest.raises(ConnectorError, match="no topic"):
        await K.KafkaConnector().write(CFG, SECRETS, {}, 1)


def test_errors_never_carry_the_password():
    from app.telemetry.connectors import _plain as P

    text = P.scrub(K.words(RuntimeError("auth s3cret-pass failed"), CFG), SECRETS)
    assert "s3cret-pass" not in text


def test_topics_are_a_list_field_and_lists_are_read():
    keys = {f.key: f for f in K.KafkaConnector.config_fields}
    assert keys["subjects"].kind == "list" and keys["subjects"].required
    assert keys["bootstrap_servers"].kind == "list"
    assert K.servers_of({"bootstrap_servers": ["a:9092", " b:9092 "]}) == [
        "a:9092",
        "b:9092",
    ]


def test_plain_sign_in_sends_no_authorization_identity():
    from aiokafka import conn

    assert conn.SaslPlainAuthenticator is K._PlainNoAuthzid
    auth = conn.SaslPlainAuthenticator(
        loop=None, sasl_plain_username="abenix", sasl_plain_password="pw"
    )
    first, _ = next(auth._authenticator)
    assert first == b"\x00abenix\x00pw"


@arun
async def test_a_lost_broker_shows_as_connecting_then_connected(monkeypatch):
    class Client:
        up = True

        async def fetch_all_metadata(self):
            if not self.up:
                raise KE.KafkaError(
                    "Unable to get cluster metadata over all known brokers"
                )
            return object()

    class Watched(FakeConsumer):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._client = Client()
            self._coordinator = SimpleNamespace(coordinator_id=0)

    monkeypatch.setattr(K, "AIOKafkaConsumer", Watched)
    monkeypatch.setattr(K, "HEALTH_EVERY_S", 0.05)
    FakeConsumer.instances.clear()
    c = ctx()
    task = asyncio.create_task(K.KafkaConnector().run(c))

    async def until(cond):
        for _ in range(200):
            if cond():
                return True
            await asyncio.sleep(0.01)
        return False

    assert await until(lambda: c.status == "connected")
    FakeConsumer.instances[0]._client.up = False
    assert await until(lambda: c.status == "connecting")
    assert "Lost the Kafka broker at redpanda.abenix-testbed" in c.last_error
    assert "No messages are lost" in c.last_error
    FakeConsumer.instances[0]._client.up = True
    assert await until(lambda: c.status == "connected")
    assert c.last_error is None
    c.stopping.set()
    await asyncio.wait_for(task, 3)


def test_start_from_help_says_latest_skips_history():
    f = {f.key: f for f in K.KafkaConnector.config_fields}["start_from"]
    assert (
        "latest skips everything sent before" in f.description
        and "earliest" in f.description
    )
