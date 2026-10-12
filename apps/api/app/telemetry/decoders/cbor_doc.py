"""CBOR documents."""

from __future__ import annotations

from typing import Any

from app.telemetry.decoders.base import DecodeError, DocumentDecoder


class CborDecoder(DocumentDecoder):
    name = "cbor"
    label = "CBOR"
    description = "A CBOR map or a list of maps, as constrained devices send them."
    config_fields = ()

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        try:
            import cbor2
        except ImportError:  # pragma: no cover
            raise DecodeError("CBOR needs the cbor2 package on the ingest") from None
        try:
            doc = cbor2.loads(payload)
        except Exception as exc:  # noqa: BLE001
            raise DecodeError(f"This is not CBOR: {exc}") from None
        return doc if isinstance(doc, list) else [doc]
