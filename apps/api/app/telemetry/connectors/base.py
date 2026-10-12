"""The connector side of the telemetry pipeline: transports that bring messages in and send commands out.

A connector yields Envelopes. A decoder and the connection's mapping turn each
one into Records, and the store keeps those. Add a transport by dropping a
module in this package that defines a SourceConnector subclass. The registry
finds it, nothing else needs editing.

    class KafkaConnector(SourceConnector):
        transport = "kafka"
        label = "Kafka"
        description = "Topics on a Kafka cluster, Redpanda or Event Hubs."
        config_fields = (ConfigField("bootstrap_servers", "Bootstrap servers", kind="string", required=True), ...)
        capabilities = {"receive": "subscribe", "write": True}
        scale_mode = "shared"

        async def run(self, ctx):
            ...
            while not ctx.stopping.is_set():
                msg = await consumer.getone()
                await ctx.emit(Envelope(ctx.connection_id, ctx.tenant, msg.topic, msg.value,
                                        headers=..., msg_id=..., offset_token=(msg.partition, msg.offset)))

        async def commit(self, tokens):
            await consumer.commit(...)          # called by the pipeline after the store flush
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from engine.tools.base import ConfigField

__all__ = [
    "ConfigField",
    "ConnectorError",
    "Envelope",
    "RunContext",
    "SourceConnector",
    "STATUSES",
    "FIELD_KINDS",
    "clean_config",
]

STATUSES = ("connected", "connecting", "error", "disabled")


@dataclass(slots=True)
class Envelope:
    """One message as the transport delivered it."""

    connection_id: str
    tenant: str
    # topic, routing key, partition key, OPC UA node id or register block
    subject: str
    payload: bytes
    headers: dict[str, str] = field(default_factory=dict)
    t_recv: float = field(default_factory=time.time)
    # set it when the transport has a stable id, duplicates within a day are dropped
    msg_id: str | None = None
    # what commit() needs to acknowledge this message, None when nothing is acked
    offset_token: Any = None


class ConnectorError(Exception):
    """A failure to say to a person as it is, such as a refused password."""


class RunContext:
    """What a running connector gets from the pipeline. One per connection per replica."""

    def __init__(
        self,
        *,
        connection_id: str,
        tenant: str,
        name: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
        replica: str,
        shared: bool,
        queue_max: int = 20000,
        on_enqueue: Callable[[], None] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.connection_id = connection_id
        self.tenant = tenant
        self.name = name
        self.config = config
        self.secrets = secrets
        self.replica = replica
        # true when every replica runs this connection, join a consumer group or $share
        self.shared = shared
        self.stopping = asyncio.Event()
        self.queue: deque = deque()
        self.queue_max = queue_max
        self.status = "connecting"
        self.last_error: str | None = None
        self.received = 0
        self.dropped = 0
        self.last_message_at: float | None = None
        self._on_enqueue = on_enqueue
        self._loop = loop
        self._room = asyncio.Event()
        self._room.set()

    async def emit(self, env: Envelope) -> None:
        """Hand one message to the pipeline. Waits while this connection's queue is full."""
        while len(self.queue) >= self.queue_max and not self.stopping.is_set():
            self._room.clear()
            await self._room.wait()
        self._push(env)

    def emit_nowait(self, env: Envelope) -> bool:
        """For clients that call back on their own thread. False when the queue was full and it was dropped."""
        if len(self.queue) >= self.queue_max:
            self.dropped += 1
            self.received += 1
            return False
        self._push(env)
        return True

    def _push(self, env: Envelope) -> None:
        self.received += 1
        self.last_message_at = env.t_recv
        self.queue.append(env)
        if len(self.queue) == 1 and self._on_enqueue is not None:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._on_enqueue)
            else:
                self._on_enqueue()

    def taken(self) -> None:
        """Called by the pipeline after it drains, so a waiting emit() can go on."""
        if len(self.queue) < self.queue_max:
            self._room.set()

    def set_status(self, status: str, plain_error: str | None = None) -> None:
        """connected, connecting, error or disabled, with the reason in plain words."""
        self.status = status if status in STATUSES else "error"
        self.last_error = plain_error

    def ack(self, offset_token: Any) -> None:
        """Kept for symmetry with the contract, the pipeline acks through commit() after each flush."""
        return None


class SourceConnector:
    """A transport. Subclass it in a module of this package and the registry finds it."""

    transport: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    # what an admin fills in. kind "secret" values are encrypted and never returned
    config_fields: ClassVar[tuple[ConfigField, ...]] = ()
    # receive: subscribe, poll or push. write: whether commands can go back out
    capabilities: ClassVar[dict[str, Any]] = {"receive": "subscribe", "write": False}
    # lease: one replica at a time. shared: every replica joins and takes a slice
    scale_mode: ClassVar[str] = "lease"
    # the decoder a new connection of this transport starts with, such as "values"
    default_decoder: ClassVar[str | None] = None

    async def run(self, ctx: RunContext) -> None:
        """Receive until ctx.stopping is set. Reconnect with backoff, report with ctx.set_status."""
        raise NotImplementedError

    async def commit(self, tokens: list[Any]) -> None:
        """Acknowledge messages whose records are stored. Called by the pipeline after each flush."""
        return None

    async def test(
        self, cfg: dict[str, Any], secrets: dict[str, Any]
    ) -> dict[str, Any]:
        """Connect for up to 5 s: {ok, connected, messages, subjects_seen, sample, error}."""
        return {
            "ok": False,
            "connected": False,
            "messages": 0,
            "subjects_seen": [],
            "sample": None,
            "error": f"{self.label or self.transport} has no connection test",
        }

    async def write(
        self,
        cfg: dict[str, Any],
        secrets: dict[str, Any],
        target: dict[str, Any],
        value: Any,
    ) -> dict[str, Any]:
        """Send one value back: {published, at}. target comes from the mapping or a Sparkplug birth."""
        raise ConnectorError(f"{self.label or self.transport} cannot send commands")

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "transport": cls.transport,
            "label": cls.label,
            "description": cls.description,
            "config_fields": [f.to_dict() for f in cls.config_fields],
            "capabilities": dict(cls.capabilities),
            "scale_mode": cls.scale_mode,
            "default_decoder": cls.default_decoder,
        }


FIELD_KINDS = ("secret", "string", "url", "int", "bool", "select", "list")


def clean_config(
    fields: tuple[ConfigField, ...], cfg: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Values coerced to each field's kind, and the problems in plain words.

    list takes a list of text or one text with a value per line or comma.
    """
    out = dict(cfg)
    problems: list[str] = []
    for f in fields:
        if f.key not in cfg or cfg[f.key] in (None, ""):
            continue
        v = cfg[f.key]
        name = f.label or f.key
        if f.kind == "list":
            if isinstance(v, str):
                v = [x.strip() for x in v.replace(chr(10), ",").split(",")]
            if not isinstance(v, (list, tuple)):
                problems.append(f"{name} must be a list")
                continue
            out[f.key] = [str(x).strip() for x in v if str(x).strip()]
        elif f.kind == "int":
            try:
                out[f.key] = int(str(v).strip())
            except ValueError:
                problems.append(f"{name} must be a whole number")
        elif f.kind == "bool":
            out[f.key] = (
                str(v).strip().lower() in ("1", "true", "yes", "on")
                if not isinstance(v, bool)
                else v
            )
        elif f.kind == "select" and f.options and str(v) not in f.options:
            problems.append(f"{name} must be one of {', '.join(f.options)}")
    return out, problems


def backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter, for reconnect loops."""
    import random

    return random.uniform(0, min(cap, base * (2 ** min(attempt, 10))))
