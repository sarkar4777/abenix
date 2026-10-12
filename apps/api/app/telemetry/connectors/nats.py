"""NATS subjects: core with a queue group, or a JetStream durable pull consumer."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import nats as natslib
import nats.errors as NE
import nats.js.errors as JE
from nats.aio.client import RawCredentials
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)

DELIVER = {
    "new": DeliverPolicy.NEW,
    "all": DeliverPolicy.ALL,
    "last": DeliverPolicy.LAST,
}


def servers_of(cfg: dict[str, Any]) -> list[str]:
    out = P.subjects_of(cfg, "servers")
    if not out:
        raise ConnectorError(
            "Enter the server address, for example nats://nats.abenix-testbed.svc.cluster.local:4222"
        )
    return [s if "://" in s else f"nats://{s}" for s in out]


def where_of(cfg: dict[str, Any]) -> str:
    try:
        host, port = P.host_port(servers_of(cfg)[0], 4222)
        return f"{host}:{port}"
    except ConnectorError:
        return "the server"


def connect_kwargs(
    cfg: dict[str, Any], secrets: dict[str, Any], name: str
) -> dict[str, Any]:
    kw: dict[str, Any] = {"servers": servers_of(cfg), "name": f"abenix {name}"[:100]}
    user = (cfg.get("username") or "").strip()
    if user:
        kw["user"] = user
        kw["password"] = secrets.get("password") or ""
    if secrets.get("token"):
        kw["token"] = secrets["token"]
    if secrets.get("creds"):
        kw["user_credentials"] = RawCredentials(secrets["creds"])
    elif secrets.get("nkey_seed"):
        kw["nkeys_seed_str"] = secrets["nkey_seed"].strip()
    if P.as_bool(cfg, "tls", False) or any(
        s.startswith("tls://") for s in kw["servers"]
    ):
        kw["tls"] = P.ssl_context(cfg, secrets)
        if (cfg.get("tls_hostname") or "").strip():
            kw["tls_hostname"] = cfg["tls_hostname"].strip()
    return kw


def words(exc: BaseException, cfg: dict[str, Any]) -> str:
    where = where_of(cfg)
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
        text = str(e).lower()
        if (
            isinstance(e, (NE.AuthorizationError, NE.InvalidUserCredentialsError))
            or "authorization violation" in text
            or "authentication" in text
        ):
            return (
                f"NATS at {where} refused the credentials. Check the user name and password, "
                "token, creds file or nkey seed."
            )
        if "permissions violation" in text:
            subj = str(e).split('"')[1] if str(e).count('"') >= 2 else ""
            return (
                f"This user may not use subject {subj}. Ask the NATS admin to allow it, "
                "and $JS.API.> for JetStream."
            ).replace("  ", " ")
        if isinstance(e, JE.ServiceUnavailableError) or "jetstream not enabled" in text:
            return f"JetStream is not turned on at {where}. Use core mode, or enable JetStream on the server."
        if isinstance(e, JE.NotFoundError) or "stream not found" in text:
            return "No JetStream stream holds that subject. Check the subject or the stream name."
        if isinstance(e, (NE.SecureConnRequiredError,)):
            return f"NATS at {where} requires TLS. Turn on TLS."
        if isinstance(e, (NE.SecureConnWantedError, NE.SecureConnFailedError)):
            return f"The secure connection to NATS at {where} failed. Check TLS is on at the server and the CA."
    net = P.network_words(exc, where, "NATS server")
    if net:
        return net
    if isinstance(exc, (NE.NoServersError, NE.ConnectionClosedError, NE.UnexpectedEOF)):
        return f"Could not reach NATS at {where}. Check the address and that the server is running."
    if isinstance(exc, (NE.TimeoutError, asyncio.TimeoutError)):
        return f"NATS at {where} did not answer in time."
    return f"NATS at {where} failed: {type(exc).__name__}: {exc}"[:500]


async def explain(exc: BaseException, cfg: dict[str, Any]) -> str:
    text = words(exc, cfg)
    if text.startswith("Could not reach NATS"):
        host, port = P.host_port(servers_of(cfg)[0], 4222)
        return await P.probe_tcp(host, port, "NATS server") or text
    return text


def headers_of(msg: Any) -> dict[str, str]:
    out = {str(k): str(v) for k, v in (msg.headers or {}).items()}
    if msg.reply and not msg.reply.startswith("$JS.ACK"):
        out["nats.reply"] = msg.reply
    return out


class NatsConnector(SourceConnector):
    transport = "nats"
    label = "NATS"
    description = (
        "Subjects on a NATS server. Core mode shares the subjects across replicas with a queue group. "
        "JetStream mode reads a durable pull consumer and acknowledges each message after it is stored."
    )
    config_fields = (
        ConfigField(
            "servers",
            "Servers",
            kind="list",
            required=True,
            group="Connection",
            description="nats://host:4222, comma separated for a cluster. Example: nats://nats.abenix-testbed.svc.cluster.local:4222",
        ),
        ConfigField(
            "subjects",
            "Subjects",
            kind="list",
            required=True,
            group="Connection",
            description="The subjects to read, comma or newline separated. * matches one token and > the rest. Example: fleet.positions.>",
        ),
        ConfigField(
            "mode",
            "Mode",
            kind="select",
            group="Reading",
            default="core",
            options=("core", "jetstream"),
            description="core gets messages as they are published and nothing while Abenix is away. jetstream reads a stream and resumes where it left off.",
        ),
        ConfigField(
            "username",
            "User name",
            kind="string",
            group="Sign in",
            description="For servers with user and password sign-in. Example: abenix",
        ),
        ConfigField(
            "password",
            "Password",
            kind="secret",
            group="Sign in",
            description="Stored encrypted and never shown again.",
        ),
        ConfigField(
            "token",
            "Token",
            kind="secret",
            group="Sign in",
            description="For servers with token sign-in.",
        ),
        ConfigField(
            "creds",
            "Credentials file",
            kind="secret",
            group="Sign in",
            description="The text of a .creds file (JWT and nkey seed), for NGS, Synadia Cloud or decentralised auth. Example: -----BEGIN NATS USER JWT----- ...",
        ),
        ConfigField(
            "nkey_seed",
            "NKey seed",
            kind="secret",
            group="Sign in",
            description="A user nkey seed starting with SU, for nkey sign-in. Example: SUAM...",
        ),
        ConfigField(
            "tls",
            "Use TLS",
            kind="bool",
            group="TLS",
            default="false",
            description="Turn on when the server needs TLS. tls:// addresses turn it on as well.",
        ),
        ConfigField(
            "tls_ca",
            "CA certificate",
            kind="string",
            group="TLS",
            description="PEM text of the CA that signed the server's certificate. Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "tls_cert",
            "Client certificate",
            kind="string",
            group="TLS",
            description="PEM text, for servers that verify clients. Example: -----BEGIN CERTIFICATE----- ...",
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
            "Check the server's certificate",
            kind="bool",
            group="TLS",
            default="true",
            description="Turn off only for a test server with a self-signed certificate.",
        ),
        ConfigField(
            "queue_group",
            "Queue group",
            kind="string",
            group="Reading",
            description="Core mode: replicas in one queue group share the messages. Empty means abenix-<connection id>. Example: abenix-fleet",
        ),
        ConfigField(
            "stream",
            "Stream",
            kind="string",
            group="JetStream",
            description="JetStream: the stream to read. Empty means the stream that holds the first subject. Example: FLEET",
        ),
        ConfigField(
            "durable",
            "Durable consumer",
            kind="string",
            group="JetStream",
            description="JetStream: the consumer name, created when missing. Empty means abenix-<connection id>. Example: abenix-fleet",
        ),
        ConfigField(
            "deliver_policy",
            "Start from",
            kind="select",
            group="JetStream",
            default="new",
            options=("new", "all", "last"),
            description="JetStream: where a new consumer starts. Later runs resume from its acknowledged position.",
        ),
        ConfigField(
            "ack_wait",
            "Redeliver after (seconds)",
            kind="int",
            group="JetStream",
            default="30",
            description="JetStream: a message that is not stored and acknowledged in this time is sent again.",
        ),
        ConfigField(
            "max_ack_pending",
            "Most unacknowledged",
            kind="int",
            group="JetStream",
            default="5000",
            description="JetStream: the consumer pauses when this many messages are waiting to be stored.",
        ),
        ConfigField(
            "batch",
            "Fetch batch",
            kind="int",
            group="JetStream",
            default="200",
            description="JetStream: messages fetched per pull.",
        ),
    )
    capabilities = {"receive": "subscribe", "write": True}
    scale_mode = "shared"
    default_decoder = "json"

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        sup = P.Supervisor(ctx, lambda e: words(e, cfg), "nats")

        async def once() -> None:
            subjects = P.subjects_of(cfg)
            if not subjects:
                raise ConnectorError(
                    "Pick at least one subject, for example fleet.positions.>"
                )
            broken: asyncio.Future = asyncio.get_running_loop().create_future()

            async def on_error(e: Exception) -> None:
                text = str(e).lower()
                if "permissions violation" in text or "authorization" in text:
                    if not broken.done():
                        broken.set_exception(e)

            async def on_disconnect() -> None:
                if not ctx.stopping.is_set():
                    ctx.set_status(
                        "connecting",
                        f"Lost the connection to {where_of(cfg)}, reconnecting",
                    )

            async def on_reconnect() -> None:
                sup.connected()

            async def on_closed() -> None:
                if not broken.done():
                    broken.set_exception(
                        ConnectorError(
                            f"The connection to NATS at {where_of(cfg)} closed"
                        )
                    )

            try:
                nc = await natslib.connect(
                    **connect_kwargs(cfg, secrets, ctx.name),
                    connect_timeout=5,
                    allow_reconnect=True,
                    max_reconnect_attempts=-1,
                    reconnect_time_wait=1,
                    error_cb=on_error,
                    disconnected_cb=on_disconnect,
                    reconnected_cb=on_reconnect,
                    closed_cb=on_closed,
                )
            except Exception as exc:  # noqa: BLE001
                raise ConnectorError(await explain(exc, cfg)) from exc
            try:
                if (cfg.get("mode") or "core") == "jetstream":
                    await self._jetstream(ctx, nc, subjects, sup, broken)
                else:
                    await self._core(ctx, nc, subjects, sup, broken)
            finally:
                try:
                    await asyncio.wait_for(nc.close(), 5)
                except Exception:  # noqa: BLE001
                    pass

        await sup.run(once)

    async def _core(
        self,
        ctx: RunContext,
        nc: Any,
        subjects: list[str],
        sup: P.Supervisor,
        broken: asyncio.Future,
    ) -> None:
        cfg = ctx.config
        queue = (cfg.get("queue_group") or "").strip()
        if not queue and ctx.shared:
            queue = f"abenix-{ctx.connection_id}"

        async def handle(msg: Any) -> None:
            hdr = headers_of(msg)
            await ctx.emit(
                Envelope(
                    connection_id=ctx.connection_id,
                    tenant=ctx.tenant,
                    subject=msg.subject,
                    payload=msg.data,
                    headers=hdr,
                    t_recv=time.time(),
                    msg_id=hdr.get("Nats-Msg-Id") or None,
                )
            )

        for s in subjects:
            await nc.subscribe(
                s,
                queue=queue,
                cb=handle,
                pending_msgs_limit=20000,
                pending_bytes_limit=64 * 1024 * 1024,
            )
        await nc.flush(timeout=5)
        sup.connected()
        await P.until_stopped(ctx, broken)

    async def _jetstream(
        self,
        ctx: RunContext,
        nc: Any,
        subjects: list[str],
        sup: P.Supervisor,
        broken: asyncio.Future,
    ) -> None:
        cfg = ctx.config
        js = nc.jetstream(timeout=5)
        stream = (
            cfg.get("stream") or ""
        ).strip() or await js.find_stream_name_by_subject(subjects[0])
        durable = (cfg.get("durable") or "").strip() or f"abenix-{ctx.connection_id}"
        await ensure_consumer(js, stream, durable, subjects, cfg)
        psub = await js.pull_subscribe_bind(durable, stream)
        batch = max(1, P.as_int(cfg, "batch", 200))
        sup.connected()

        async def pull() -> None:
            while not ctx.stopping.is_set():
                try:
                    msgs = await psub.fetch(batch, timeout=1)
                except (NE.TimeoutError, asyncio.TimeoutError, JE.FetchTimeoutError):
                    continue
                except (NE.ConnectionReconnectingError, NE.ConnectionClosedError):
                    await asyncio.sleep(0.5)
                    continue
                for m in msgs:
                    md = m.metadata
                    hdr = headers_of(m)
                    hdr["nats.stream"] = md.stream
                    hdr["nats.stream_seq"] = str(md.sequence.stream)
                    hdr["nats.delivered"] = str(md.num_delivered)
                    if md.timestamp:
                        hdr["nats.timestamp"] = md.timestamp.isoformat()
                    await ctx.emit(
                        Envelope(
                            connection_id=ctx.connection_id,
                            tenant=ctx.tenant,
                            subject=m.subject,
                            payload=m.data,
                            headers=hdr,
                            t_recv=time.time(),
                            msg_id=f"{md.stream}/{md.sequence.stream}",
                            offset_token=m,
                        )
                    )

        await P.until_stopped(ctx, pull(), broken)

    async def commit(self, tokens: list[Any]) -> None:
        for m in tokens:
            if m is None:
                continue
            try:
                await m.ack()
            except NE.MsgAlreadyAckdError:
                pass
            except Exception as exc:  # noqa: BLE001
                # the server sends it again after ack_wait and the duplicate is dropped by msg_id
                logger.info("nats ack skipped: %s", type(exc).__name__)
                return

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 5.0
        out = P.result()
        errors: list[Exception] = []

        async def on_error(e: Exception) -> None:
            errors.append(e)

        nc = None
        try:
            nc = await natslib.connect(
                **connect_kwargs(cfg, secrets, "connection test"),
                connect_timeout=3,
                allow_reconnect=False,
                max_reconnect_attempts=0,
                error_cb=on_error,
            )
            out["connected"] = True
            subjects = P.subjects_of(cfg) or [">"]
            seen: list[str] = []

            async def handle(msg: Any) -> None:
                out["messages"] += 1
                if msg.subject not in seen and len(seen) < 50:
                    seen.append(msg.subject)
                if out["sample"] is None:
                    out["sample"] = P.sample_of(msg.data)

            if (cfg.get("mode") or "core") == "jetstream":
                js = nc.jetstream(timeout=P.deadline_left(deadline))
                stream = (
                    cfg.get("stream") or ""
                ).strip() or await js.find_stream_name_by_subject(subjects[0])
                info = await js.stream_info(stream)
                if info.state.last_seq:
                    try:
                        last = await js.get_msg(stream, seq=info.state.last_seq)
                        out["sample"] = P.sample_of(last.data or b"")
                        seen.append(last.subject)
                    except Exception:  # noqa: BLE001
                        pass
            for s in subjects:
                await nc.subscribe(s, cb=handle)
            await nc.flush(timeout=P.deadline_left(deadline))
            while time.monotonic() < deadline and out["messages"] < 50 and not errors:
                await asyncio.sleep(0.1)
            if errors:
                raise errors[0]
            out["subjects_seen"] = seen
            out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = P.scrub(
                await explain(errors[0] if errors else exc, cfg), secrets
            )
        finally:
            if nc is not None:
                try:
                    await asyncio.wait_for(nc.close(), 2)
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
        subject = str(target.get("subject") or target.get("topic") or "").strip()
        if not subject:
            raise ConnectorError(
                "The command has no subject to publish to. Set one on the writable signal."
            )
        errors: list[Exception] = []

        async def on_error(e: Exception) -> None:
            errors.append(e)

        nc = None
        try:
            nc = await natslib.connect(
                **connect_kwargs(cfg, secrets, "command"),
                connect_timeout=5,
                allow_reconnect=False,
                max_reconnect_attempts=0,
                error_cb=on_error,
            )
            body = P.payload_bytes(target, value)
            headers = {
                str(k): str(v) for k, v in (target.get("headers") or {}).items()
            } or None
            extra: dict[str, Any] = {}
            if target.get("jetstream"):
                ack = await nc.jetstream(timeout=5).publish(
                    subject, body, headers=headers
                )
                extra = {"stream": ack.stream, "seq": ack.seq}
            else:
                await nc.publish(subject, body, headers=headers)
                await nc.flush(timeout=5)
            await asyncio.sleep(0.05)
            if errors:
                raise errors[0]
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(P.scrub(await explain(exc, cfg), secrets)) from None
        finally:
            if nc is not None:
                try:
                    await asyncio.wait_for(nc.close(), 2)
                except Exception:  # noqa: BLE001
                    pass
        return {"published": True, "at": P.iso_now(), "subject": subject, **extra}


async def ensure_consumer(
    js: Any, stream: str, durable: str, subjects: list[str], cfg: dict[str, Any]
) -> None:
    """Creates the durable pull consumer, or brings its filter in line with the chosen subjects."""
    want = ConsumerConfig(
        durable_name=durable,
        ack_policy=AckPolicy.EXPLICIT,
        deliver_policy=DELIVER.get(
            (cfg.get("deliver_policy") or "new").strip(), DeliverPolicy.NEW
        ),
        ack_wait=float(P.as_int(cfg, "ack_wait", 30)),
        max_ack_pending=P.as_int(cfg, "max_ack_pending", 5000),
    )
    if len(subjects) == 1:
        want.filter_subject = subjects[0]
    else:
        want.filter_subjects = subjects
    try:
        info = await js.consumer_info(stream, durable)
    except JE.NotFoundError:
        await js.add_consumer(stream, want)
        return
    have = info.config
    if (have.filter_subject or None, have.filter_subjects or None) != (
        want.filter_subject or None,
        want.filter_subjects or None,
    ):
        want.deliver_policy = have.deliver_policy
        await js.add_consumer(stream, want)
