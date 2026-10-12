"""JSON documents, one object or a list. NDJSON is read too when the payload has several lines."""

from __future__ import annotations

import json
from typing import Any

from app.telemetry.decoders.base import DecodeError, DocumentDecoder


class JsonDecoder(DocumentDecoder):
    name = "json"
    label = "JSON"
    description = "One JSON object or a list of them. The mapping picks the asset, time and signals."
    config_fields = ()

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        text = payload.decode("utf-8", "replace").strip()
        if not text:
            raise DecodeError("The message is empty")
        try:
            doc = json.loads(text)
        except ValueError as exc:
            if "\n" in text:
                from app.telemetry.decoders.json_lines import parse_lines

                return parse_lines(text)
            raise DecodeError(
                f"This is not JSON: {exc.msg} at character {exc.pos}"
            ) from None
        return doc if isinstance(doc, list) else [doc]
