"""AMQP 0.9.1 queues and exchanges, as RabbitMQ and its compatibles speak it."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import aio_pika
import aiormq.exceptions as AE

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)

EXCHANGE_TYPES = ("topic", "direct", "fanout", "headers")


def where_of(cfg: dict[str, Any]) -> str:
    host = (cfg.get("host") or "").strip()
    return f"{host}:{P.as_int(cfg, 'port', 5671 if P.as_bool(cfg, 'tls', False) else 5672)}"


async def connect(
    cfg: dict[str, Any], secrets: dict[str, Any], name: str, timeout: float = 10.0
):
    host = (cfg.get("host") or "").strip()
    if not host:
        raise ConnectorError(
            "Enter the broker host, for example rabbitmq.abenix-testbed.svc.cluster.local"
        )
    tls = P.as_bool(cfg, "tls", False)
    kw: dict[str, Any] = {
        "host": host,
        "port": P.as_int(cfg, "port", 5671 if tls else 5672),
        "login": (cfg.get("username") or "guest").strip(),
        "password": secrets.get("password") or "",
        "virtualhost": (cfg.get("vhost") or "/").strip() or "/",
        "timeout": timeout,
        "client_properties": {"connection_name": f"abenix {name}"[:120]},
    }
    if tls:
        kw["ssl"] = True
        kw["ssl_context"] = P.ssl_context(cfg, secrets)
    return await asyncio.wait_for(aio_pika.connect(**kw), timeout + 1)


def words(exc: BaseException, cfg: dict[str, Any]) -> str:
    where = where_of(cfg) if cfg.get("host") else "the broker"
    vhost = (cfg.get("vhost") or "/").strip() or "/"
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
        text = str(e)
        if (
            isinstance(e, (AE.ProbableAuthenticationError, AE.AuthenticationError))
            or "ACCESS_REFUSED - Login was refused" in text
        ):
            return f"RabbitMQ at {where} refused the user name or password. Check both."
        if isinstance(e, AE.ConnectionNotAllowed) or "NOT_ALLOWED" in text:
            return (
                f"This user may not use virtual host {vhost} on {where}, or it does not exist. "
                "Check the vhost and the user's permissions."
            )
        if isinstance(e, AE.ChannelNotFoundEntity) or "NOT_FOUND" in text:
            what = (
                "queue"
                if "queue" in text
                else "exchange" if "exchange" in text else "queue or exchange"
            )
            name = text.split("'")[1] if text.count("'") >= 2 else ""
            return f"There is no {what} {name} in virtual host {vhost}. Check the name.".replace(
                "  ", " "
            )
        if isinstance(e, AE.ChannelAccessRefused) or "ACCESS_REFUSED" in text:
            return (
                f"This user is not allowed to read or configure that queue or exchange in {vhost}. "
                "Ask the RabbitMQ admin for read and configure permissions."
            )
        if isinstance(e, AE.ChannelPreconditionFailed) or "PRECONDITION_FAILED" in text:
            return (
                "The queue or exchange already exists with other settings (durable, type or arguments). "
                "Match them, or pick another queue name."
            )
        if "transient_nonexcl_queues" in text:
            return (
                "This RabbitMQ does not allow temporary shared queues. "
                "Turn on Keep the queue across restarts."
            )
        if isinstance(e, AE.ChannelLockedResource) or "RESOURCE_LOCKED" in text:
            return "The queue is exclusive to another connection. Pick a queue that is not exclusive."
    net = P.network_words(exc, where, "AMQP broker")
    if net:
        return net
    if isinstance(exc, AE.InvalidFrameError) and "Connection.Close" in str(exc):
        # RabbitMQ closes the handshake instead of opening a vhost the user may not use
        return (
            f"This user may not use virtual host {vhost} on {where}, or it does not exist. "
            "Check the vhost and the user's permissions."
        )
    if isinstance(exc, AE.IncompatibleProtocolError):
        return f"{where} does not speak AMQP 0.9.1. Check the port, 5672 for plain and 5671 for TLS."
    return f"RabbitMQ at {where} failed: {type(exc).__name__}: {exc}"[:500]


def headers_of(msg: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (msg.headers or {}).items():
        out[str(k)] = (
            v.decode("utf-8", errors="replace")
            if isinstance(v, (bytes, bytearray))
            else str(v)
        )
    out["amqp.routing_key"] = msg.routing_key or ""
    out["amqp.exchange"] = msg.exchange or ""
    if msg.content_type:
        out["content-type"] = msg.content_type
    if msg.type:
        out["amqp.type"] = msg.type
    if msg.app_id:
        out["amqp.app_id"] = msg.app_id
    if msg.timestamp:
        out["amqp.timestamp"] = msg.timestamp.isoformat()
    if msg.redelivered:
        out["amqp.redelivered"] = "true"
    return out


async def bind_queue(
    channel: Any,
    cfg: dict[str, Any],
    keys: list[str],
    default_name: str,
    *,
    temporary: bool = False,
):
    """The queue to read: an existing one, or one bound to the exchange with the routing keys."""
    mode = (cfg.get("mode") or "queue").strip()
    qname = (cfg.get("queue") or "").strip()
    if mode == "queue":
        if not qname:
            raise ConnectorError(
                "Enter the queue to read, or pick Exchange to bind a new queue"
            )
        q = await channel.get_queue(qname, ensure=True)
        return q, [qname]
    exname = (cfg.get("exchange") or "").strip()
    if not exname:
        raise ConnectorError("Enter the exchange to bind to")
    ex = await channel.get_exchange(exname, ensure=True)
    ex_type = (cfg.get("exchange_type") or "topic").strip()
    if not keys:
        keys = ["#"] if ex_type == "topic" else [""]
    if temporary:
        # named like the queues admins usually allow, a server-named amq.gen queue is often refused
        q = await channel.declare_queue(
            f"abenix.test-{uuid.uuid4().hex[:10]}", exclusive=True, auto_delete=True
        )
    else:
        args: dict[str, Any] = {}
        cap = P.as_int(cfg, "queue_max_length", 0)
        if cap > 0:
            args["x-max-length"] = cap
            args["x-overflow"] = "reject-publish"
        q = await channel.declare_queue(
            qname or default_name,
            durable=P.as_bool(cfg, "durable", True),
            arguments=args or None,
        )
    for k in keys:
        await q.bind(ex, routing_key=k)
    return q, keys


class AmqpConnector(SourceConnector):
    transport = "amqp"
    label = "RabbitMQ (AMQP 0.9.1)"
    description = (
        "Messages from a RabbitMQ queue, or from an exchange through a queue Abenix binds. Every ingest "
        "replica consumes the same queue, and each message is acknowledged only after it is stored."
    )
    config_fields = (
        ConfigField(
            "host",
            "Broker host",
            kind="string",
            required=True,
            group="Connection",
            description="Host name of the broker. Example: rabbitmq.abenix-testbed.svc.cluster.local",
        ),
        ConfigField(
            "port",
            "Port",
            kind="int",
            group="Connection",
            default="5672",
            description="5672 for plain AMQP, 5671 for TLS. Example: 5672",
        ),
        ConfigField(
            "vhost",
            "Virtual host",
            kind="string",
            group="Connection",
            default="/",
            description="The RabbitMQ virtual host. Leave / for the default one. Example: /",
        ),
        ConfigField(
            "username",
            "User name",
            kind="string",
            group="Sign in",
            default="guest",
            description="The RabbitMQ user. Example: abenix",
        ),
        ConfigField(
            "password",
            "Password",
            kind="secret",
            group="Sign in",
            description="Stored encrypted and never shown again.",
        ),
        ConfigField(
            "tls",
            "Use TLS",
            kind="bool",
            group="TLS",
            default="false",
            description="Turn on for amqps, usually on port 5671.",
        ),
        ConfigField(
            "tls_ca",
            "CA certificate",
            kind="string",
            group="TLS",
            description="PEM text of the CA that signed the broker's certificate. Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "tls_cert",
            "Client certificate",
            kind="string",
            group="TLS",
            description="PEM text, for brokers that ask for a client certificate. Example: -----BEGIN CERTIFICATE----- ...",
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
            description="Turn off only for a test broker with a self-signed certificate.",
        ),
        ConfigField(
            "mode",
            "Read from",
            kind="select",
            group="Reading",
            default="queue",
            options=("queue", "exchange"),
            description="queue reads a queue that already exists. exchange binds a queue to an exchange with the routing keys you list as subjects.",
        ),
        ConfigField(
            "queue",
            "Queue",
            kind="string",
            group="Reading",
            description="The queue to read. With exchange, the name of the queue Abenix declares, empty means abenix.<connection id>. Example: telemetry.shipments",
        ),
        ConfigField(
            "exchange",
            "Exchange",
            kind="string",
            group="Reading",
            description="With exchange: the exchange to bind to. It must already exist. Example: logistics.events",
        ),
        ConfigField(
            "exchange_type",
            "Exchange type",
            kind="select",
            group="Reading",
            default="topic",
            options=EXCHANGE_TYPES,
            description="The exchange's type, used to pick a default binding: # for topic, empty for the others.",
        ),
        ConfigField(
            "subjects",
            "Routing keys",
            kind="list",
            group="Reading",
            description="With exchange: the binding keys, comma separated. * matches one word and # the rest. Example: shipment.#. Empty means # for a topic exchange.",
        ),
        ConfigField(
            "durable",
            "Keep the queue across restarts",
            kind="bool",
            group="Reading",
            default="true",
            description="With exchange: whether the queue Abenix declares survives a broker restart.",
        ),
        ConfigField(
            "queue_max_length",
            "Queue length cap",
            kind="int",
            group="Reading",
            description="With exchange: most messages the queue holds while Abenix is away. Empty means no cap. New messages are refused when full. Example: 100000",
        ),
        ConfigField(
            "prefetch",
            "Prefetch",
            kind="int",
            group="Reading",
            default="500",
            description="Unacknowledged messages each replica holds at once. Higher is faster, lower spreads load across replicas.",
        ),
    )
    capabilities = {"receive": "subscribe", "write": True}
    scale_mode = "shared"
    default_decoder = "json"

    def __init__(self) -> None:
        self._channel: Any = None

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        sup = P.Supervisor(ctx, lambda e: words(e, cfg), "amqp")

        async def once() -> None:
            conn = await connect(cfg, secrets, ctx.name)
            try:
                channel = await conn.channel()
                await channel.set_qos(
                    prefetch_count=max(1, P.as_int(cfg, "prefetch", 500))
                )
                queue, _ = await bind_queue(
                    channel, cfg, P.subjects_of(cfg), f"abenix.{ctx.connection_id}"
                )
                self._channel = channel
                closed = asyncio.get_running_loop().create_future()

                def on_close(*_: Any) -> None:
                    if not closed.done():
                        closed.set_result(None)

                conn.close_callbacks.add(on_close)
                sup.connected()

                async def consume() -> None:
                    async with queue.iterator() as it:
                        async for msg in it:
                            await ctx.emit(
                                Envelope(
                                    connection_id=ctx.connection_id,
                                    tenant=ctx.tenant,
                                    subject=msg.routing_key or queue.name,
                                    payload=msg.body,
                                    headers=headers_of(msg),
                                    t_recv=time.time(),
                                    msg_id=msg.message_id or None,
                                    offset_token=msg,
                                )
                            )

                await P.until_stopped(ctx, consume(), closed)
                if not ctx.stopping.is_set():
                    raise ConnectorError(
                        f"The broker at {where_of(cfg)} closed the connection"
                    )
            finally:
                self._channel = None
                try:
                    await asyncio.wait_for(conn.close(), 5)
                except Exception:  # noqa: BLE001
                    pass

        await sup.run(once)

    async def commit(self, tokens: list[Any]) -> None:
        # messages come in delivery order, so acking the newest per channel with multiple acks the rest
        last: dict[int, Any] = {}
        for msg in tokens:
            if msg is None:
                continue
            ch = id(msg.channel)
            if ch not in last or msg.delivery_tag > last[ch].delivery_tag:
                last[ch] = msg
        for msg in last.values():
            try:
                await msg.ack(multiple=True)
            except Exception as exc:  # noqa: BLE001
                # the channel closed, the broker redelivers and duplicates are dropped by msg_id
                logger.info("amqp ack skipped: %s", type(exc).__name__)

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 5.0
        out = P.result()
        conn = None
        try:
            conn = await connect(cfg, secrets, "connection test", timeout=4.0)
            out["connected"] = True
            channel = await conn.channel()
            mode = (cfg.get("mode") or "queue").strip()
            if mode == "queue":
                qname = (cfg.get("queue") or "").strip()
                if not qname:
                    raise ConnectorError(
                        "Enter the queue to read, or pick Exchange to bind a new queue"
                    )
                q = await channel.get_queue(qname, ensure=True)
                ok = await q.declare()
                out["messages"] = int(ok.message_count or 0)
                out["subjects_seen"] = [qname]
                # a peek that puts the message straight back
                msg = await q.get(
                    no_ack=False, fail=False, timeout=P.deadline_left(deadline)
                )
                if msg is not None:
                    out["sample"] = P.sample_of(msg.body)
                    if msg.routing_key and msg.routing_key not in out["subjects_seen"]:
                        out["subjects_seen"].append(msg.routing_key)
                    await msg.nack(requeue=True)
            else:
                q, _ = await bind_queue(
                    channel, cfg, P.subjects_of(cfg), "", temporary=True
                )
                seen: list[str] = []
                async with q.iterator() as it:
                    try:
                        while time.monotonic() < deadline and out["messages"] < 50:
                            msg = await asyncio.wait_for(
                                it.__anext__(), P.deadline_left(deadline)
                            )
                            await msg.ack()
                            out["messages"] += 1
                            if msg.routing_key not in seen:
                                seen.append(msg.routing_key)
                            if out["sample"] is None:
                                out["sample"] = P.sample_of(msg.body)
                    except (asyncio.TimeoutError, StopAsyncIteration):
                        pass
                out["subjects_seen"] = seen[:50]
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = P.scrub(words(exc, cfg), secrets)
        finally:
            if conn is not None:
                try:
                    await asyncio.wait_for(conn.close(), 3)
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
        exname = str(
            target.get("exchange")
            if target.get("exchange") is not None
            else cfg.get("exchange") or ""
        )
        key = str(target.get("routing_key") or "").strip()
        if not key:
            raise ConnectorError(
                "The command has no routing key. Set one on the writable signal."
            )
        conn = None
        try:
            conn = await connect(cfg, secrets, "command")
            channel = await conn.channel(publisher_confirms=True)
            ex = (
                await channel.get_exchange(exname, ensure=True)
                if exname
                else channel.default_exchange
            )
            headers = {str(k): str(v) for k, v in (target.get("headers") or {}).items()}
            await asyncio.wait_for(
                ex.publish(
                    aio_pika.Message(
                        P.payload_bytes(target, value),
                        content_type=str(
                            target.get("content_type") or "application/json"
                        ),
                        headers=headers or None,
                        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                        app_id="abenix",
                    ),
                    routing_key=key,
                    mandatory=True,
                ),
                10,
            )
        except AE.DeliveryError:
            raise ConnectorError(
                f"No queue is bound to routing key {key} on exchange {exname or '(default)'}, so the command went nowhere"
            ) from None
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(P.scrub(words(exc, cfg), secrets)) from None
        finally:
            if conn is not None:
                try:
                    await asyncio.wait_for(conn.close(), 3)
                except Exception:  # noqa: BLE001
                    pass
        return {
            "published": True,
            "at": P.iso_now(),
            "exchange": exname,
            "routing_key": key,
        }
