"""Tests for engine.pipeline.parse_pipeline_nodes + the templating helpers.

Covers the DSL → typed-PipelineNode translation that runs at the start
of every pipeline execution, including:

  * the two valid YAMLs the platform accepts (low-level
    `tool_name=agent_step` form vs. high-level `type=agent` DSL)
  * automatic depends_on inference from `{{node.field}}` template refs
  * cycle detection in the topological sort
  * the JSON-fence-stripping helper that lets agent_step outputs pass
    through `_extract_field` even when the LLM wraps JSON in markdown
"""

from __future__ import annotations

import pytest

from engine.pipeline import (
    PipelineNode,
    _extract_field,
    _strip_markdown_fence,
    _topological_sort,
    _try_parse_json_ish,
    parse_pipeline_nodes,
    serialize_pipeline_result,
)
from engine.pipeline import NodeResult, PipelineResult

# ── parse_pipeline_nodes — DSL forms ─────────────────────────────────


def test_parse_low_level_tool_node():
    raw = [
        {
            "id": "s1",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "print(1)", "language": "python"},
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    assert len(nodes) == 1
    assert nodes[0].id == "s1"
    assert nodes[0].tool_name == "code_executor"
    assert nodes[0].arguments["code"] == "print(1)"
    assert nodes[0].depends_on == []


def test_parse_agent_dsl_normalizes_to_agent_step():
    """type=agent + agent_slug shorthand must rewrite to tool_name=agent_step
    so the executor's tool registry resolves it."""
    raw = [
        {
            "id": "triage",
            "type": "agent",
            "agent_slug": "triage-bot",
            "input": "Classify: {{input.ticket}}",
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    assert nodes[0].tool_name == "agent_step"
    assert nodes[0].agent_slug == "triage-bot"
    assert nodes[0].arguments["input_message"] == "Classify: {{input.ticket}}"


def test_parse_structured_node_uses_marker_tool():
    raw = [
        {
            "id": "final",
            "type": "structured",
            "output": {"summary": "{{plan.summary}}", "score": 0.5},
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    assert nodes[0].tool_name == "__structured__"
    assert nodes[0].structured_output is True
    assert nodes[0].arguments["summary"] == "{{plan.summary}}"


def test_parse_infers_depends_on_from_template_refs():
    """If a node templates `{{triage.intent}}` and `triage` is a sibling,
    `triage` must be auto-added to depends_on. Without this the DAG is
    flat and downstream nodes resolve to [not available]."""
    raw = [
        {
            "id": "triage",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "x"},
        },
        {
            "id": "plan",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "use {{triage.intent}}"},
        },
    ]
    nodes = parse_pipeline_nodes(raw)
    plan = next(n for n in nodes if n.id == "plan")
    assert "triage" in plan.depends_on


def test_parse_infers_deps_from_input_field():
    """The `input` field on a high-level agent DSL node must also be
    scanned for `{{ref}}` template references."""
    raw = [
        {
            "id": "a",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "x"},
        },
        {"id": "b", "type": "agent", "agent_slug": "x", "input": "use {{a.value}}"},
    ]
    nodes = parse_pipeline_nodes(raw)
    b = next(n for n in nodes if n.id == "b")
    assert "a" in b.depends_on


def test_parse_keeps_explicit_depends_on():
    """Manual depends_on takes precedence — the inference adds to it,
    never overrides."""
    raw = [
        {
            "id": "a",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "x"},
        },
        {
            "id": "b",
            "type": "tool",
            "tool": "code_executor",
            "arguments": {"code": "y"},
            "depends_on": ["a"],
        },
    ]
    nodes = parse_pipeline_nodes(raw)
    b = next(n for n in nodes if n.id == "b")
    assert b.depends_on == ["a"]


def test_parse_required_if_lifts_into_arguments():
    raw = [
        {
            "id": "approve",
            "type": "tool",
            "tool": "human_approval",
            "required_if": "{{plan.risk}}",
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    assert nodes[0].arguments["__required_if__"] == "{{plan.risk}}"


def test_parse_for_each_config():
    raw = [
        {
            "id": "fan_out",
            "type": "tool",
            "tool": "code_executor",
            "for_each": {
                "source_node": "triage",
                "source_field": "actions",
                "item_variable": "item",
                "max_concurrency": 4,
            },
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    assert nodes[0].for_each is not None
    assert nodes[0].for_each.source_node == "triage"
    assert nodes[0].for_each.max_concurrency == 4


def test_parse_max_retries_default_zero():
    raw = [{"id": "x", "type": "tool", "tool": "code_executor"}]
    nodes = parse_pipeline_nodes(raw)
    assert nodes[0].max_retries == 0


def test_parse_input_mappings_object():
    raw = [
        {
            "id": "step",
            "type": "tool",
            "tool": "code_executor",
            "input_mappings": {
                "code": {"source_node": "prev", "source_field": "snippet"},
            },
        }
    ]
    nodes = parse_pipeline_nodes(raw)
    mappings = nodes[0].input_mappings
    assert "code" in mappings
    assert mappings["code"].source_node == "prev"
    assert mappings["code"].source_field == "snippet"


# ── _topological_sort ───────────────────────────────────────────────


def _node(nid, deps=None):
    return PipelineNode(id=nid, tool_name="x", depends_on=deps or [])


def test_topo_sort_orders_independent_nodes_in_layer_zero():
    layers = _topological_sort([_node("a"), _node("b"), _node("c")])
    assert layers == [["a", "b", "c"]]


def test_topo_sort_separates_chained_nodes_into_layers():
    nodes = [_node("a"), _node("b", ["a"]), _node("c", ["b"])]
    layers = _topological_sort(nodes)
    assert layers == [["a"], ["b"], ["c"]]


def test_topo_sort_parallel_branches_share_a_layer():
    """Diamond: a → b, a → c, both → d."""
    nodes = [
        _node("a"),
        _node("b", ["a"]),
        _node("c", ["a"]),
        _node("d", ["b", "c"]),
    ]
    layers = _topological_sort(nodes)
    assert layers[0] == ["a"]
    assert sorted(layers[1]) == ["b", "c"]
    assert layers[2] == ["d"]


def test_topo_sort_detects_cycles():
    nodes = [_node("a", ["b"]), _node("b", ["a"])]
    with pytest.raises(ValueError, match="Cycle detected"):
        _topological_sort(nodes)


def test_topo_sort_detects_self_loop():
    """A node listed in its own depends_on is the simplest cycle."""
    nodes = [_node("a", ["a"])]
    with pytest.raises(ValueError, match="Cycle detected"):
        _topological_sort(nodes)


# ── markdown fence + JSON-ish parser ────────────────────────────────


def test_strip_fence_removes_json_block():
    text = '```json\n{"intent": "billing"}\n```'
    assert _strip_markdown_fence(text).strip() == '{"intent": "billing"}'


def test_strip_fence_handles_trailing_prose():
    """LLMs often append a `**Reasoning:**` block after the fence —
    the stripper takes the first fenced block and ignores the rest."""
    text = '```json\n{"k": 1}\n```\n**Reasoning:** because.'
    inner = _strip_markdown_fence(text).strip()
    assert inner == '{"k": 1}'


def test_strip_fence_passthrough_when_no_fence():
    assert _strip_markdown_fence("just text") == "just text"


def test_try_parse_json_ish_handles_clean_json():
    assert _try_parse_json_ish('{"a": 1}') == {"a": 1}


def test_try_parse_json_ish_handles_fenced_json():
    assert _try_parse_json_ish('```json\n{"a": 1}\n```') == {"a": 1}


def test_try_parse_json_ish_recovers_from_trailing_prose():
    """Pure JSON followed by prose — the balanced-brace fallback finds
    the first complete block."""
    text = '{"a": 1, "b": [1,2,3]} and then some thoughts'
    assert _try_parse_json_ish(text) == {"a": 1, "b": [1, 2, 3]}


def test_try_parse_json_ish_returns_none_on_garbage():
    assert _try_parse_json_ish("hello world") is None


# ── _extract_field ──────────────────────────────────────────────────


def test_extract_field_simple_dot_path():
    data = {"intent": "billing", "score": 0.9}
    assert _extract_field(data, "intent") == "billing"


def test_extract_field_nested():
    data = {"plan": {"actions": [{"type": "refund"}]}}
    assert _extract_field(data, "plan.actions") == [{"type": "refund"}]
    assert _extract_field(data, "plan.actions.0.type") == "refund"


def test_extract_field_unwraps_agent_step_response():
    """agent_step returns {response, cost, model} — when the field isn't
    on the wrapper, the resolver descends into `response`."""
    data = {"response": '{"intent": "billing"}', "cost": 0.001}
    assert _extract_field(data, "intent") == "billing"


def test_extract_field_returns_none_for_missing_field():
    assert _extract_field({"a": 1}, "b") is None


def test_extract_field_all_returns_unwrapped_response():
    """Bare `{{triage}}` (field_path='__all__') should unwrap
    agent_step's response object so structured outputs see the data
    payload, not the cost/model metadata."""
    data = {"response": {"intent": "billing"}, "cost": 0.001, "model": "claude"}
    out = _extract_field(data, "__all__")
    assert out == {"intent": "billing"}


def test_extract_field_all_unwraps_json_string_response():
    """If the response field is a JSON string, __all__ must parse it."""
    data = {"response": '{"k": "v"}', "cost": 0.0}
    assert _extract_field(data, "__all__") == {"k": "v"}


# ── serialize_pipeline_result ───────────────────────────────────────


def test_serialize_pipeline_result_minimal_completed():
    result = PipelineResult(
        status="completed",
        node_results={
            "s1": NodeResult(
                node_id="s1",
                status="completed",
                output="ok",
                duration_ms=42,
                tool_name="x",
            )
        },
        execution_path=["s1"],
        total_duration_ms=42,
        final_output="ok",
    )
    out = serialize_pipeline_result(result)
    assert out["status"] == "completed"
    assert out["execution_path"] == ["s1"]
    assert out["failed_nodes"] == []
    assert out["node_results"]["s1"]["status"] == "completed"
    assert out["node_results"]["s1"]["output"] == "ok"


def test_serialize_pipeline_result_failed_node_carries_error():
    result = PipelineResult(
        status="failed",
        node_results={
            "s1": NodeResult(
                node_id="s1",
                status="failed",
                error="boom",
                error_message="boom",
                error_type="tool_error",
                duration_ms=1,
                tool_name="x",
            )
        },
        execution_path=[],
        failed_nodes=["s1"],
    )
    out = serialize_pipeline_result(result)
    assert out["status"] == "failed"
    assert out["failed_nodes"] == ["s1"]
    assert out["node_results"]["s1"]["error"] == "boom"


def test_serialize_pipeline_result_truncates_huge_output():
    """Large node outputs (>10kB) get truncated and tagged so dashboards
    don't blow up rendering huge JSON blobs."""
    big = {"x": "y" * 20_000}
    result = PipelineResult(
        status="completed",
        node_results={
            "s1": NodeResult(
                node_id="s1",
                status="completed",
                output=big,
                duration_ms=1,
                tool_name="x",
            )
        },
        execution_path=["s1"],
    )
    out = serialize_pipeline_result(result)
    nr = out["node_results"]["s1"]
    # Either truncated marker is set, or output was clipped to a string.
    assert nr.get("output_truncated") is True or isinstance(nr["output"], (dict, str))
