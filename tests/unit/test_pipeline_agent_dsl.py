"""Tests for the `type: 'agent'` pipeline DSL — schema, engine dispatch, router.

Covers the PM-blocker fix where every node had to be `type: 'tool'` because
PipelineNodeSchema required `tool_name`. Now nodes can be `type: 'agent'`
with an `agent_id` or `agent_slug`, and the engine routes through the
`agent_step` tool.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.pipelines import PipelineNodeSchema
from engine.pipeline import (
    PipelineExecutor,
    parse_pipeline_nodes,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


# ── Schema tests ────────────────────────────────────────────────────


def test_schema_accepts_agent_type_with_slug() -> None:
    n = PipelineNodeSchema(id="x", type="agent", agent_slug="research-agent")
    assert n.type == "agent"
    assert n.agent_slug == "research-agent"
    assert n.tool_name is None


def test_schema_accepts_agent_type_with_id() -> None:
    n = PipelineNodeSchema(id="x", type="agent", agent_id="aaa-bbb")
    assert n.type == "agent"
    assert n.agent_id == "aaa-bbb"


def test_schema_rejects_agent_type_without_id_or_slug() -> None:
    with pytest.raises(ValidationError):
        PipelineNodeSchema(id="x", type="agent")


def test_schema_back_compat_tool_default() -> None:
    # No type given → defaults to "tool" → tool_name required
    n = PipelineNodeSchema(id="x", tool_name="search")
    assert n.type == "tool"
    assert n.tool_name == "search"


def test_schema_rejects_tool_type_without_tool_name() -> None:
    with pytest.raises(ValidationError):
        PipelineNodeSchema(id="x", type="tool")


# ── Engine tests ────────────────────────────────────────────────────


class _StubAgentStep(BaseTool):
    """In-memory stand-in for AgentStepTool — records the args it was called with."""

    name = "agent_step"
    description = "stub"
    input_schema = {"type": "object", "properties": {}}
    captured: dict[str, Any] = {}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        type(self).captured = dict(arguments)
        return ToolResult(content='{"response": "stub-agent-output"}')


@pytest.mark.asyncio
async def test_engine_reports_unknown_dependency_without_raising() -> None:
    """A node depending on a non-existent upstream node should NOT raise.

    The engine must return a PipelineResult(status='failed') with a
    node_errors entry so the router can surface a 200+failed body.
    """
    registry = ToolRegistry()
    executor = PipelineExecutor(tool_registry=registry, timeout_seconds=10)

    raw_nodes = [
        {"id": "n1", "type": "tool", "tool_name": "echo", "depends_on": ["ghost"]},
    ]
    nodes = parse_pipeline_nodes(raw_nodes)
    result = await executor.execute(nodes, {})
    assert result.status == "failed"
    assert "n1" in result.node_errors
    assert "unknown dependency" in result.node_errors["n1"]


@pytest.mark.asyncio
async def test_engine_dispatches_agent_step_for_agent_node(monkeypatch) -> None:
    """A type:'agent' node must route through the agent_step tool."""
    registry = ToolRegistry()
    stub = _StubAgentStep()
    registry.register(stub)
    # The engine resolves agent_slug → system_prompt via DB; bypass that
    # with a monkeypatch so the test stays offline.
    from engine import pipeline as pipeline_module

    async def _fake_resolve(self, slug):
        return {"system_prompt": f"You are {slug}", "model_config": {"model": "x"}}

    monkeypatch.setattr(
        pipeline_module.PipelineExecutor,
        "_resolve_agent_by_slug",
        _fake_resolve,
    )

    raw_nodes = [
        {
            "id": "summarise",
            "type": "agent",
            "agent_slug": "research-agent",
            "input": "Summarise the project status",
        }
    ]
    nodes = parse_pipeline_nodes(raw_nodes)
    # parse_pipeline_nodes maps type:agent → tool_name='agent_step' AND
    # carries the agent_slug onto the PipelineNode so the executor's
    # agent_slug branch fires.
    assert nodes[0].tool_name == "agent_step"
    assert nodes[0].agent_slug == "research-agent"
    assert nodes[0].node_type == "agent"

    executor = PipelineExecutor(tool_registry=registry, timeout_seconds=10)
    result = await executor.execute(nodes, {})
    assert result.status == "completed"
    # Stub recorded the dispatched arguments — proves the agent_step tool
    # was invoked rather than skipped or routed elsewhere.
    assert _StubAgentStep.captured.get("input_message") == "Summarise the project status"
    assert "You are research-agent" in _StubAgentStep.captured.get("system_prompt", "")


@pytest.mark.asyncio
async def test_engine_completes_mixed_tool_and_agent_pipeline(monkeypatch) -> None:
    """A pipeline mixing tool nodes and agent nodes should run end-to-end."""

    class _EchoTool(BaseTool):
        name = "echo"
        description = "echo"
        input_schema = {"type": "object", "properties": {}}

        async def execute(self, arguments):
            return ToolResult(content=str(arguments.get("value", "")))

    registry = ToolRegistry()
    registry.register(_EchoTool())
    registry.register(_StubAgentStep())

    from engine import pipeline as pipeline_module

    async def _fake_resolve(self, slug):
        return {"system_prompt": "system", "model_config": {}}

    monkeypatch.setattr(
        pipeline_module.PipelineExecutor,
        "_resolve_agent_by_slug",
        _fake_resolve,
    )

    raw_nodes = [
        {"id": "first", "type": "tool", "tool_name": "echo", "arguments": {"value": "hello"}},
        {
            "id": "second",
            "type": "agent",
            "agent_slug": "writer",
            "depends_on": ["first"],
            "input": "Process the upstream output",
        },
    ]
    nodes = parse_pipeline_nodes(raw_nodes)
    executor = PipelineExecutor(tool_registry=registry, timeout_seconds=10)
    result = await executor.execute(nodes, {})
    assert result.status == "completed"
    assert "first" in result.execution_path
    assert "second" in result.execution_path
