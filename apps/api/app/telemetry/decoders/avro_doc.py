"""Avro, schemaless datums, Confluent framing or object container files."""

from __future__ import annotations

import io
import json
from typing import Any

from app.telemetry.connectors.base import ConfigField
from app.telemetry.decoders.base import DecodeError, DocumentDecoder


class AvroDecoder(DocumentDecoder):
    name = "avro"
    label = "Avro"
    description = "Avro records read with the schema you give. Confluent framing and container files work too."
    config_fields = (
        ConfigField(
            key="schema",
            label="Schema (JSON)",
            kind="string",
            required=False,
            description="The writer schema. Container files carry their own.",
        ),
        ConfigField(
            key="framing",
            label="Framing",
            kind="select",
            required=False,
            default="auto",
            options=("auto", "raw", "confluent", "container"),
        ),
    )

    _cache: dict[str, Any] = {}

    def _schema(self, text: str) -> Any:
        import fastavro

        hit = self._cache.get(text)
        if hit is None:
            try:
                hit = fastavro.parse_schema(json.loads(text))
            except Exception as exc:  # noqa: BLE001
                raise DecodeError(f"The Avro schema did not load: {exc}") from None
            self._cache[text] = hit
        return hit

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        try:
            import fastavro
        except ImportError:  # pragma: no cover
            raise DecodeError("Avro needs the fastavro package on the ingest") from None
        framing = config.get("framing") or "auto"
        if framing == "container" or (framing == "auto" and payload[:4] == b"Obj\x01"):
            try:
                return list(fastavro.reader(io.BytesIO(payload)))
            except Exception as exc:  # noqa: BLE001
                raise DecodeError(
                    f"This is not an Avro container file: {exc}"
                ) from None
        if not config.get("schema"):
            raise DecodeError("Give the Avro schema for messages without a container")
        body = payload
        if framing == "confluent" or (
            framing == "auto" and payload[:1] == b"\x00" and len(payload) > 5
        ):
            body = payload[5:]
        schema = self._schema(config["schema"])
        try:
            return [fastavro.schemaless_reader(io.BytesIO(body), schema)]
        except Exception as exc:  # noqa: BLE001
            raise DecodeError(
                f"The message does not match the Avro schema: {exc}"
            ) from None
