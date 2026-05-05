"""MQTT publish — write-back to a broker topic.

Pairs with the MQTT trigger (consume side). Used to send commands to
a PLC/SCADA bridge, raise alarms, or feed downstream agents. Connects
to MQTT_URL env (default mqtt://abenix-mosquitto:1883).

paho-mqtt is sync — we run the publish in a worker thread so the asyncio
loop stays unblocked even if the broker is slow to ack a QoS-1/2 message.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any
from urllib.parse import urlparse

from engine.tools.base import BaseTool, ToolResult


class MqttPublishTool(BaseTool):
    name = "mqtt_publish"
    description = (
        "Publish a JSON payload to an MQTT topic on the platform broker. "
        "Use for write-back to PLC bridges, SCADA gateways, or downstream "
        "agents. QoS 0/1/2 supported, retain flag supported."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "MQTT topic (e.g. 'plant/pump1/cmd').",
            },
            "payload": {
                "description": "Message — string or JSON-serialisable object.",
            },
            "qos": {
                "type": "integer",
                "enum": [0, 1, 2],
                "default": 0,
                "description": "0=fire-and-forget, 1=at-least-once, 2=exactly-once.",
            },
            "retain": {
                "type": "boolean",
                "default": False,
                "description": "Persist as topic's last-known value.",
            },
        },
        "required": ["topic", "payload"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "published": {"type": "boolean"},
            "topic": {"type": "string"},
            "ts": {"type": "number"},
            "qos": {"type": "integer"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        topic = (arguments.get("topic") or "").strip()
        if not topic:
            return ToolResult(content="topic is required", is_error=True)

        qos = int(arguments.get("qos", 0) or 0)
        if qos not in (0, 1, 2):
            return ToolResult(content="qos must be 0, 1 or 2", is_error=True)
        retain = bool(arguments.get("retain", False))

        raw = arguments.get("payload")
        if isinstance(raw, (dict, list)):
            payload = json.dumps(raw)
        elif raw is None:
            payload = ""
        else:
            payload = str(raw)

        # MQTT_URL is the canonical name; MQTT_BROKER_URL kept as a fallback
        # for older configs that haven't migrated yet.
        url = (
            os.environ.get("MQTT_URL")
            or os.environ.get("MQTT_BROKER_URL")
            or "mqtt://abenix-mosquitto:1883"
        )
        parsed = urlparse(url)
        host = parsed.hostname or "abenix-mosquitto"
        port = parsed.port or 1883
        username = parsed.username
        password = parsed.password

        try:
            import paho.mqtt.publish as mqtt_publish
        except ImportError:
            return ToolResult(
                content=json.dumps(
                    {
                        "published": False,
                        "status": "not_installed",
                        "message": "paho-mqtt missing — add `paho-mqtt>=2.0` to requirements.txt",
                    }
                ),
                is_error=True,
            )

        auth = {"username": username, "password": password or ""} if username else None

        def _publish() -> None:
            mqtt_publish.single(
                topic=topic,
                payload=payload,
                qos=qos,
                retain=retain,
                hostname=host,
                port=port,
                auth=auth,
                keepalive=10,
            )

        try:
            await asyncio.wait_for(asyncio.to_thread(_publish), timeout=10)
        except asyncio.TimeoutError:
            return ToolResult(
                content=f"MQTT publish to {host}:{port} timed out after 10s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                content=f"MQTT publish failed: {e}",
                is_error=True,
            )

        ts = time.time()
        return ToolResult(
            content=json.dumps(
                {
                    "published": True,
                    "topic": topic,
                    "ts": ts,
                    "qos": qos,
                    "retain": retain,
                }
            ),
            metadata={
                "published": True,
                "topic": topic,
                "ts": ts,
                "qos": qos,
                "retain": retain,
            },
        )
