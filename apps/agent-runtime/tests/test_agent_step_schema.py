"""An agent step holds its answer to the agent's declared output_schema."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from engine.post_process import post_process, schema_violations
from engine.tools.agent_step import _hold_to_schema

SCHEMA = {
    "type": "object",
    "required": ["coded_terms", "uncoded"],
    "properties": {
        "coded_terms": {
            "type": "array",
            "items": {"type": "object", "required": ["verbatim", "pt"]},
        },
        "uncoded": {"type": "array"},
    },
}
BAD = json.dumps({"coded_terms": [{"verbatim": "weakness", "pt": None}], "uncoded": []})
GOOD = json.dumps(
    {"coded_terms": [], "uncoded": [{"verbatim": "weakness", "reason": "no match"}]}
)


class Router:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    async def complete(self, **kw):
        self.calls += 1
        return SimpleNamespace(content=self.reply)


def test_null_required_field_is_a_violation():
    _, warns = post_process(BAD, SCHEMA)
    assert schema_violations(warns)


@pytest.mark.asyncio
async def test_violation_gets_one_corrective_retry():
    r = Router(GOOD)
    out, left = await _hold_to_schema(r, SCHEMA, "sys", "m", 0.0, "task", BAD)
    assert out == GOOD and left == [] and r.calls == 1


@pytest.mark.asyncio
async def test_worse_fix_keeps_original_and_reports():
    r = Router("not json at all")
    out, left = await _hold_to_schema(r, SCHEMA, "sys", "m", 0.0, "task", BAD)
    assert out == BAD and left


@pytest.mark.asyncio
async def test_valid_or_schemaless_output_passes_untouched():
    r = Router(GOOD)
    assert await _hold_to_schema(r, SCHEMA, "s", "m", 0, "t", GOOD) == (GOOD, [])
    assert await _hold_to_schema(r, None, "s", "m", 0, "t", BAD) == (BAD, [])
    assert r.calls == 0
