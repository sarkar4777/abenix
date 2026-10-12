"""A bare number, or name=value pairs, as simple sensors and scripts send them."""

from __future__ import annotations

import re
from typing import Any

from app.telemetry.connectors.base import ConfigField
from app.telemetry.decoders.base import DecodeError, DocumentDecoder

_PAIR = re.compile(r"([A-Za-z_][\w/.\-]*)\s*[=:]\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


class TextNumberDecoder(DocumentDecoder):
    name = "text_number"
    label = "Plain number"
    description = 'A bare number such as 21.5, or pairs such as "temp=21.5 hum=40". The signal name comes from the subject when there is none.'
    config_fields = (
        ConfigField(
            key="signal",
            label="Signal name",
            kind="string",
            required=False,
            description="Name for a bare number. Empty uses the last subject level.",
        ),
    )

    def parse(self, payload: bytes, config: dict[str, Any]) -> list[Any]:
        text = payload.decode("utf-8", "replace").strip()
        if not text:
            raise DecodeError("The message is empty")
        pairs = _PAIR.findall(text)
        if pairs:
            return [{k: float(v) for k, v in pairs}]
        try:
            v = float(text.split()[0])
        except ValueError:
            raise DecodeError(f"{text[:40]!r} is not a number") from None
        return [{str(config.get("signal") or "value"): v}]
