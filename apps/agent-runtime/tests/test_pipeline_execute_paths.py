from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from engine.pipeline import (
    PipelineExecutor,
    PipelineNode,
    build_run_context,
    pipeline_timed_out,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class Broken(BaseTool):
    name = "broken"
    description = "always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="HTTP request failed: boom", is_error=True)


class Echo(BaseTool):
    name = "echo"
    description = "echo"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps({"args": arguments}))


class Slow(BaseTool):
    name = "slow"
    description = "sleeps"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(1.2)
        return ToolResult(content="done")


def _reg() -> ToolRegistry:
    reg = ToolRegistry()
    for t in (Broken(), Echo(), Slow()):
        reg.register(t)
    return reg


async def test_continue_runs_dependents_with_the_error():
    result = await PipelineExecutor(_reg()).execute(
        [
            PipelineNode(id="boom", tool_name="broken", on_error="continue"),
            PipelineNode(
                id="after",
                tool_name="echo",
                depends_on=["boom"],
                arguments={"upstream": "{{boom.error}}"},
            ),
            PipelineNode(id="last", tool_name="echo", depends_on=["after"]),
        ]
    )
    assert result.node_results["after"].status == "completed"
    assert result.node_results["last"].status == "completed"
    assert "boom" in result.node_results["after"].output["args"]["upstream"]
    assert result.skipped_nodes == []


async def test_stop_still_skips_dependents():
    result = await PipelineExecutor(_reg()).execute(
        [
            PipelineNode(id="boom", tool_name="broken"),
            PipelineNode(id="after", tool_name="echo", depends_on=["boom"]),
        ]
    )
    assert result.node_results["after"].status == "skipped"
    assert result.status == "failed"


@pytest.mark.parametrize(
    "ctx",
    [
        build_run_context("hello", "e1", defaults={"region": "eu"}),
        build_run_context("hello", "e1", context={"region": "eu"}),
        # older callers put the message under "input" as plain text
        {"input": "hello", "region": "eu"},
    ],
)
async def test_input_fields_resolve_on_every_path(ctx):
    result = await PipelineExecutor(_reg()).execute(
        [
            PipelineNode(
                id="a",
                tool_name="echo",
                arguments={"r": "{{input.region}}", "m": "{{input.message}}"},
            )
        ],
        ctx,
    )
    args = result.node_results["a"].output["args"]
    assert args == {"r": "eu", "m": "hello"}


def test_run_context_carries_execution_id_and_caller_wins():
    ctx = build_run_context(
        "hi", "exec-1", defaults={"tier": "gold"}, context={"tier": "silver"}
    )
    assert ctx["__execution_id"] == "exec-1"
    assert ctx["tier"] == "silver"
    assert ctx["user_message"] == "hi"
    assert "input" not in ctx


async def test_timeout_between_layers_reads_plainly():
    result = await PipelineExecutor(_reg(), timeout_seconds=1).execute(
        [
            PipelineNode(id="s", tool_name="slow"),
            PipelineNode(id="t", tool_name="echo", depends_on=["s"]),
        ]
    )
    assert result.failure_code == "RUNTIME_TIMEOUT"
    assert "ran out of time" in result.node_errors["t"]


def test_timed_out_result_marks_unfinished_steps():
    r = pipeline_timed_out(30, {"a": "completed", "b": "running", "c": "pending"})
    assert r.status == "failed"
    assert r.failed_nodes == ["b", "c"]
    assert "30s" in r.node_errors["pipeline"]
    assert r.failure_code == "RUNTIME_TIMEOUT"


def test_pipeline_cost_splits_by_step_model():
    from engine.pipeline import NodeResult, PipelineResult, pipeline_provider_costs

    r = PipelineResult(
        status="completed",
        node_results={
            "a": NodeResult(
                "a", "completed", metadata={"cost": 0.3, "model": "claude-sonnet-4-5"}
            ),
            "b": NodeResult(
                "b", "completed", metadata={"cost": 0.1, "model": "gpt-4o-mini"}
            ),
            "c": NodeResult("c", "completed", metadata={"cost": 0.0}),
        },
    )
    assert pipeline_provider_costs(r) == {"anthropic": 0.3, "openai": 0.1}
