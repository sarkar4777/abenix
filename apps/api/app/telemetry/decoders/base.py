"""The decoder side of the telemetry pipeline: bytes from a transport into Records.

Add a format by dropping a module in this package that defines a Decoder
subclass. A decoder that reads structured documents (JSON, CSV, Avro, ...)
usually subclasses DocumentDecoder, implements parse() and lets the
connection's mapping build the Records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar

from app.telemetry.connectors.base import ConfigField, Envelope

__all__ = [
    "DecodeError",
    "MappingError",
    "Skipped",
    "Decoder",
    "DecoderState",
    "DocumentDecoder",
    "Metric",
    "Record",
    "KINDS",
    "TYPES",
    "QUALITIES",
]

KINDS = ("data", "birth", "death", "state", "frame", "event")
TYPES = ("number", "bool", "string", "json", "bytes")
QUALITIES = ("good", "uncertain", "bad")


@dataclass(slots=True)
class Metric:
    name: str
    value: Any
    # number, bool, string, json or bytes
    type: str = "number"
    unit: str | None = None
    # event time in epoch ms, None means the receive time
    ts: int | None = None
    quality: str = "good"
    # the source's own type name when it has one, such as Sparkplug's Int32
    source_type: str | None = None
    # history only, the latest value is not moved
    historical: bool = False


@dataclass(slots=True)
class Record:
    group: str
    node: str
    device: str = ""
    # data, birth, death, state, frame or event
    kind: str = "data"
    metrics: list[Metric] = field(default_factory=list)
    seq: int | None = None
    # event time of the record in epoch ms
    ts: int | None = None
    # kind frame: [{t, id, data, dlc}]
    frames: list[dict[str, Any]] = field(default_factory=list)
    # kind event: the whole message, and its name such as order.created
    event: dict[str, Any] | None = None
    event_name: str | None = None
    # decoder notes for the store, such as {"cascade": True} on a node death
    meta: dict[str, Any] = field(default_factory=dict)


class DecodeError(Exception):
    """Raised with the reason in plain words. The message goes to the dead-letter ring."""


class MappingError(DecodeError):
    """The payload was read, the mapping could not turn it into records."""


class Skipped(Exception):
    """The mapping's filter left this message out on purpose. Counted, never dead-lettered."""


Lookup = Callable[..., Awaitable[Any]]


@dataclass
class DecoderState:
    """Per connection and replica. config is the decoder's settings, data is a stateful decoder's own."""

    config: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    # async reads of the store, for stateful decoders after a handover: lookup(kind, tenant, group, node, device)
    lookup: Lookup | None = None
    # what the decoder asks the pipeline to send back, such as a Sparkplug rebirth: (subject, payload bytes)
    outbox: list[tuple[str, bytes]] = field(default_factory=list)
    # counters the pipeline adds to the workspace stats, such as rebirths
    stats: dict[str, int] = field(default_factory=dict)
    # every replica reads this connection, so per-node ordering is not guaranteed
    shared: bool = False


class Decoder:
    name: ClassVar[str] = ""
    label: ClassVar[str] = ""
    description: ClassVar[str] = ""
    config_fields: ClassVar[tuple[ConfigField, ...]] = ()
    stateful: ClassVar[bool] = False
    # whether the connection's mapping applies
    uses_mapping: ClassVar[bool] = True

    def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record] | Awaitable[list[Record]]:
        """Records from one envelope. May be async. Raise DecodeError with a plain reason."""
        raise NotImplementedError

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "name": cls.name,
            "label": cls.label,
            "description": cls.description,
            "config_fields": [f.to_dict() for f in cls.config_fields],
            "stateful": cls.stateful,
            "uses_mapping": cls.uses_mapping,
        }


class DocumentDecoder(Decoder):
    """Parses the payload into documents, the mapping turns each document into Records."""

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        raise NotImplementedError

    def decode(
        self, envelope: Envelope, state: DecoderState, mapping: dict[str, Any] | None
    ) -> list[Record]:
        from app.telemetry import mapping as M

        docs = self.parse(envelope.payload, state.config)
        out: list[Record] = []
        skips: list[str] = []
        for doc in docs:
            out.extend(M.apply(doc, envelope, mapping or {}, skips))
        if not out and skips:
            raise Skipped(skips[0])
        return out
