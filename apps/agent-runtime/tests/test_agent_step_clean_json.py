"""A pipeline agent step passes on the JSON its schema asks for, not the prose and fences around it."""

from __future__ import annotations

import asyncio
import json

from engine.tools.agent_step import _hold_to_schema

SCHEMA = {
    "type": "object",
    "required": ["action", "reason"],
    "properties": {"action": {"type": "string"}, "reason": {"type": "string"}},
}


def test_prose_with_a_fenced_answer_becomes_clean_json():
    raw = 'Both cranes are within limits.\n```json\n{"action": "continue", "reason": "wind 8 m/s"}\n```'
    out, bad = asyncio.run(_hold_to_schema(None, SCHEMA, "", "m", 0, "task", raw))
    assert bad == []
    assert json.loads(out) == {"action": "continue", "reason": "wind 8 m/s"}


def test_agents_without_a_schema_pass_through_untouched():
    raw = "free text answer"
    out, bad = asyncio.run(_hold_to_schema(None, None, "", "m", 0, "task", raw))
    assert out == raw and bad == []
