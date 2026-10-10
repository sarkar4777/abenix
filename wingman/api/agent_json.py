"""Pull the JSON answer out of an agent's final message."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.DOTALL)


def parse_agent_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        whole = json.loads(raw)
        if isinstance(whole, dict):
            return whole
    except (TypeError, ValueError):
        pass

    # agents often narrate their steps and end with a fenced block, last one wins
    for block in reversed(_FENCE.findall(raw)):
        try:
            obj = json.loads(block.strip())
        except ValueError:
            continue
        if isinstance(obj, dict):
            return obj

    # prose braces break a first-to-last slice, so decode every top-level object
    decoder = json.JSONDecoder()
    best: dict[str, Any] = {}
    best_len = 0
    i = raw.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(raw, i)
        except ValueError:
            i = raw.find("{", i + 1)
            continue
        if isinstance(obj, dict) and end - i >= best_len:
            best, best_len = obj, end - i
        i = raw.find("{", end)
    return best
