"""MQTT broker addresses, a short connection test, and the client commands go out on."""

from __future__ import annotations

import asyncio
import os
import socket
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

SCHEMES = {
    "mqtt": (1883, False),
    "tcp": (1883, False),
    "mqtts": (8883, True),
    "ssl": (8883, True),
}
EXAMPLE = "mqtt://abenix-mosquitto.abenix.svc.cluster.local:1883"


@dataclass(frozen=True)
class Broker:
    host: str
    port: int
    tls: bool

    @property
    def where(self) -> str:
        return f"{self.host}:{self.port}"


def parse_url(url: str) -> Broker:
    """mqtt://host:port or mqtts://host:port. Raises ValueError in plain words."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError(f"Enter the broker address, for example {EXAMPLE}")
    if "://" not in raw:
        raw = "mqtt://" + raw
    u = urlparse(raw)
    scheme = (u.scheme or "").lower()
    if scheme not in SCHEMES:
        raise ValueError(
            f"The address must start with mqtt:// or mqtts://, for example {EXAMPLE}"
        )
    if not u.hostname:
        raise ValueError(f"The address has no host name, for example {EXAMPLE}")
    default_port, tls = SCHEMES[scheme]
    try:
        port = u.port or default_port
    except ValueError:
        raise ValueError("The port must be a number between 1 and 65535") from None
    return Broker(host=u.hostname, port=port, tls=tls)


def clean_topics(values: Any, *, default: list[str] | None = None) -> list[str]:
    """Topic filters as a list of non-empty strings. Raises ValueError in plain words."""
    if values is None:
        return list(default or [])
    if isinstance(values, str):
        values = [v for v in values.replace("\n", ",").split(",")]
    out: list[str] = []
    for v in values:
        t = str(v or "").strip()
        if not t:
            continue
        if len(t) > 512:
            raise ValueError("A topic is longer than 512 characters")
        parts = t.split("/")
        for i, p in enumerate(parts):
            if "#" in p and (p != "#" or i != len(parts) - 1):
                raise ValueError(f"In {t}, # can only be the whole last level")
            if "+" in p and p != "+":
                raise ValueError(f"In {t}, + must be a whole level on its own")
        if t not in out:
            out.append(t)
    if len(out) > 50:
        raise ValueError("At most 50 topics per broker")
    return out


def reason_words(rc: Any, broker: Broker) -> str:
    code = getattr(rc, "value", rc)
    text = str(rc).lower()
    if "not authorized" in text or "bad user name" in text or code in (4, 5, 134, 135):
        return (
            f"The broker at {broker.where} refused the user name or password. "
            "Check them, or leave both empty if the broker allows anonymous clients."
        )
    if "identifier" in text or code in (2, 133):
        return f"The broker at {broker.where} refused the client id."
    return f"The broker at {broker.where} refused the connection ({rc})."


def error_words(exc: BaseException, broker: Broker) -> str:
    if isinstance(exc, socket.gaierror):
        return (
            f"Could not find a broker called {broker.host}. Check the host name, "
            f"for example {EXAMPLE}"
        )
    if isinstance(exc, ssl.SSLError):
        return (
            f"The secure connection to {broker.where} failed. Check the broker "
            "uses TLS on this port, or use mqtt:// for a plain connection."
        )
    if isinstance(exc, (ConnectionRefusedError, TimeoutError, OSError)):
        return (
            f"Could not reach the broker at {broker.where}. Check the address "
            "and that the broker is running."
        )
    return f"Could not connect to the broker at {broker.where}: {exc}"


def make_client(
    client_id: str,
    broker: Broker,
    username: str | None,
    password: str | None,
    *,
    clean_session: bool = True,
) -> Any:
    import paho.mqtt.client as mqtt

    c = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id[:64],
        clean_session=clean_session,
        protocol=mqtt.MQTTv311,
    )
    if username:
        c.username_pw_set(username, password or None)
    if broker.tls:
        c.tls_set()
    c.max_inflight_messages_set(200)
    c.max_queued_messages_set(5000)
    c.reconnect_delay_set(1, 10)
    return c


def test_connection(
    url: str,
    username: str | None,
    password: str | None,
    topics: list[str],
    seconds: float = 5.0,
) -> dict[str, Any]:
    """Connect for up to `seconds`, listen, and say what happened in plain words."""
    out: dict[str, Any] = {
        "ok": False,
        "connected": False,
        "messages": 0,
        "topics_seen": [],
        "error": None,
    }
    try:
        broker = parse_url(url)
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    seen: list[str] = []
    lock = threading.Lock()
    connected = threading.Event()
    refused: list[str] = []

    def on_connect(
        client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
    ) -> None:
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc != 0):
            refused.append(reason_words(rc, broker))
            connected.set()
            return
        out["connected"] = True
        for t in topics or ["#"]:
            client.subscribe(t, qos=0)
        connected.set()

    def on_message(client: Any, userdata: Any, msg: Any) -> None:
        with lock:
            out["messages"] += 1
            if msg.topic not in seen and len(seen) < 25:
                seen.append(msg.topic)

    c = make_client(f"abenix-test-{uuid.uuid4().hex[:10]}", broker, username, password)
    c.on_connect = on_connect
    c.on_message = on_message
    deadline = time.monotonic() + seconds
    try:
        c.connect(broker.host, broker.port, keepalive=10)
    except BaseException as exc:  # noqa: BLE001
        out["error"] = error_words(exc, broker)
        return out
    c.loop_start()
    try:
        connected.wait(max(0.1, deadline - time.monotonic()))
        if refused:
            out["error"] = refused[0]
            return out
        if not out["connected"]:
            out["error"] = (
                f"Could not reach the broker at {broker.where}. Check the address "
                "and that the broker is running."
            )
            return out
        # listen for the rest of the window, stop early once something arrived
        while time.monotonic() < deadline:
            time.sleep(0.1)
            if out["messages"] >= 200:
                break
    finally:
        try:
            c.disconnect()
        finally:
            c.loop_stop()
    out["topics_seen"] = sorted(seen)
    out["ok"] = out["connected"]
    if out["ok"] and not out["messages"]:
        out["note"] = (
            "Connected, but nothing arrived in five seconds. Machines appear "
            "when a node sends its birth message."
        )
    return out


class Publisher:
    """One long-lived client per broker connection in this process, for commands."""

    def __init__(self) -> None:
        self._clients: dict[str, tuple[str, Any, threading.Event]] = {}
        self._lock = threading.Lock()

    def _client(
        self,
        conn_id: str,
        url: str,
        username: str | None,
        password: str | None,
        sig: str,
    ) -> tuple[Any, threading.Event]:
        with self._lock:
            hit = self._clients.get(conn_id)
            if hit and hit[0] == sig:
                return hit[1], hit[2]
            if hit:
                self._close(hit[1])
            broker = parse_url(url)
            ready = threading.Event()
            c = make_client(
                f"abenix-cmd-{socket.gethostname()[:20]}-{os.getpid()}-{conn_id[:8]}",
                broker,
                username,
                password,
            )

            def on_connect(
                client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
            ) -> None:
                if not getattr(rc, "is_failure", False):
                    ready.set()

            def on_disconnect(
                client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
            ) -> None:
                ready.clear()

            c.on_connect = on_connect
            c.on_disconnect = on_disconnect
            c.connect_async(broker.host, broker.port, keepalive=30)
            c.loop_start()
            self._clients[conn_id] = (sig, c, ready)
            return c, ready

    @staticmethod
    def _close(c: Any) -> None:
        try:
            c.disconnect()
            c.loop_stop()
        except Exception:  # noqa: BLE001
            pass

    def publish_sync(
        self,
        conn_id: str,
        url: str,
        username: str | None,
        password: str | None,
        topic: str,
        payload: bytes,
        timeout: float = 3.0,
    ) -> None:
        sig = f"{url}|{username}|{password}"
        c, ready = self._client(conn_id, url, username, password, sig)
        broker = parse_url(url)
        if not ready.wait(timeout):
            raise ConnectionError(
                f"Could not reach the broker at {broker.where}. Check the address "
                "and that the broker is running."
            )
        info = c.publish(topic, payload, qos=0)
        info.wait_for_publish(timeout)
        if not info.is_published():
            raise ConnectionError(
                f"The broker at {broker.where} did not take the command."
            )

    async def publish(self, *args: Any, **kw: Any) -> None:
        await asyncio.to_thread(self.publish_sync, *args, **kw)

    def forget(self, conn_id: str) -> None:
        with self._lock:
            hit = self._clients.pop(str(conn_id), None)
        if hit:
            self._close(hit[1])


publisher = Publisher()


async def warm_publishers() -> int:
    """Connect the command client of every enabled MQTT source at API start, so the first command is fast."""
    from sqlalchemy import select

    from app.core.deps import async_session
    from app.telemetry import pipeline
    from models.telemetry import TelemetryConnection

    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    select(TelemetryConnection).where(
                        TelemetryConnection.enabled.is_(True),
                        TelemetryConnection.transport == "mqtt",
                    )
                )
            )
            .scalars()
            .all()
        )
    n = 0
    for c in rows:
        try:
            row = pipeline.connection_row(c)
            cfg = row["config"]
            pw = row["secrets"].get("password")
            sig = f"{cfg.get('broker_url')}|{cfg.get('username')}|{pw}"
            await asyncio.to_thread(
                publisher._client,
                row["id"],
                cfg.get("broker_url") or "",
                cfg.get("username"),
                pw,
                sig,
            )
            n += 1
        except Exception:  # noqa: BLE001
            continue
    return n
