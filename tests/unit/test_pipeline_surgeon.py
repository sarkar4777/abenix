"""Pipeline Surgeon: patch shape, allow-list validator, risk default."""

from __future__ import annotations

import copy
import json

import pytest

from engine.pipeline_surgeon import (
    _SYSTEM_PROMPT,
    normalize_risk_level,
    propose_patch,
    validate_patch,
)

REGISTRY = [
    {"name": "web_search", "description": "Search the web."},
    {"name": "calculator", "description": "Do maths."},
    {"name": "json_validator", "description": "Validate a JSON shape."},
]


def _dsl() -> dict:
    # Same shape the API passes: {"pipeline_config": agent.model_config.pipeline_config}
    return {
        "pipeline_config": {
            "nodes": [
                {"id": "fetch", "type": "tool", "tool": "web_search", "input": "x"},
                {
                    "id": "calc",
                    "type": "tool",
                    "tool": "calculator",
                    "depends_on": ["fetch"],
                    "arguments": {"expression": "{fetch.total}"},
                },
                {
                    "id": "summ",
                    "type": "agent",
                    "agent_slug": "summarizer",
                    "depends_on": ["calc"],
                },
                {
                    "id": "report",
                    "type": "structured",
                    "depends_on": ["summ"],
                    "output": {"text": "{summ}"},
                },
            ]
        }
    }


def test_prompt_describes_real_shape():
    assert "pipeline_config.nodes" in _SYSTEM_PROMPT
    assert "model_config.pipeline_config" not in _SYSTEM_PROMPT
    assert "/pipeline_config/nodes/<index>" in _SYSTEM_PROMPT


def test_surgeon_shaped_patch_applies_to_real_dsl():
    before = _dsl()
    patch = [
        {"op": "add", "path": "/pipeline_config/nodes/1/on_error", "value": "continue"},
        {
            "op": "replace",
            "path": "/pipeline_config/nodes/1/arguments/expression",
            "value": "{fetch.total|default:0}",
        },
    ]
    after = validate_patch(before, patch, REGISTRY)
    nodes = after["pipeline_config"]["nodes"]
    assert nodes[1]["on_error"] == "continue"
    assert nodes[1]["arguments"]["expression"] == "{fetch.total|default:0}"
    # Input is untouched.
    assert before == _dsl()


def test_defensive_node_can_be_inserted_mid_graph():
    patch = [
        {
            "op": "add",
            "path": "/pipeline_config/nodes/-",
            "value": {
                "id": "guard",
                "type": "tool",
                "tool": "json_validator",
                "depends_on": ["fetch"],
            },
        },
        {"op": "replace", "path": "/pipeline_config/nodes/1/depends_on", "value": ["guard"]},
    ]
    after = validate_patch(_dsl(), patch, REGISTRY)
    ids = [n["id"] for n in after["pipeline_config"]["nodes"]]
    assert "guard" in ids


@pytest.mark.parametrize("op", ["remove", "move", "copy"])
def test_destructive_ops_rejected(op):
    patch = [{"op": op, "path": "/pipeline_config/nodes/1", "from": "/pipeline_config/nodes/0"}]
    if op == "remove":
        patch[0].pop("from")
    with pytest.raises(ValueError, match="not allowed"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_node_removal_via_replace_rejected():
    nodes = copy.deepcopy(_dsl()["pipeline_config"]["nodes"])
    patch = [
        {
            "op": "replace",
            "path": "/pipeline_config/nodes/1",
            "value": {**nodes[1], "id": "calc2"},
        },
    ]
    with pytest.raises(ValueError, match="removes node"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_node_id_change_rejected():
    patch = [{"op": "replace", "path": "/pipeline_config/nodes/1/id", "value": "zzz"}]
    with pytest.raises(ValueError, match="node id"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_paths_outside_nodes_rejected():
    for path in ["/pipeline_config/nodes", "/pipeline_config/input_schema", "/foo"]:
        with pytest.raises(ValueError, match="must target"):
            validate_patch(_dsl(), [{"op": "add", "path": path, "value": 1}], REGISTRY)


def test_unknown_tool_rejected():
    patch = [{"op": "replace", "path": "/pipeline_config/nodes/1/tool", "value": "nope"}]
    with pytest.raises(ValueError, match="unknown tool 'nope'"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_internal_tool_names_allowed():
    patch = [
        {"op": "replace", "path": "/pipeline_config/nodes/1/tool", "value": "agent_step"}
    ]
    validate_patch(_dsl(), patch, REGISTRY)


def test_cycle_rejected():
    # fetch -> calc -> summ -> report, make calc depend on summ too.
    patch = [
        {
            "op": "replace",
            "path": "/pipeline_config/nodes/1/depends_on",
            "value": ["fetch", "summ"],
        }
    ]
    with pytest.raises(ValueError, match="cycle"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_dangling_dependency_rejected():
    patch = [
        {"op": "replace", "path": "/pipeline_config/nodes/1/depends_on", "value": ["ghost"]}
    ]
    with pytest.raises(ValueError, match="missing node ghost"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_entry_and_exit_nodes_must_stay():
    new_entry = [
        {
            "op": "add",
            "path": "/pipeline_config/nodes/-",
            "value": {"id": "x", "type": "tool", "tool": "calculator"},
        }
    ]
    with pytest.raises(ValueError, match="entry nodes"):
        validate_patch(_dsl(), new_entry, REGISTRY)
    new_exit = [
        {
            "op": "add",
            "path": "/pipeline_config/nodes/-",
            "value": {
                "id": "x",
                "type": "tool",
                "tool": "calculator",
                "depends_on": ["fetch"],
            },
        }
    ]
    with pytest.raises(ValueError, match="exit nodes"):
        validate_patch(_dsl(), new_exit, REGISTRY)


def test_node_kind_change_rejected():
    patch = [{"op": "replace", "path": "/pipeline_config/nodes/1/type", "value": "agent"}]
    with pytest.raises(ValueError, match="kind of node"):
        validate_patch(_dsl(), patch, REGISTRY)


def test_patch_size_and_shape_limits():
    with pytest.raises(ValueError, match="non-empty"):
        validate_patch(_dsl(), [], REGISTRY)
    too_many = [
        {"op": "add", "path": "/pipeline_config/nodes/1/on_error", "value": "continue"}
    ] * 9
    with pytest.raises(ValueError, match="too large"):
        validate_patch(_dsl(), too_many, REGISTRY)


@pytest.mark.parametrize(
    "raw,expected",
    [("low", "low"), ("Medium", "medium"), ("high", "high"), ("yolo", "high"),
     (None, "high"), ("", "high"), (3, "high")],
)
def test_unknown_risk_defaults_to_high(raw, expected):
    assert normalize_risk_level(raw) == expected


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeRouter:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def complete(self, **kw):
        self.calls.append(kw)
        return _Resp("```json\n" + json.dumps(self.payload) + "\n```\nDone.")


@pytest.mark.asyncio
async def test_propose_patch_end_to_end():
    router = _FakeRouter(
        {
            "title": "Continue past calc failures",
            "rationale": "calc is non-critical.",
            "confidence": 0.8,
            "risk_level": "weird",
            "json_patch": [
                {"op": "add", "path": "/pipeline_config/nodes/1/on_error", "value": "continue"}
            ],
        }
    )
    out = await propose_patch(
        llm_router=router,
        model="m",
        dsl_before=_dsl(),
        failure={"node_id": "calc"},
        recent_successes=[],
        tool_registry=REGISTRY,
    )
    assert out["risk_level"] == "high"
    assert out["dsl_after"]["pipeline_config"]["nodes"][1]["on_error"] == "continue"
    assert out["dsl_before"] == _dsl()
    assert router.calls[0]["system"] == _SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_propose_patch_rejects_node_removal():
    router = _FakeRouter(
        {
            "title": "Drop calc",
            "confidence": 0.9,
            "risk_level": "low",
            "json_patch": [{"op": "remove", "path": "/pipeline_config/nodes/1"}],
        }
    )
    with pytest.raises(ValueError, match="not allowed"):
        await propose_patch(
            llm_router=router,
            model="m",
            dsl_before=_dsl(),
            failure={},
            recent_successes=[],
            tool_registry=REGISTRY,
        )
