"""A WebSocket client: connect, optionally subscribe, and take every frame as a message."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import websockets.exceptions as WE
from websockets.asyncio.client import connect

from app.telemetry.connectors import _plain as P
from app.telemetry.connectors.base import (
    ConfigField,
    ConnectorError,
    Envelope,
    RunContext,
    SourceConnector,
)

logger = logging.getLogger(__name__)


def url_of(cfg: dict[str, Any]) -> str:
    url = (cfg.get("url") or "").strip()
    if not url:
        raise ConnectorError(
            "Enter the WebSocket address, for example ws://prices.abenix-testbed.svc.cluster.local:8765/ticks"
        )
    if not url.startswith(("ws://", "wss://")):
        raise ConnectorError("The address must start with ws:// or wss://")
    return url


def where_of(cfg: dict[str, Any]) -> str:
    u = urlparse((cfg.get("url") or "").strip())
    port = u.port or (443 if u.scheme == "wss" else 80)
    return f"{u.hostname or 'the server'}:{port}"


def default_subject(cfg: dict[str, Any]) -> str:
    if (cfg.get("subject") or "").strip():
        return cfg["subject"].strip()
    u = urlparse((cfg.get("url") or "").strip())
    host = u.hostname or "ws"
    host = (
        host.replace(".", "-")
        if host.replace(".", "").isdigit()
        else host.split(".")[0]
    )
    path = u.path.strip("/").replace(".", "-")
    return f"{host}/{path}" if path else host


def headers_of(cfg: dict[str, Any], secrets: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in str(cfg.get("headers") or "").splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ConnectorError(
                f"Each header line must be Name: value, this one is not: {line.strip()[:60]}"
            )
        k, v = line.split(":", 1)
        out.append((k.strip(), v.strip()))
    if secrets.get("auth_header"):
        out.append(("Authorization", str(secrets["auth_header"]).strip()))
    return out


def connect_kwargs(
    cfg: dict[str, Any], secrets: dict[str, Any], *, open_timeout: float = 10
) -> dict[str, Any]:
    url = url_of(cfg)
    kw: dict[str, Any] = {
        "additional_headers": headers_of(cfg, secrets) or None,
        "open_timeout": open_timeout,
        "ping_interval": P.as_int(cfg, "ping_interval", 20) or None,
        "ping_timeout": P.as_int(cfg, "ping_timeout", 20) or None,
        "close_timeout": 3,
        "max_size": max(1, P.as_int(cfg, "max_message_kb", 1024)) * 1024,
        "max_queue": 64,
        "proxy": None,
        "user_agent_header": "Abenix telemetry",
    }
    if (cfg.get("subprotocol") or "").strip():
        kw["subprotocols"] = [
            s.strip() for s in cfg["subprotocol"].split(",") if s.strip()
        ]
    if url.startswith("wss://"):
        kw["ssl"] = P.ssl_context(cfg, secrets)
    return kw


def subscribe_message(cfg: dict[str, Any]) -> str | None:
    msg = str(cfg.get("subscribe_message") or "").strip()
    if not msg:
        return None
    return msg.replace("{subjects}", json.dumps(P.subjects_of(cfg)))


def words(exc: BaseException, cfg: dict[str, Any]) -> str:
    where = where_of(cfg)
    for e in P.walk(exc):
        if isinstance(e, ConnectorError):
            return str(e)
        if isinstance(e, WE.InvalidStatus):
            code = e.response.status_code
            if code in (401, 403):
                return (
                    f"The WebSocket server at {where} refused the sign-in ({code}). "
                    "Check the Authorization header or token."
                )
            if code == 404:
                return f"There is no WebSocket endpoint at {urlparse(cfg.get('url') or '').path or '/'} on {where}. Check the path."
            return (
                f"The server at {where} answered {code} instead of opening a WebSocket."
            )
        if isinstance(e, WE.InvalidURI):
            return "The address is not a valid WebSocket URL. It must look like ws://host:port/path"
        if isinstance(e, (WE.InvalidHandshake, WE.InvalidMessage)):
            return f"{where} did not answer as a WebSocket server. Check the address and the path."
        if isinstance(e, WE.PayloadTooBig):
            return "A message was larger than the size cap. Raise Largest message."
        if isinstance(e, WE.ConnectionClosedError):
            return f"The WebSocket server at {where} closed the connection ({e.rcvd.code if e.rcvd else 'no close frame'})."
    net = P.network_words(exc, where, "WebSocket server")
    if net:
        return net
    return f"The WebSocket connection to {where} failed: {type(exc).__name__}: {exc}"[
        :500
    ]


class WebSocketConnector(SourceConnector):
    transport = "websocket"
    label = "WebSocket"
    description = (
        "A WebSocket stream, such as a market data feed or an app's live events. Abenix connects as a "
        "client, sends an optional subscribe message, and takes every frame as one message."
    )
    config_fields = (
        ConfigField(
            "url",
            "Address",
            kind="url",
            required=True,
            group="Connection",
            description="ws:// or wss:// with the path. Example: ws://prices.abenix-testbed.svc.cluster.local:8765/ticks",
        ),
        ConfigField(
            "auth_header",
            "Authorization header",
            kind="secret",
            group="Sign in",
            description="Sent as the Authorization header, for example Bearer <token>. Stored encrypted. Example: Bearer eyJhbGciOi...",
        ),
        ConfigField(
            "headers",
            "Other headers",
            kind="string",
            group="Connection",
            description="One per line as Name: value. Do not put secrets here, use Authorization header. Example: X-Client: abenix",
        ),
        ConfigField(
            "subprotocol",
            "Subprotocol",
            kind="string",
            group="Connection",
            description="Sec-WebSocket-Protocol values, comma separated, when the server asks for one. Example: graphql-transport-ws",
        ),
        ConfigField(
            "subscribe_message",
            "Subscribe message",
            kind="string",
            group="Reading",
            description='Sent after every connect. {subjects} becomes the subjects as a JSON list. Example: {"op": "subscribe", "symbols": {subjects}}',
        ),
        ConfigField(
            "subjects",
            "Channels or symbols",
            kind="list",
            group="Reading",
            description="Put into the subscribe message where it says {subjects}, as a JSON list. Example: BTC-USD, ETH-USD",
        ),
        ConfigField(
            "subject",
            "Subject",
            kind="string",
            group="Reading",
            description="The subject every message gets, which the mapping turns into an asset. Empty means host/path. Example: markets/prices",
        ),
        ConfigField(
            "ping_interval",
            "Ping every (seconds)",
            kind="int",
            group="Reading",
            default="20",
            description="Keeps the connection alive and notices a dead one. 0 turns pings off.",
        ),
        ConfigField(
            "ping_timeout",
            "Ping timeout (seconds)",
            kind="int",
            group="Reading",
            default="20",
            description="Reconnect when a ping gets no answer in this time.",
        ),
        ConfigField(
            "max_message_kb",
            "Largest message (KB)",
            kind="int",
            group="Reading",
            default="1024",
            description="Bigger messages close the connection.",
        ),
        ConfigField(
            "tls_ca",
            "CA certificate",
            kind="string",
            group="TLS",
            description="For wss://, PEM text of the CA that signed the server's certificate. Example: -----BEGIN CERTIFICATE----- ...",
        ),
        ConfigField(
            "tls_cert",
            "Client certificate",
            kind="string",
            group="TLS",
            description="For wss:// servers that ask for a client certificate. Example: -----BEGIN CERTIFICATE----- ...",
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
    )
    capabilities = {"receive": "subscribe", "write": True}
    # every client gets the whole stream, so one replica holds it
    scale_mode = "lease"
    default_decoder = "json"

    async def run(self, ctx: RunContext) -> None:
        cfg, secrets = ctx.config, ctx.secrets
        sup = P.Supervisor(ctx, lambda e: words(e, cfg), "websocket")
        subject = default_subject(cfg)

        async def once() -> None:
            async with connect(url_of(cfg), **connect_kwargs(cfg, secrets)) as ws:
                sub = subscribe_message(cfg)
                if sub:
                    await ws.send(sub)
                sup.connected()

                async def consume() -> None:
                    async for frame in ws:
                        await ctx.emit(
                            Envelope(
                                connection_id=ctx.connection_id,
                                tenant=ctx.tenant,
                                subject=subject,
                                payload=(
                                    frame.encode()
                                    if isinstance(frame, str)
                                    else bytes(frame)
                                ),
                                headers={
                                    "ws.binary": (
                                        "false" if isinstance(frame, str) else "true"
                                    )
                                },
                                t_recv=time.time(),
                            )
                        )

                await P.until_stopped(ctx, consume())
                if not ctx.stopping.is_set():
                    raise ConnectorError(
                        f"The WebSocket server at {where_of(cfg)} closed the connection"
                    )

        await sup.run(once)

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + 5.0
        out = P.result()
        try:
            async with connect(
                url_of(cfg), **connect_kwargs(cfg, secrets, open_timeout=4)
            ) as ws:
                out["connected"] = True
                sub = subscribe_message(cfg)
                if sub:
                    await ws.send(sub)
                try:
                    while time.monotonic() < deadline and out["messages"] < 50:
                        frame = await asyncio.wait_for(
                            ws.recv(), P.deadline_left(deadline)
                        )
                        out["messages"] += 1
                        # the first frame is often the subscribe answer, the second is real data
                        if out["messages"] <= 2:
                            out["sample"] = P.sample_of(
                                frame.encode()
                                if isinstance(frame, str)
                                else bytes(frame)
                            )
                except asyncio.TimeoutError:
                    pass
                out["subjects_seen"] = [default_subject(cfg)] if out["messages"] else []
                out["ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["error"] = P.scrub(words(exc, cfg), secrets)
        return out

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        reply = None
        try:
            async with connect(url_of(cfg), **connect_kwargs(cfg, secrets)) as ws:
                sub = subscribe_message(cfg) if target.get("subscribe_first") else None
                if sub:
                    await ws.send(sub)
                await ws.send(
                    P.payload_bytes(target, value).decode("utf-8", errors="replace")
                )
                wait = float(target.get("wait_reply_s") or 1.0)
                end = time.monotonic() + wait
                # reply_contains skips the stream's own traffic until the answer comes
                marker = str(target.get("reply_contains") or "")
                while time.monotonic() < end:
                    try:
                        frame = await asyncio.wait_for(ws.recv(), P.deadline_left(end))
                    except asyncio.TimeoutError:
                        break
                    text = (
                        frame
                        if isinstance(frame, str)
                        else bytes(frame).decode("utf-8", errors="replace")
                    )
                    if marker and marker not in text:
                        continue
                    reply = text[:1000]
                    break
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(P.scrub(words(exc, cfg), secrets)) from None
        return {"published": True, "at": P.iso_now(), "reply": reply}
