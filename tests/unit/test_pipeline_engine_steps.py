"""Steps the engine runs itself need no grant: validation passes them and execution does not refuse them."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.routers import pipelines as router

pytestmark = pytest.mark.asyncio


async def test_validate_does_not_flag_the_output_step():
    body = {
        "tools": ["decision_evaluate"],
        "nodes": [
            {"id": "mode", "tool_name": "decision_evaluate", "arguments": {"decision": "x", "facts": {}}},
            {"id": "result", "tool_name": "__structured__", "arguments": {"mode": "{{mode.result}}"}, "depends_on": ["mode"]},
        ],
    }
    res = await router.validate_pipeline_endpoint(body, user=SimpleNamespace())
    payload = json.loads(res.body)["data"]
    assert not [e for e in payload.get("errors", []) if "not enabled" in e.get("message", "")]


async def test_validate_still_flags_a_real_tool_the_agent_lacks():
    body = {
        "tools": ["decision_evaluate"],
        "nodes": [{"id": "x", "tool_name": "web_search", "arguments": {"query": "q"}}],
    }
    res = await router.validate_pipeline_endpoint(body, user=SimpleNamespace())
    payload = json.loads(res.body)["data"]
    assert any("not enabled" in e.get("message", "") for e in payload.get("errors", []))


def test_engine_steps_match_the_runtime():
    from engine.pipeline_surgeon import INTERNAL_TOOL_NAMES

    assert router.ENGINE_STEPS == INTERNAL_TOOL_NAMES
