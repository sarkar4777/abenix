"""MQTT 3.1.1 and 5, TLS and client certificates, QoS 0 and 1, and $share for shared reading."""

from __future__ import annotations

import asyncio
import os
import socket
import ssl
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.telemetry import brokers
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

SHARE_GROUP = "abenix"


def _tls(
    client: Any, cfg: dict[str, Any], secrets: dict[str, Any], broker: brokers.Broker
) -> list[str]:
    """Client TLS from uploaded PEM text. Returns the temp files to remove afterwards."""
    if not broker.tls:
        return []
    files = []

    def pem(text: str | None) -> str | None:
        if not text:
            return None
        fd, path = tempfile.mkstemp(suffix=".pem")
        with os.fdopen(fd, "w") as f:
            f.write(text)
        files.append(path)
        return path

    client.tls_set(
        ca_certs=pem(cfg.get("tls_ca")),
        certfile=pem(cfg.get("tls_cert")),
        keyfile=pem(secrets.get("tls_key")),
        cert_reqs=ssl.CERT_REQUIRED,
    )
    if str(cfg.get("tls_verify", "true")).lower() in ("false", "0", "no"):
        client.tls_insecure_set(True)
    return files


def _client(
    client_id: str, cfg: dict[str, Any], secrets: dict[str, Any], broker: brokers.Broker
) -> tuple[Any, list[str]]:
    import paho.mqtt.client as mqtt

    v5 = str(cfg.get("protocol_version") or "3.1.1") == "5"
    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id[:64],
        clean_session=None if v5 else True,
        protocol=mqtt.MQTTv5 if v5 else mqtt.MQTTv311,
    )
    if cfg.get("username"):
        c.username_pw_set(cfg["username"], secrets.get("password") or None)
    files = _tls(c, cfg, secrets, broker)
    c.max_inflight_messages_set(200)
    c.max_queued_messages_set(5000)
    c.reconnect_delay_set(1, 30)
    return c, files


def _qos(cfg: dict[str, Any]) -> int:
    try:
        return 1 if int(cfg.get("qos") or 0) >= 1 else 0
    except (TypeError, ValueError):
        return 0


class MqttConnector(SourceConnector):
    transport = "mqtt"
    label = "MQTT"
    description = (
        "Topics on an MQTT broker, versions 3.1.1 and 5, with TLS and client certificates. "
        "Sparkplug B machines, sensors and gateways usually speak this."
    )
    config_fields = (
        ConfigField(
            key="broker_url",
            label="Broker address",
            kind="url",
            required=True,
            description=f"mqtt://host:port or mqtts://host:port, for example {brokers.EXAMPLE}",
        ),
        ConfigField(
            key="subjects",
            label="Topics",
            kind="list",
            required=False,
            description="Topic filters to read, e.g. spBv1.0/# or factory/+/line1/#. + is one level, # the rest.",
            default="spBv1.0/#",
        ),
        ConfigField(
            key="username",
            label="User name",
            kind="string",
            required=False,
            description="Leave empty when the broker allows anonymous clients, e.g. abenix-ingest.",
        ),
        ConfigField(
            key="password",
            label="Password",
            kind="secret",
            required=False,
            description="Stored encrypted and never shown again.",
        ),
        ConfigField(
            key="qos",
            label="QoS",
            kind="select",
            required=False,
            default="0",
            options=("0", "1"),
            description="1 asks the broker to resend what was not acknowledged.",
        ),
        ConfigField(
            key="protocol_version",
            label="Protocol version",
            kind="select",
            required=False,
            default="3.1.1",
            options=("3.1.1", "5"),
        ),
        ConfigField(
            key="tls_ca",
            label="CA certificate",
            kind="string",
            required=False,
            group="TLS",
            description="PEM, for a broker signed by your own CA. mqtts:// only.",
        ),
        ConfigField(
            key="tls_cert",
            label="Client certificate",
            kind="string",
            required=False,
            group="TLS",
            description="PEM, for brokers that ask for a client certificate.",
        ),
        ConfigField(
            key="tls_key",
            label="Client key",
            kind="secret",
            required=False,
            group="TLS",
            description="PEM private key for the client certificate. Stored encrypted.",
        ),
        ConfigField(
            key="tls_verify",
            label="Check the broker's certificate",
            kind="bool",
            required=False,
            group="TLS",
            default="true",
        ),
    )
    capabilities = {"receive": "subscribe", "write": True}
    scale_mode = "lease"
    default_decoder = "sparkplug_b"

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        try:
            broker = brokers.parse_url(cfg.get("broker_url") or "")
        except ValueError as exc:
            ctx.set_status("error", str(exc))
            await ctx.stopping.wait()
            return
        subjects = brokers.clean_topics(cfg.get("subjects"), default=["#"]) or ["#"]
        prefix = f"$share/{SHARE_GROUP}/" if ctx.shared else ""
        qos = _qos(cfg)
        client_id = f"abenix-ingest-{ctx.replica[-24:]}-{ctx.connection_id[:8]}"
        c, files = _client(client_id, cfg, secrets, broker)

        def on_connect(
            client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
        ) -> None:
            if getattr(rc, "is_failure", False):
                ctx.set_status("error", brokers.reason_words(rc, broker))
                return
            ctx.set_status("connected")
            for t in subjects:
                client.subscribe(prefix + t, qos=qos)

        def on_subscribe(
            client: Any, userdata: Any, mid: Any, reason_codes: Any, props: Any = None
        ) -> None:
            for rc in reason_codes or []:
                if getattr(rc, "is_failure", False):
                    ctx.set_status(
                        "error",
                        f"The broker at {broker.where} refused a subscription ({rc}). "
                        "Check the topic and that this user may read it.",
                    )

        def on_disconnect(
            client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
        ) -> None:
            if not ctx.stopping.is_set():
                ctx.set_status(
                    "connecting",
                    (
                        f"Lost the connection to the broker at {broker.where}, reconnecting."
                        if getattr(rc, "is_failure", False)
                        else None
                    ),
                )

        def on_message(client: Any, userdata: Any, msg: Any) -> None:
            ctx.emit_nowait(
                Envelope(
                    connection_id=ctx.connection_id,
                    tenant=ctx.tenant,
                    subject=msg.topic,
                    payload=msg.payload,
                    t_recv=time.time(),
                )
            )

        def on_connect_fail(client: Any, userdata: Any) -> None:
            try:
                socket.getaddrinfo(broker.host, broker.port)
                ctx.set_status(
                    "error",
                    f"Could not reach the broker at {broker.where}. Check the address "
                    "and that the broker is running.",
                )
            except socket.gaierror:
                ctx.set_status(
                    "error",
                    f"Could not find a broker called {broker.host}. Check the host name.",
                )

        c.on_connect = on_connect
        c.on_subscribe = on_subscribe
        c.on_disconnect = on_disconnect
        c.on_message = on_message
        c.on_connect_fail = on_connect_fail
        try:
            c.connect_async(broker.host, broker.port, keepalive=30)
        except Exception as exc:  # noqa: BLE001
            ctx.set_status("error", brokers.error_words(exc, broker))
        c.loop_start()
        try:
            await ctx.stopping.wait()
        finally:

            def close() -> None:
                try:
                    c.disconnect()
                finally:
                    c.loop_stop()

            await asyncio.to_thread(close)
            for f in files:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        topics = brokers.clean_topics(cfg.get("subjects"), default=["#"]) or ["#"]
        out = await asyncio.to_thread(
            brokers.test_connection,
            cfg.get("broker_url") or "",
            cfg.get("username"),
            secrets.get("password"),
            topics,
            5.0,
        )
        out["subjects_seen"] = out.get("topics_seen", [])
        out.setdefault("sample", None)
        return out

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        topic = target.get("topic")
        if not topic:
            raise ConnectorError("This signal has no topic to write to")
        payload = target.get("payload")
        if payload is None:
            payload = "" if value is None else str(value)
        if isinstance(payload, str):
            payload = payload.encode()
        try:
            await brokers.publisher.publish(
                target.get("connection_id")
                or cfg.get("_connection_id")
                or uuid.uuid4().hex,
                cfg.get("broker_url") or "",
                cfg.get("username"),
                secrets.get("password"),
                topic,
                payload,
            )
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(str(exc)) from None
        return {"published": True, "at": datetime.now(timezone.utc).isoformat()}
