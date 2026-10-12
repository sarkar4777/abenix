"""A local MQTT broker on the site network, bridged to Abenix through the gateway's buffer.

Each message becomes readings: a JSON object gives one signal per field
(nested objects as a/b/c), a bare number or word gives one signal named after
the topic. The asset comes from topic segments when the template asks for them.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from typing import Any
from urllib.parse import urlparse

from abenix_edge.buffer import now_ms
from abenix_edge.collectors.base import Collector, retry_sleep, slug

TS_KEYS = ("ts", "timestamp", "time", "t")


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}/{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(flatten(v, key))
            else:
                out[key] = v
    elif prefix:
        out[prefix] = obj
    return out


def ts_of(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        return (
            int(f / 1e6)
            if f > 1e17
            else int(f / 1e3) if f > 1e14 else int(f) if f > 1e11 else int(f * 1000)
        )
    try:
        from datetime import datetime, timezone

        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp() * 1000)
    except ValueError:
        return None


def readings(topic: str, payload: bytes) -> tuple[list[tuple[str, Any]], int | None]:
    text = payload.decode("utf-8", "replace").strip()
    try:
        doc = json.loads(text)
    except ValueError:
        doc = text
    name = topic.rsplit("/", 1)[-1] or "value"
    if isinstance(doc, dict):
        ts = None
        for k in TS_KEYS:
            if k in doc:
                ts = ts_of(doc.pop(k))
                break
        out = []
        for k, v in flatten(doc).items():
            if isinstance(v, list):
                v = json.dumps(v)
            out.append((k, v))
        return out, ts
    if isinstance(doc, list):
        return [(name, json.dumps(doc))], None
    if isinstance(doc, (int, float, bool)):
        return [(name, doc)], None
    try:
        return [(name, float(text))], None
    except ValueError:
        return [(name, text)], None


def render(template: str, topic: str) -> str:
    segs = topic.split("/")

    def sub(m: re.Match) -> str:
        try:
            return segs[int(m.group(1))]
        except (ValueError, IndexError):
            return ""

    return re.sub(r"\{topic\.(\d+)\}", sub, template or "")


class MqttBridgeCollector(Collector):
    type = "mqtt_bridge"
    label = "Local MQTT broker"

    def __init__(self, spec: dict[str, Any], sink: Any, gateway_id: str) -> None:
        super().__init__(spec, sink, gateway_id)
        self.url = str(spec.get("broker") or "mqtt://localhost:1883")
        self.topics = [
            t.strip()
            for t in str(spec.get("topics") or "#").replace(",", "\n").splitlines()
            if t.strip()
        ]
        self.node_tpl = str((spec.get("asset") or {}).get("node") or "")
        self.device_tpl = str((spec.get("asset") or {}).get("device") or "")

    def on_message(self, topic: str, payload: bytes) -> None:
        rows, ts = readings(topic, payload)
        node = (
            slug(render(self.node_tpl, topic), self.node)
            if "{topic." in self.node_tpl
            else self.node
        )
        device = (
            slug(render(self.device_tpl, topic), self.device)
            if "{topic." in self.device_tpl
            else self.device
        )
        if not rows:
            return
        prev = self.node
        self.node = node
        try:
            self.emit_many(
                [(n, v, None, "good") for n, v in rows],
                device=device,
                ts=ts or now_ms(),
            )
        finally:
            self.node = prev

    async def run(self, stop: asyncio.Event) -> None:
        import paho.mqtt.client as mqtt

        u = urlparse(self.url)
        if u.scheme not in ("mqtt", "mqtts", "tcp", "ssl"):
            self.fail(
                f"{self.url} is not an MQTT address, use mqtt://host:1883 or mqtts://host:8883"
            )
            return
        loop = asyncio.get_running_loop()
        lost = asyncio.Event()
        lock = threading.Lock()

        def on_connect(
            client: Any, userdata: Any, flags: Any, rc: Any, props: Any = None
        ) -> None:
            code = getattr(rc, "value", rc)
            if code == 0:
                for t in self.topics:
                    client.subscribe(t, qos=1)
                self.ok()
            elif code in (4, 5, 134, 135):
                self.fail(
                    f"The broker at {u.hostname}:{u.port or 1883} refused the user name or password."
                )
            else:
                self.fail(
                    f"The broker at {u.hostname}:{u.port or 1883} refused the connection ({rc})."
                )

        def on_disconnect(client: Any, userdata: Any, *args: Any) -> None:
            loop.call_soon_threadsafe(lost.set)

        def on_message(client: Any, userdata: Any, msg: Any) -> None:
            with lock:
                self.on_message(msg.topic, msg.payload)

        attempt = 0
        while not stop.is_set():
            lost.clear()
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"abenix-edge-{self.id}"[:23],
            )
            if self.spec.get("username"):
                client.username_pw_set(
                    self.spec["username"], self.spec.get("password") or None
                )
            if u.scheme in ("mqtts", "ssl"):
                client.tls_set()
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            try:
                await asyncio.to_thread(
                    client.connect,
                    u.hostname or "localhost",
                    u.port or (8883 if u.scheme in ("mqtts", "ssl") else 1883),
                    30,
                )
            except Exception as exc:  # noqa: BLE001
                self.fail(
                    f"Could not reach the broker at {u.hostname}:{u.port or 1883}: {exc}"
                )
                attempt += 1
                await retry_sleep(stop, attempt)
                continue
            client.loop_start()
            attempt = 0
            waiter = asyncio.create_task(stop.wait())
            lost_w = asyncio.create_task(lost.wait())
            await asyncio.wait([waiter, lost_w], return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            lost_w.cancel()
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            if not stop.is_set():
                self.fail(
                    f"Lost the broker at {u.hostname}:{u.port or 1883}. Reconnecting."
                )
                attempt += 1
                await retry_sleep(stop, attempt)
