"""A pipeline run's cost includes what failed and retried steps spent."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from engine.pipeline import (
    NodeResult,
    PipelineExecutor,
    PipelineResult,
    node_usage,
    parse_pipeline_nodes,
    pipeline_usage,
    serialize_pipeline_result,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class _Answer(BaseTool):
    name = "answer"
    description = "Answers and reports its spend in the output."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        out = {"response": "ok", "cost": 0.1, "input_tokens": 100, "output_tokens": 10}
        return ToolResult(content=json.dumps(out))


class _OverBudget(BaseTool):
    name = "over_budget"
    description = "Spends money, then stops at its budget."
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            content="Budget exceeded: partial",
            is_error=True,
            metadata={
                "failure_code": "BUDGET_EXCEEDED",
                "cost": 0.25,
                "input_tokens": 300,
                "output_tokens": 30,
            },
        )


class _Flaky(BaseTool):
    name = "flaky"
    description = "Fails once with spend, then succeeds."
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult(
                content="bad json from the model",
                is_error=True,
                metadata={"cost": 0.04, "input_tokens": 40, "output_tokens": 4},
            )
        return ToolResult(
            content="fine",
            metadata={"cost": 0.06, "input_tokens": 60, "output_tokens": 6},
        )


def _registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def test_node_usage_reads_metadata_then_output():
    assert node_usage(NodeResult("a", "failed", metadata={"cost": 0.2}))["cost"] == 0.2
    out = json.dumps({"cost": 0.3, "input_tokens": 5})
    u = node_usage(NodeResult("b", "failed", output=out))
    assert u == {"cost": 0.3, "input_tokens": 5, "output_tokens": 0}
    assert node_usage(NodeResult("c", "failed", output="boom"))["cost"] == 0.0
    flagged = NodeResult("d", "completed", metadata={"cost": True})
    assert node_usage(flagged)["cost"] == 0.0


@pytest.mark.asyncio
async def test_failed_step_spend_counts_toward_the_run():
    nodes = parse_pipeline_nodes(
        [
            {"id": "s1", "type": "tool", "tool": "answer", "arguments": {}},
            {
                "id": "s2",
                "type": "tool",
                "tool": "over_budget",
                "arguments": {},
                "depends_on": ["s1"],
            },
        ]
    )
    result = await PipelineExecutor(_registry(_Answer(), _OverBudget())).execute(nodes)
    assert result.status != "completed"
    assert pipeline_usage(result) == {
        "cost": 0.35,
        "input_tokens": 400,
        "output_tokens": 40,
    }
    ser = serialize_pipeline_result(result)
    assert ser["cost"] == 0.35
    assert ser["input_tokens"] == 400
    # failed nodes carry no output in the record, only their metadata
    assert "output" not in ser["node_results"]["s2"]
    assert ser["node_results"]["s2"]["metadata"]["cost"] == 0.25


@pytest.mark.asyncio
async def test_retried_step_keeps_the_spend_of_earlier_attempts():
    flaky = _Flaky()
    nodes = parse_pipeline_nodes(
        [
            {
                "id": "s1",
                "type": "tool",
                "tool": "flaky",
                "arguments": {},
                "max_retries": 1,
                "retry_delay_ms": 1,
            }
        ]
    )
    result = await PipelineExecutor(_registry(flaky)).execute(nodes)
    assert flaky.calls == 2
    nr = result.node_results["s1"]
    assert nr.status == "completed"
    assert nr.metadata["cost"] == pytest.approx(0.1)
    assert nr.metadata["input_tokens"] == 100
    assert nr.metadata["earlier_attempts_cost"] == pytest.approx(0.04)
    assert pipeline_usage(result)["cost"] == pytest.approx(0.1)


def test_hook_metrics_count_failed_nodes_from_their_metadata():
    from app.services.execution_hooks import execution_metrics

    ex = SimpleNamespace(
        agent_id=uuid.uuid4(),
        node_results={
            "a": {"status": "completed", "output": {"cost": 0.1, "input_tokens": 9}},
            "b": {"status": "failed", "metadata": {"cost": 0.2, "output_tokens": 3}},
        },
        tool_calls=None,
        input_tokens=None,
        output_tokens=None,
        cost=None,
        duration_ms=10,
        started_at=None,
        completed_at=None,
        confidence_score=None,
        output_message="",
    )
    m = execution_metrics(ex)
    assert m["cost"] == pytest.approx(0.3)
    assert (m["input_tokens"], m["output_tokens"]) == (9, 3)
    assert m["tool_failures"] == 1


def _pr(*nodes: NodeResult) -> PipelineResult:
    return PipelineResult(status="failed", node_results={n.node_id: n for n in nodes})


def test_pipelines_router_writes_the_usage_onto_the_row():
    from app.routers.pipelines import _apply_usage

    ex = SimpleNamespace(cost=None, input_tokens=None, output_tokens=None)
    _apply_usage(
        ex,
        _pr(
            NodeResult("a", "completed", output={"cost": 0.1, "input_tokens": 7}),
            NodeResult("b", "failed", metadata={"cost": 0.05}),
        ),
    )
    assert ex.cost == pytest.approx(0.15)
    assert ex.input_tokens == 7 and ex.output_tokens is None
