"""Newline-delimited JSON, one document a line."""

from __future__ import annotations

import json
from typing import Any

from app.telemetry.decoders.base import DecodeError, DocumentDecoder


def parse_lines(text: str) -> list[Any]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError as exc:
            raise DecodeError(f"Line {i} is not JSON: {exc.msg}") from None
    return out


class JsonLinesDecoder(DocumentDecoder):
    name = "json_lines"
    label = "JSON lines (NDJSON)"
    description = (
        "One JSON document a line, as log shippers and batch pushers send them."
    )
    config_fields = ()

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        return parse_lines(payload.decode("utf-8", "replace"))
