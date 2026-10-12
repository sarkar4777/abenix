"""MessagePack documents."""

from __future__ import annotations

from typing import Any

from app.telemetry.decoders.base import DecodeError, DocumentDecoder


class MsgpackDecoder(DocumentDecoder):
    name = "msgpack"
    label = "MessagePack"
    description = "A MessagePack map or a list of maps. The mapping picks the asset, time and signals."
    config_fields = ()

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        try:
            import msgpack
        except ImportError:  # pragma: no cover
            raise DecodeError(
                "MessagePack needs the msgpack package on the ingest"
            ) from None
        try:
            doc = msgpack.unpackb(payload, raw=False, strict_map_key=False)
        except Exception as exc:  # noqa: BLE001
            raise DecodeError(f"This is not MessagePack: {exc}") from None
        return doc if isinstance(doc, list) else [doc]
