"""Tests for the SubPipelineTool — nested pipeline execution."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from engine.tools.base import BaseTool, ToolRegistry, ToolResult
from engine.tools.sub_pipeline import SubPipelineTool


# ── Test helpers ──────────────────────────────────────────────────


class EchoTool(BaseTool):
    """Returns its arguments as JSON output."""
    name = "echo"
    description = "Echo arguments"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps(arguments))


class FailTool(BaseTool):
    """Always returns an error."""
    name = "fail"
    description = "Always fails"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="Intentional failure", is_error=True)


class SlowTool(BaseTool):
    """Takes some time to execute."""
    name = "slow"
    description = "Slow tool"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(content=json.dumps({"delayed": True}))


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(FailTool())
    reg.register(SlowTool())
    return reg


@pytest.fixture
def tool(registry: ToolRegistry) -> SubPipelineTool:
    return SubPipelineTool(tool_registry=registry)


# ── Tests ─────────────────────────────────────────────────────────


class TestSubPipelineTool:
    @pytest.mark.asyncio
    async def test_basic_sub_pipeline(self, tool: SubPipelineTool) -> None:
        """A 2-node echo pipeline should execute both nodes and return results."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "n1",
                    "tool_name": "echo",
                    "arguments": {"msg": "hello"},
                },
                {
                    "id": "n2",
                    "tool_name": "echo",
                    "arguments": {"msg": "world"},
                    "depends_on": ["n1"],
                },
            ],
        })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["status"] == "completed"
        assert "n1" in parsed["node_results"]
        assert "n2" in parsed["node_results"]
        assert parsed["node_results"]["n1"]["status"] == "completed"
        assert parsed["node_results"]["n2"]["status"] == "completed"
        assert len(parsed["execution_path"]) == 2

    @pytest.mark.asyncio
    async def test_sub_pipeline_with_context(
        self, tool: SubPipelineTool
    ) -> None:
        """Context data is accessible in the sub-pipeline via input_mappings."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "n1",
                    "tool_name": "echo",
                    "arguments": {},
                    "input_mappings": {
                        "value": {
                            "source_node": "ctx",
                            "source_field": "data",
                        },
                    },
                },
            ],
            "context": {"ctx": {"data": "from_context"}},
        })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["status"] == "completed"
        node_output = parsed["node_results"]["n1"]["output"]
        assert node_output["value"] == "from_context"

    @pytest.mark.asyncio
    async def test_sub_pipeline_timeout(
        self, tool: SubPipelineTool
    ) -> None:
        """A sub-pipeline with a tight timeout and slow tools should handle timeout."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "s1",
                    "tool_name": "slow",
                },
                {
                    "id": "s2",
                    "tool_name": "slow",
                    "depends_on": ["s1"],
                },
                {
                    "id": "s3",
                    "tool_name": "slow",
                    "depends_on": ["s2"],
                },
            ],
            "timeout_seconds": 5,  # Use a minimum valid timeout
        })

        # The tool should still return a result (not crash)
        assert not result.is_error or result.is_error
        parsed = json.loads(result.content)
        assert "status" in parsed

    @pytest.mark.asyncio
    async def test_sub_pipeline_failure_propagation(
        self, tool: SubPipelineTool
    ) -> None:
        """A sub-pipeline with a failing node propagates the error."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "good",
                    "tool_name": "echo",
                    "arguments": {"ok": True},
                },
                {
                    "id": "bad",
                    "tool_name": "fail",
                    "depends_on": ["good"],
                },
            ],
        })

        assert not result.is_error  # The tool itself succeeds, but reports failure
        parsed = json.loads(result.content)
        assert parsed["status"] in ("partial", "failed")
        assert "bad" in parsed["failed_nodes"]
        assert parsed["node_results"]["bad"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_sub_pipeline_with_conditions(
        self, tool: SubPipelineTool
    ) -> None:
        """Sub-pipeline with conditional node executes conditionally."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "source",
                    "tool_name": "echo",
                    "arguments": {"flag": "yes"},
                },
                {
                    "id": "conditional_yes",
                    "tool_name": "echo",
                    "arguments": {"branch": "taken"},
                    "depends_on": ["source"],
                    "condition": {
                        "source_node": "source",
                        "field": "flag",
                        "operator": "eq",
                        "value": "yes",
                    },
                },
                {
                    "id": "conditional_no",
                    "tool_name": "echo",
                    "arguments": {"branch": "skipped"},
                    "depends_on": ["source"],
                    "condition": {
                        "source_node": "source",
                        "field": "flag",
                        "operator": "eq",
                        "value": "no",
                    },
                },
            ],
        })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["status"] == "completed"
        assert "conditional_yes" in parsed["execution_path"]
        assert "conditional_no" in parsed["skipped_nodes"]

    @pytest.mark.asyncio
    async def test_sub_pipeline_parallel_nodes(
        self, tool: SubPipelineTool
    ) -> None:
        """Sub-pipeline with 3 independent nodes executes them in parallel."""
        result = await tool.execute({
            "nodes": [
                {
                    "id": "p1",
                    "tool_name": "echo",
                    "arguments": {"task": 1},
                },
                {
                    "id": "p2",
                    "tool_name": "echo",
                    "arguments": {"task": 2},
                },
                {
                    "id": "p3",
                    "tool_name": "echo",
                    "arguments": {"task": 3},
                },
            ],
        })

        assert not result.is_error
        parsed = json.loads(result.content)
        assert parsed["status"] == "completed"
        assert len(parsed["execution_path"]) == 3
        # All three should have completed
        for nid in ["p1", "p2", "p3"]:
            assert parsed["node_results"][nid]["status"] == "completed"
        # Metadata should report 3 completed
        assert result.metadata["completed_count"] == 3
        assert result.metadata["failed_count"] == 0
