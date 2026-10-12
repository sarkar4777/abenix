"""Kafka topics: Apache Kafka, Redpanda, Confluent Cloud and Azure Event Hubs' Kafka endpoint."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka import conn as _kconn
from aiokafka import errors as KE
from aiokafka.abc import AbstractTokenProvider

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)


class _PlainNoAuthzid(_kconn.SaslPlainAuthenticator):
    # aiokafka sends the user as authzid too, which Redpanda refuses, an empty one is what RFC 4616 expects
    def authenticator_plain(self):
        data = "\0".join(["", self._sasl_plain_username, self._sasl_plain_password])
        resp = yield data.encode("utf-8"), True
        assert resp == b"", "Server should either close or send an empty response"


_kconn.SaslPlainAuthenticator = _PlainNoAuthzid

PROTOCOLS = ("PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL")
MECHANISMS = ("PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512", "OAUTHBEARER")


class OAuthToken(AbstractTokenProvider):
    """OAUTHBEARER through the client credentials grant, or a fixed token."""

    def __init__(self, cfg: dict[str, Any], secrets: dict[str, Any]) -> None:
        self.url = (cfg.get("oauth_token_url") or "").strip()
        self.client_id = (cfg.get("oauth_client_id") or "").strip()
        self.scope = (cfg.get("oauth_scope") or "").strip()
        self.secret = secrets.get("oauth_client_secret") or ""
        self.fixed = secrets.get("oauth_token") or ""
        self._token = ""
        self._until = 0.0

    async def token(self) -> str:
        if self.fixed:
            return self.fixed
        if self._token and time.time() < self._until:
            return self._token
        if not (self.url and self.client_id and self.secret):
            raise ConnectorError(
                "OAUTHBEARER needs a token, or a token URL with a client id and secret"
            )
        import httpx

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.secret,
        }
        if self.scope:
            data["scope"] = self.scope
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.post(self.url, data=data)
        if r.status_code >= 400:
            raise ConnectorError(
                f"The token service at {self.url} refused the client id or secret ({r.status_code})"
            )
        body = r.json()
        self._token = body.get("access_token") or ""
        self._until = time.time() + max(30, int(body.get("expires_in") or 300) - 60)
        return self._token


def servers_of(cfg: dict[str, Any]) -> list[str]:
    out = P.subjects_of(cfg, "bootstrap_servers")
    if not out:
        raise ConnectorError(
            "Enter the bootstrap servers, for example redpanda.abenix-testbed.svc.cluster.local:9092"
        )
    return out


def client_kwargs(cfg: dict[str, Any], secrets: dict[str, Any]) -> dict[str, Any]:
    proto = (cfg.get("security_protocol") or "PLAINTEXT").upper()
    if proto not in PROTOCOLS:
        raise ConnectorError(f"Security protocol must be one of {', '.join(PROTOCOLS)}")
    kw: dict[str, Any] = {
        "bootstrap_servers": servers_of(cfg),
        "client_id": (cfg.get("client_id") or "abenix").strip(),
        "security_protocol": proto,
        "request_timeout_ms": 30000,
        "retry_backoff_ms": 250,
    }
    if proto in ("SSL", "SASL_SSL"):
        kw["ssl_context"] = P.ssl_context(cfg, secrets)
    if proto.startswith("SASL"):
        mech = (cfg.get("sasl_mechanism") or "PLAIN").upper()
        if mech not in MECHANISMS:
            raise ConnectorError(
                f"SASL mechanism must be one of {', '.join(MECHANISMS)}"
            )
        kw["sasl_mechanism"] = mech
        if mech == "OAUTHBEARER":
            kw["sasl_oauth_token_provider"] = OAuthToken(cfg, secrets)
        else:
            user = (cfg.get("username") or "").strip()
            if not user:
                raise ConnectorError(f"{mech} needs a user name and password")
            kw["sasl_plain_username"] = user
            kw["sasl_plain_password"] = secrets.get("password") or ""
    return kw


class Heard(logging.Handler):
    """aiokafka logs why a bootstrap failed but raises only 'Unable to bootstrap', so keep what it said."""

    def __init__(self, servers: list[str]) -> None:
        super().__init__(logging.DEBUG)
        self.servers = servers
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if any(s in msg for s in self.servers) and len(self.lines) < 20:
            self.lines.append(msg)


@contextmanager
def heard(cfg: dict[str, Any]) -> Iterator[Heard]:
    try:
        servers = servers_of(cfg)
    except ConnectorError:
        servers = []
    h = Heard(servers)
    lg = logging.getLogger("aiokafka")
    lg.addHandler(h)
    try:
        yield h
    finally:
        lg.removeHandler(h)


def missing_words(missing: list[str], cfg: dict[str, Any]) -> str:
    return (
        f"Topic {', '.join(missing)} is not on {', '.join(servers_of(cfg))}, or this user may not see it. "
        "Check the name, or ask the Kafka admin to allow DESCRIBE and READ on it."
    )


def words(
    exc: BaseException,
    cfg: dict[str, Any],
    topics: list[str] | None = None,
    said: list[str] | None = None,
) -> str:
    where = (
        ", ".join(servers_of(cfg)) if cfg.get("bootstrap_servers") else "the cluster"
    )
    mech = (cfg.get("sasl_mechanism") or "PLAIN").upper()
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
        if isinstance(
            e,
            (
                KE.SaslAuthenticationFailed,
                KE.AuthenticationFailedError,
                KE.IllegalSaslStateError,
            ),
        ):
            return (
                f"Kafka at {where} refused the user name or password for {mech}. "
                "Check both, and that the mechanism matches the one the user was created with."
            )
        if isinstance(
            e, (KE.UnsupportedSaslMechanismError, KE.AuthenticationMethodNotSupported)
        ):
            return f"Kafka at {where} does not offer the {mech} sign-in. Pick another SASL mechanism."
        if isinstance(e, KE.TopicAuthorizationFailedError):
            return (
                f"This user may not read {', '.join(topics or []) or 'that topic'}. "
                "Ask the Kafka admin to allow READ and DESCRIBE on it."
            )
        if isinstance(e, KE.GroupAuthorizationFailedError):
            return (
                f"This user may not use consumer group {cfg.get('group_id') or 'abenix-...'}. "
                "Ask the Kafka admin to allow READ on the group."
            )
        if isinstance(e, KE.ClusterAuthorizationFailedError):
            return "This user is not allowed on the cluster. Ask the Kafka admin for access."
        if isinstance(e, (KE.UnknownTopicOrPartitionError, KE.InvalidTopicError)):
            return f"Topic {', '.join(topics or []) or ''} does not exist on {where}. Check the name or create it."
    text = " ".join(said or [])
    if (
        "SaslAuthenticationFailed" in text
        or "Invalid credentials" in text
        or "Authentication failed" in text
    ):
        return (
            f"Kafka at {where} refused the user name or password for {mech}. "
            "Check both, and that the mechanism matches the one the user was created with."
        )
    if "UnsupportedSaslMechanism" in text:
        return f"Kafka at {where} does not offer the {mech} sign-in. Pick another SASL mechanism."
    if "SSL" in text or "certificate" in text:
        return (
            f"The secure connection to Kafka at {where} failed. Check that the listener uses TLS, "
            "and add its CA certificate if it is private."
        )
    net = P.network_words(
        exc,
        servers_of(cfg)[0] if cfg.get("bootstrap_servers") else where,
        "Kafka broker",
    )
    if net:
        return net
    text = str(exc)
    if "Unable to bootstrap" in text or isinstance(exc, KE.KafkaConnectionError):
        return (
            f"Could not reach Kafka at {where}. Check the address, the port, and that the security "
            "protocol matches the listener (plain, TLS or SASL)."
        )
    if isinstance(
        exc, (asyncio.TimeoutError, KE.KafkaTimeoutError, KE.RequestTimedOutError)
    ):
        return f"Kafka at {where} did not answer in time. Check the address and the security protocol."
    return f"Kafka at {where} failed: {type(exc).__name__}: {text}"[:500]


async def explain(
    exc: BaseException,
    cfg: dict[str, Any],
    topics: list[str] | None = None,
    said: list[str] | None = None,
) -> str:
    """words(), sharpened with a TCP probe when the client only says it could not bootstrap."""
    text = words(exc, cfg, topics, said)
    if (
        text.startswith("Could not reach Kafka")
        or text.startswith("Kafka at")
        and "did not answer" in text
    ):
        host, port = P.host_port(servers_of(cfg)[0], 9092)
        probed = await P.probe_tcp(host, port, "Kafka broker")
        if probed:
            return probed
    return text


def topic_pattern(topics: list[str]) -> str | None:
    if not any(ch in t for t in topics for ch in "*?["):
        return None
    return "|".join(f"(?:{fnmatch.translate(t)})" for t in topics)


def headers_of(msg: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in msg.headers or ():
        out[str(k)] = (
            v.decode("utf-8", errors="replace")
            if isinstance(v, (bytes, bytearray))
            else str(v)
        )
    if msg.key is not None:
        out["kafka.key"] = msg.key.decode("utf-8", errors="replace")
    out["kafka.partition"] = str(msg.partition)
    out["kafka.offset"] = str(msg.offset)
    if msg.timestamp is not None and msg.timestamp >= 0:
        out["kafka.timestamp"] = str(msg.timestamp)
    return out


HEALTH_EVERY_S = 5.0


def lost_words(cfg: dict[str, Any]) -> str:
    return (
        f"Lost the Kafka broker at {', '.join(servers_of(cfg))}, reconnecting. "
        "No messages are lost, the group resumes from its last commit."
    )


async def broker_ok(consumer: Any) -> bool:
    """A metadata round trip and a known group coordinator. aiokafka itself reconnects without a word."""
    try:
        await asyncio.wait_for(consumer._client.fetch_all_metadata(), HEALTH_EVERY_S)
    except Exception:  # noqa: BLE001
        return False
    coord = getattr(consumer, "_coordinator", None)
    return getattr(coord, "coordinator_id", 0) is not None


async def watch_broker(
    ctx: RunContext, consumer: Any, cfg: dict[str, Any], sup: P.Supervisor
) -> None:
    """Shows a lost broker as connecting and back as connected, while the client reconnects."""
    lost = False
    while True:
        await asyncio.sleep(HEALTH_EVERY_S)
        ok = await broker_ok(consumer)
        if not ok and not lost:
            lost = True
            ctx.set_status("connecting", lost_words(cfg))
            logger.warning("telemetry kafka %s: broker lost", ctx.connection_id)
        elif ok and lost:
            lost = False
            sup.connected()


class KafkaConnector(SourceConnector):
    transport = "kafka"
    label = "Kafka"
    description = (
        "Topics on Apache Kafka, Redpanda, Confluent Cloud or Azure Event Hubs. Every ingest replica "
        "joins one consumer group, and offsets are committed only after the records are stored."
    )
    config_fields = (
        ConfigField(
            "bootstrap_servers",
            "Bootstrap servers",
            kind="list",
            required=True,
            group="Connection",
            description="host:port of one or more brokers, comma separated. Example: redpanda.abenix-testbed.svc.cluster.local:9092. Event Hubs: <namespace>.servicebus.windows.net:9093",
        ),
        ConfigField(
            "subjects",
            "Topics",
            kind="list",
            required=True,
            group="Connection",
            description="The topics to read, comma or newline separated. * matches any part of a name. Example: shop.orders, plant.*",
        ),
        ConfigField(
            "security_protocol",
            "Security",
            kind="select",
            group="Connection",
            default="PLAINTEXT",
            options=PROTOCOLS,
            description="PLAINTEXT for none, SSL for TLS, SASL_PLAINTEXT for a password without TLS, SASL_SSL for both. Confluent Cloud and Event Hubs use SASL_SSL.",
        ),
        ConfigField(
            "sasl_mechanism",
            "Sign-in method",
            kind="select",
            group="Sign in",
            default="PLAIN",
            options=MECHANISMS,
            description="How the user signs in when Security is SASL. Event Hubs uses PLAIN with user name $ConnectionString and the connection string as password.",
        ),
        ConfigField(
            "username",
            "User name",
            kind="string",
            group="Sign in",
            description="The SASL user. Leave empty for PLAINTEXT or SSL. Example: abenix",
        ),
        ConfigField(
            "password",
            "Password",
            kind="secret",
            group="Sign in",
            description="The SASL password. Stored encrypted and never shown again.",
        ),
        ConfigField(
            "oauth_token_url",
            "OAuth token URL",
            kind="url",
            group="Sign in",
            description="For OAUTHBEARER: the token endpoint for the client credentials grant. Example: https://login.example.com/oauth2/token",
        ),
        ConfigField(
            "oauth_client_id",
            "OAuth client id",
            kind="string",
            group="Sign in",
            description="For OAUTHBEARER with a token URL. Example: abenix-ingest",
        ),
        ConfigField(
            "oauth_client_secret",
            "OAuth client secret",
            kind="secret",
            group="Sign in",
            description="For OAUTHBEARER with a token URL. Stored encrypted.",
        ),
        ConfigField(
            "oauth_scope",
            "OAuth scope",
            kind="string",
            group="Sign in",
            description="For OAUTHBEARER, when the token service asks for one. Example: kafka",
        ),
        ConfigField(
            "oauth_token",
            "OAuth token",
            kind="secret",
            group="Sign in",
            description="For OAUTHBEARER without a token URL: a fixed bearer token.",
        ),
        ConfigField(
            "tls_ca",
            "CA certificate",
            kind="string",
            group="TLS",
            description="PEM text of the CA that signed the brokers' certificates. Leave empty to trust the public CAs. Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "tls_cert",
            "Client certificate",
            kind="string",
            group="TLS",
            description="PEM text, for brokers that ask for a client certificate (mTLS). Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "tls_key",
            "Client key",
            kind="secret",
            group="TLS",
            description="PEM private key for the client certificate. Stored encrypted. Example: -----BEGIN PRIVATE KEY----- ...",
        ),
        ConfigField(
            "tls_verify",
            "Check the broker's certificate",
            kind="bool",
            group="TLS",
            default="true",
            description="Turn off only for a test cluster with a self-signed certificate.",
        ),
        ConfigField(
            "group_id",
            "Consumer group",
            kind="string",
            group="Reading",
            description="Leave empty to use abenix-<connection id>, which every ingest replica joins. Use your own when the Kafka admin grants a named group. Example: abenix-payments",
        ),
        ConfigField(
            "start_from",
            "Start from",
            kind="select",
            group="Reading",
            default="latest",
            options=("latest", "earliest"),
            description="Where a new consumer group starts. latest skips everything sent before this source first connects, pick earliest to read the history still kept on the topic. Later runs always continue from the last commit.",
        ),
        ConfigField(
            "max_poll_records",
            "Batch size",
            kind="int",
            group="Reading",
            default="500",
            description="Most messages fetched at once. Lower it for very large messages.",
        ),
        ConfigField(
            "client_id",
            "Client id",
            kind="string",
            group="Reading",
            default="abenix",
            description="Shown in the broker's logs and quotas. Example: abenix-plant-a",
        ),
    )
    capabilities = {"receive": "subscribe", "write": True}
    scale_mode = "shared"
    default_decoder = "json"

    def __init__(self) -> None:
        self._consumer: AIOKafkaConsumer | None = None

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        topics = P.subjects_of(cfg)
        sup = P.Supervisor(ctx, lambda e: words(e, cfg, topics), "kafka")

        async def once() -> None:
            if not topics:
                raise ConnectorError("Pick at least one topic to read")
            group = (cfg.get("group_id") or "").strip() or f"abenix-{ctx.connection_id}"
            consumer = AIOKafkaConsumer(
                group_id=group,
                enable_auto_commit=False,
                auto_offset_reset=(cfg.get("start_from") or "latest"),
                max_poll_records=P.as_int(cfg, "max_poll_records", 500),
                session_timeout_ms=30000,
                heartbeat_interval_ms=3000,
                **client_kwargs(cfg, secrets),
            )
            try:
                with heard(cfg) as h:
                    try:
                        await consumer.start()
                    except Exception as exc:  # noqa: BLE001
                        raise ConnectorError(
                            await explain(exc, cfg, topics, h.lines)
                        ) from exc
                pattern = topic_pattern(topics)
                if pattern:
                    consumer.subscribe(pattern=pattern)
                else:
                    have = await consumer.topics()
                    missing = [t for t in topics if t not in have]
                    if missing:
                        raise ConnectorError(missing_words(missing, cfg))
                    consumer.subscribe(topics)
                self._consumer = consumer
                sup.connected()

                async def consume() -> None:
                    while True:
                        batch = await consumer.getmany(timeout_ms=500)
                        for tp, msgs in batch.items():
                            for m in msgs:
                                await ctx.emit(
                                    Envelope(
                                        connection_id=ctx.connection_id,
                                        tenant=ctx.tenant,
                                        subject=m.topic,
                                        payload=m.value or b"",
                                        headers=headers_of(m),
                                        t_recv=time.time(),
                                        msg_id=f"{m.topic}/{m.partition}/{m.offset}",
                                        offset_token=(tp, m.offset),
                                    )
                                )

                await P.until_stopped(
                    ctx, consume(), watch_broker(ctx, consumer, cfg, sup)
                )
            finally:
                self._consumer = None
                try:
                    await asyncio.wait_for(consumer.stop(), 10)
                except Exception:  # noqa: BLE001
                    pass

        await sup.run(once)

    async def commit(self, tokens: list[Any]) -> None:
        consumer = self._consumer
        if consumer is None or not tokens:
            return
        mine = consumer.assignment()
        offsets: dict[TopicPartition, int] = {}
        for tok in tokens:
            if not tok:
                continue
            tp, off = tok
            if tp in mine and off + 1 > offsets.get(tp, -1):
                offsets[tp] = off + 1
        if not offsets:
            return
        try:
            await consumer.commit(offsets)
        except (KE.CommitFailedError, KE.IllegalStateError, KE.KafkaError) as exc:
            # a rebalance moved the partition, the new owner reads it again and duplicates are dropped by msg_id
            logger.info(
                "kafka commit skipped after a rebalance: %s", type(exc).__name__
            )

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 5.0
        topics = P.subjects_of(cfg)
        out = P.result()
        try:
            kw = client_kwargs(cfg, secrets)
        except ConnectorError as exc:
            out["error"] = str(exc)
            return out
        kw["request_timeout_ms"] = 4500
        consumer = AIOKafkaConsumer(group_id=None, enable_auto_commit=False, **kw)
        with heard(cfg) as h:
            try:
                await asyncio.wait_for(consumer.start(), P.deadline_left(deadline))
            except Exception as exc:  # noqa: BLE001
                out["error"] = P.scrub(
                    await explain(exc, cfg, topics, h.lines), secrets
                )
                await consumer.stop()
                return out
        try:
            md = await asyncio.wait_for(
                consumer._client.fetch_all_metadata(), P.deadline_left(deadline)
            )
            have = md.topics()
            out["connected"] = True
            if not topics:
                out["subjects_seen"] = sorted(t for t in have if not t.startswith("_"))[
                    :50
                ]
                out["ok"] = True
                return out
            pattern = topic_pattern(topics)
            chosen = (
                [t for t in have if re.fullmatch(pattern, t)]
                if pattern
                else [t for t in topics if t in have]
            )
            missing = [] if pattern else [t for t in topics if t not in have]
            if missing:
                out["error"] = missing_words(missing, cfg)
                out["subjects_seen"] = sorted(t for t in have if not t.startswith("_"))[
                    :50
                ]
                return out
            parts = [
                TopicPartition(t, p)
                for t in chosen
                for p in sorted(md.partitions_for_topic(t) or ())
            ]
            consumer.assign(parts)
            ends = await consumer.end_offsets(parts)
            starts = await consumer.beginning_offsets(parts)
            for tp in parts:
                consumer.seek(tp, max(starts.get(tp, 0), ends.get(tp, 0) - 3))
            seen: list[str] = []
            while time.monotonic() < deadline and out["messages"] < 50:
                batch = await consumer.getmany(
                    timeout_ms=int(min(500, P.deadline_left(deadline) * 1000))
                )
                for tp, msgs in batch.items():
                    for m in msgs:
                        out["messages"] += 1
                        if m.topic not in seen:
                            seen.append(m.topic)
                        if out["sample"] is None:
                            out["sample"] = P.sample_of(m.value or b"")
            out["subjects_seen"] = seen or chosen[:50]
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = P.scrub(await explain(exc, cfg, topics), secrets)
        finally:
            try:
                await asyncio.wait_for(consumer.stop(), 3)
            except Exception:  # noqa: BLE001
                pass
        return out

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        topic = str(target.get("topic") or "").strip()
        if not topic:
            raise ConnectorError(
                "The command has no topic to send to. Set one on the writable signal."
            )
        kw = client_kwargs(cfg, secrets)
        producer = AIOKafkaProducer(acks="all", enable_idempotence=False, **kw)
        h = Heard(servers_of(cfg))
        logging.getLogger("aiokafka").addHandler(h)
        try:
            await asyncio.wait_for(producer.start(), 10)
            key = target.get("key")
            headers = [
                (str(k), str(v).encode())
                for k, v in (target.get("headers") or {}).items()
            ]
            md = await asyncio.wait_for(
                producer.send_and_wait(
                    topic,
                    P.payload_bytes(target, value),
                    key=str(key).encode() if key not in (None, "") else None,
                    headers=headers or None,
                ),
                10,
            )
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                P.scrub(await explain(exc, cfg, [topic], h.lines), secrets)
            ) from None
        finally:
            logging.getLogger("aiokafka").removeHandler(h)
            try:
                await asyncio.wait_for(producer.stop(), 5)
            except Exception:  # noqa: BLE001
                pass
        return {
            "published": True,
            "at": P.iso_now(),
            "topic": topic,
            "partition": md.partition,
            "offset": md.offset,
        }
