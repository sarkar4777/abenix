"""Tests for engine.pipeline.PipelineExecutor with fake in-process tools.

The executor is the heart of every multi-step agent. These tests build
ToolRegistry instances backed by trivial in-memory tools so the DAG
behaviour (parallel layers, failure propagation, cost cap, conditional
skip, template piping) can be verified without LLM calls or DB writes.
"""

from __future__ import annotations

from typing import Any

import pytest

from engine.pipeline import (
    PipelineExecutor,
    parse_pipeline_nodes,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult

# ── Fake tools ──────────────────────────────────────────────────────


class _EchoTool(BaseTool):
    """Returns its `value` argument as the output content."""

    name = "echo"
    description = "Echo a value back."
    input_schema = {"type": "object", "properties": {"value": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=str(arguments.get("value", "")))


class _UppercaseTool(BaseTool):
    name = "uppercase"
    description = "Uppercase the input string."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=str(arguments.get("text", "")).upper())


class _BoomTool(BaseTool):
    """Always returns is_error=True with the given message."""

    name = "boom"
    description = "Always errors."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="forced failure", is_error=True)


class _CounterTool(BaseTool):
    """Records every invocation so tests can assert on call counts."""

    name = "counter"
    description = "Increments an internal counter on each call."
    input_schema = {"type": "object", "properties": {"label": {"type": "string"}}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return ToolResult(content=f"call #{len(self.calls)}")


class _PaidTool(BaseTool):
    """Reports a per-call cost via metadata so the executor's cost cap can be exercised."""

    name = "paid"
    description = "Costs $0.50 per call."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="ok", metadata={"cost": 0.5})


def _registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── Linear + parallel DAGs ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_runs_single_node():
    nodes = parse_pipeline_nodes(
        [{"id": "s1", "type": "tool", "tool": "echo", "arguments": {"value": "hello"}}]
    )
    ex = PipelineExecutor(_registry(_EchoTool()))
    result = await ex.execute(nodes)
    assert result.status == "completed"
    assert result.execution_path == ["s1"]
    assert result.node_results["s1"].status == "completed"
    assert result.node_results["s1"].output == "hello"


@pytest.mark.asyncio
async def test_executor_chains_outputs_via_template():
    nodes = parse_pipeline_nodes(
        [
            {
                "id": "s1",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "abenix"},
            },
            {
                "id": "s2",
                "type": "tool",
                "tool": "uppercase",
                "arguments": {"text": "{{s1}}"},
            },
        ]
    )
    ex = PipelineExecutor(_registry(_EchoTool(), _UppercaseTool()))
    result = await ex.execute(nodes)
    assert result.status == "completed"
    assert result.node_results["s2"].output == "ABENIX"


@pytest.mark.asyncio
async def test_executor_parallel_branches_share_a_layer():
    """Two independent nodes after a common ancestor should run in the
    same topological layer; both must succeed."""
    nodes = parse_pipeline_nodes(
        [
            {
                "id": "root",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "go"},
            },
            {
                "id": "left",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "{{root}}"},
                "depends_on": ["root"],
            },
            {
                "id": "right",
                "type": "tool",
                "tool": "uppercase",
                "arguments": {"text": "{{root}}"},
                "depends_on": ["root"],
            },
        ]
    )
    ex = PipelineExecutor(_registry(_EchoTool(), _UppercaseTool()))
    result = await ex.execute(nodes)
    assert result.status == "completed"
    assert {n for n in result.execution_path} == {"root", "left", "right"}
    assert result.node_results["left"].output == "go"
    assert result.node_results["right"].output == "GO"


# ── Failure handling ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_marks_failed_node_and_aggregates_errors():
    nodes = parse_pipeline_nodes([{"id": "s1", "type": "tool", "tool": "boom"}])
    ex = PipelineExecutor(_registry(_BoomTool()))
    result = await ex.execute(nodes)
    assert result.status == "failed"
    assert result.failed_nodes == ["s1"]
    assert "s1" in result.node_errors


@pytest.mark.asyncio
async def test_executor_unknown_tool_yields_failed_node():
    """Pipelines that reference a tool not in the registry must fail
    cleanly (NodeResult.status='failed', error='Unknown tool'), not
    raise an uncaught exception."""
    nodes = parse_pipeline_nodes([{"id": "s1", "type": "tool", "tool": "ghost"}])
    ex = PipelineExecutor(_registry(_EchoTool()))
    result = await ex.execute(nodes)
    assert result.status == "failed"
    assert result.failed_nodes == ["s1"]
    assert "Unknown tool" in (
        result.node_results["s1"].error or result.node_results["s1"].error_message or ""
    )


@pytest.mark.asyncio
async def test_executor_continues_after_failure_when_on_error_continue():
    """A failing node with on_error='continue' must let downstream
    siblings still run. Critical for fan-out style pipelines.

    Contract: the per-node result still records status='failed' (so the
    UI can surface it), but result.failed_nodes excludes it because the
    pipeline as a whole succeeded — on_error=continue is the operator
    explicitly opting out of pipeline-level failure for that node.
    """
    nodes = parse_pipeline_nodes(
        [
            {"id": "fail", "type": "tool", "tool": "boom", "on_error": "continue"},
            {
                "id": "ok",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "still ran"},
            },
        ]
    )
    ex = PipelineExecutor(_registry(_BoomTool(), _EchoTool()))
    result = await ex.execute(nodes)
    # Node-level: the failing node IS marked failed in its NodeResult
    assert result.node_results["fail"].status == "failed"
    # Pipeline-level: it does NOT count toward failed_nodes — the
    # operator explicitly tolerated its failure
    assert "fail" not in result.failed_nodes
    # Downstream node ran normally
    assert "ok" in result.execution_path
    assert result.node_results["ok"].output == "still ran"


# ── Cost cap ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_enforces_cost_limit():
    """Set cost_limit=$0.4 and run two $0.50 calls — first runs (the
    pre-flight check uses accumulated_cost which is still $0 going in),
    second is short-circuited because accumulated_cost is now $0.50 ≥
    $0.40. Net effect: pipelines can't run away on cost."""
    nodes = parse_pipeline_nodes(
        [
            {"id": "first", "type": "tool", "tool": "paid"},
            {"id": "second", "type": "tool", "tool": "paid", "depends_on": ["first"]},
        ]
    )
    ex = PipelineExecutor(_registry(_PaidTool()), cost_limit=0.4)
    result = await ex.execute(nodes)
    assert result.node_results["first"].status == "completed"
    assert result.node_results["second"].status == "failed"
    err = (result.node_results["second"].error or "").lower()
    assert "budget" in err or "cost" in err


# ── Per-node retries ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_invokes_tool_once_when_no_retries():
    counter = _CounterTool()
    nodes = parse_pipeline_nodes(
        [{"id": "s1", "type": "tool", "tool": "counter", "arguments": {"label": "x"}}]
    )
    ex = PipelineExecutor(_registry(counter))
    await ex.execute(nodes)
    assert len(counter.calls) == 1


# ── Callbacks ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_fires_on_node_complete_callback():
    """The streaming UI relies on per-node callbacks; missing fires
    means the live-debug timeline goes dark.

    Callback signature is (node_id, status, duration_ms, output,
    error_message, error_type) — exactly the fields the UI's live
    timeline needs to render a step."""
    seen = []

    async def cb(node_id, status, duration_ms, output, error_message, error_type):
        seen.append((node_id, status))

    nodes = parse_pipeline_nodes(
        [
            {"id": "a", "type": "tool", "tool": "echo", "arguments": {"value": "1"}},
            {
                "id": "b",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "{{a}}"},
                "depends_on": ["a"],
            },
        ]
    )
    ex = PipelineExecutor(_registry(_EchoTool()), on_node_complete=cb)
    await ex.execute(nodes)
    assert {nid for nid, _ in seen} == {"a", "b"}
    assert all(status == "completed" for _, status in seen)


# ── Result envelope ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_executor_records_total_duration_and_path():
    nodes = parse_pipeline_nodes(
        [
            {"id": "a", "type": "tool", "tool": "echo", "arguments": {"value": "x"}},
            {
                "id": "b",
                "type": "tool",
                "tool": "echo",
                "arguments": {"value": "{{a}}"},
                "depends_on": ["a"],
            },
        ]
    )
    ex = PipelineExecutor(_registry(_EchoTool()))
    result = await ex.execute(nodes)
    assert result.total_duration_ms >= 0
    assert result.execution_path == ["a", "b"]
    assert result.final_output == "x"  # last node's output is the final
