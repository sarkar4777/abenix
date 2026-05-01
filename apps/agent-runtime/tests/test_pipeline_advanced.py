"""Advanced tests for pipeline forEach, retry, and streaming callbacks."""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from engine.pipeline import (
    ForEachConfig,
    InputMapping,
    NodeCondition,
    PipelineExecutor,
    PipelineNode,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult

# ── Test helpers ──────────────────────────────────────────────────


class EchoTool(BaseTool):
    """Returns its arguments as JSON output."""

    name = "echo"
    description = "Echo arguments"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps(arguments))


class FailOnceTool(BaseTool):
    """Fails on first call, succeeds on subsequent calls."""

    name = "fail_once"
    description = "Fails first time"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self._call_count = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self._call_count += 1
        if self._call_count <= 1:
            return ToolResult(content="Intentional first failure", is_error=True)
        return ToolResult(
            content=json.dumps({"success": True, "attempt": self._call_count})
        )


class AlwaysFailTool(BaseTool):
    """Always returns an error."""

    name = "always_fail"
    description = "Always fails"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="Always fails", is_error=True)


class ListTool(BaseTool):
    """Returns a list for forEach testing."""

    name = "list_tool"
    description = "Returns a list"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        items = arguments.get("items", ["a", "b", "c"])
        return ToolResult(content=json.dumps({"items": items}))


class NestedListTool(BaseTool):
    """Returns a nested structure for forEach nested field extraction testing."""

    name = "nested_list_tool"
    description = "Returns nested data"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps({"data": {"results": [1, 2, 3]}}))


class StringItemTool(BaseTool):
    """Returns a non-list value in the items field for negative testing."""

    name = "string_item_tool"
    description = "Returns a string instead of a list"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps({"items": "not_a_list"}))


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(EchoTool())
    reg.register(FailOnceTool())
    reg.register(AlwaysFailTool())
    reg.register(ListTool())
    reg.register(NestedListTool())
    reg.register(StringItemTool())
    return reg


# ── ForEach Tests ─────────────────────────────────────────────────


class TestForEach:
    @pytest.mark.asyncio
    async def test_for_each_basic_list(self, registry: ToolRegistry) -> None:
        """forEach iterates over a list and produces a result per item."""
        nodes = [
            PipelineNode(
                id="list_node",
                tool_name="list_tool",
                arguments={"items": ["x", "y", "z"]},
            ),
            PipelineNode(
                id="echo_node",
                tool_name="echo",
                depends_on=["list_node"],
                for_each=ForEachConfig(
                    source_node="list_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        echo_output = result.node_results["echo_node"].output
        assert isinstance(echo_output, list)
        assert len(echo_output) == 3

    @pytest.mark.asyncio
    async def test_for_each_with_concurrency_limit(
        self, registry: ToolRegistry
    ) -> None:
        """forEach with max_concurrency=2 still completes all 5 items."""
        nodes = [
            PipelineNode(
                id="list_node",
                tool_name="list_tool",
                arguments={"items": [1, 2, 3, 4, 5]},
            ),
            PipelineNode(
                id="echo_node",
                tool_name="echo",
                depends_on=["list_node"],
                for_each=ForEachConfig(
                    source_node="list_node",
                    source_field="items",
                    item_variable="current_item",
                    max_concurrency=2,
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        echo_output = result.node_results["echo_node"].output
        assert isinstance(echo_output, list)
        assert len(echo_output) == 5

    @pytest.mark.asyncio
    async def test_for_each_empty_list(self, registry: ToolRegistry) -> None:
        """forEach on an empty list produces an empty output list and status completed."""
        nodes = [
            PipelineNode(
                id="list_node",
                tool_name="list_tool",
                arguments={"items": []},
            ),
            PipelineNode(
                id="echo_node",
                tool_name="echo",
                depends_on=["list_node"],
                for_each=ForEachConfig(
                    source_node="list_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        echo_output = result.node_results["echo_node"].output
        assert isinstance(echo_output, list)
        assert len(echo_output) == 0

    @pytest.mark.asyncio
    async def test_for_each_with_downstream_dependency(
        self, registry: ToolRegistry
    ) -> None:
        """A downstream node receives the array of forEach results."""
        nodes = [
            PipelineNode(
                id="list_node",
                tool_name="list_tool",
                arguments={"items": ["a", "b"]},
            ),
            PipelineNode(
                id="for_each_node",
                tool_name="echo",
                depends_on=["list_node"],
                for_each=ForEachConfig(
                    source_node="list_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
            PipelineNode(
                id="downstream",
                tool_name="echo",
                depends_on=["for_each_node"],
                input_mappings={
                    "results": InputMapping(
                        source_node="for_each_node",
                        source_field="__all__",
                    ),
                },
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        downstream_output = result.node_results["downstream"].output
        assert "results" in downstream_output
        # The downstream node should have received the list of for_each outputs
        assert isinstance(downstream_output["results"], list)
        assert len(downstream_output["results"]) == 2

    @pytest.mark.asyncio
    async def test_for_each_invalid_source(self, registry: ToolRegistry) -> None:
        """forEach referencing a non-existent source node should fail gracefully."""
        nodes = [
            PipelineNode(
                id="for_each_node",
                tool_name="echo",
                for_each=ForEachConfig(
                    source_node="nonexistent_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        # Node should fail because the source node doesn't exist in outputs
        assert result.node_results["for_each_node"].status == "failed"
        assert "not a list" in result.node_results["for_each_node"].error

    @pytest.mark.asyncio
    async def test_for_each_non_list_source(self, registry: ToolRegistry) -> None:
        """forEach on a source that returns a non-list value should fail with error."""
        nodes = [
            PipelineNode(
                id="string_node",
                tool_name="string_item_tool",
            ),
            PipelineNode(
                id="for_each_node",
                tool_name="echo",
                depends_on=["string_node"],
                for_each=ForEachConfig(
                    source_node="string_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.node_results["for_each_node"].status == "failed"
        assert "not a list" in result.node_results["for_each_node"].error

    @pytest.mark.asyncio
    async def test_for_each_with_input_mappings(self, registry: ToolRegistry) -> None:
        """forEach node that also has input_mappings from another node."""
        nodes = [
            PipelineNode(
                id="context_node",
                tool_name="echo",
                arguments={"prefix": "item"},
            ),
            PipelineNode(
                id="list_node",
                tool_name="list_tool",
                arguments={"items": ["x", "y"]},
            ),
            PipelineNode(
                id="for_each_node",
                tool_name="echo",
                depends_on=["context_node", "list_node"],
                input_mappings={
                    "prefix": InputMapping(
                        source_node="context_node",
                        source_field="prefix",
                    ),
                },
                for_each=ForEachConfig(
                    source_node="list_node",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        outputs = result.node_results["for_each_node"].output
        assert isinstance(outputs, list)
        assert len(outputs) == 2
        # Each output should have both the mapped prefix and the forEach item
        for output in outputs:
            assert "prefix" in output
            assert output["prefix"] == "item"
            assert "current_item" in output

    @pytest.mark.asyncio
    async def test_for_each_nested_field_extraction(
        self, registry: ToolRegistry
    ) -> None:
        """forEach with a nested source_field like 'data.results' extracts correctly."""
        nodes = [
            PipelineNode(
                id="nested_node",
                tool_name="nested_list_tool",
            ),
            PipelineNode(
                id="for_each_node",
                tool_name="echo",
                depends_on=["nested_node"],
                for_each=ForEachConfig(
                    source_node="nested_node",
                    source_field="data.results",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        outputs = result.node_results["for_each_node"].output
        assert isinstance(outputs, list)
        assert len(outputs) == 3
        # Verify each item was injected as current_item
        item_values = [o["current_item"] for o in outputs]
        assert sorted(item_values) == [1, 2, 3]


# ── Retry Tests ───────────────────────────────────────────────────


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(
        self, registry: ToolRegistry
    ) -> None:
        """Node with fail_once tool and max_retries=2 succeeds on attempt 2."""
        nodes = [
            PipelineNode(
                id="retry_node",
                tool_name="fail_once",
                max_retries=2,
                retry_delay_ms=10,  # small delay for fast tests
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["retry_node"].status == "completed"
        assert result.node_results["retry_node"].attempt == 2
        output = result.node_results["retry_node"].output
        assert output["success"] is True

    @pytest.mark.asyncio
    async def test_retry_exhausted_still_fails(self, registry: ToolRegistry) -> None:
        """always_fail with max_retries=3 should fail after all retries."""
        nodes = [
            PipelineNode(
                id="doomed_node",
                tool_name="always_fail",
                max_retries=3,
                retry_delay_ms=10,
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.node_results["doomed_node"].status == "failed"
        assert "doomed_node" in result.failed_nodes

    @pytest.mark.asyncio
    async def test_retry_zero_means_no_retry(self, registry: ToolRegistry) -> None:
        """always_fail with max_retries=0 should fail immediately, only 1 attempt."""
        nodes = [
            PipelineNode(
                id="no_retry_node",
                tool_name="always_fail",
                max_retries=0,
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.node_results["no_retry_node"].status == "failed"
        assert result.node_results["no_retry_node"].attempt == 1

    @pytest.mark.asyncio
    async def test_retry_delay_is_respected(self, registry: ToolRegistry) -> None:
        """Retry with delay should take at least the configured delay time."""
        # Use a fresh FailOnceTool so it starts with _call_count=0
        fresh_reg = ToolRegistry()
        fresh_reg.register(FailOnceTool())

        nodes = [
            PipelineNode(
                id="delayed_retry",
                tool_name="fail_once",
                max_retries=1,
                retry_delay_ms=200,
            ),
        ]
        start = time.monotonic()
        result = await PipelineExecutor(fresh_reg).execute(nodes)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert result.status == "completed"
        assert result.node_results["delayed_retry"].attempt == 2
        # The retry delay should have been at least 200ms
        assert elapsed_ms >= 200

    @pytest.mark.asyncio
    async def test_retry_attempt_in_result(self, registry: ToolRegistry) -> None:
        """NodeResult.attempt field is correctly set after retries."""
        # Use a fresh FailOnceTool so it starts with _call_count=0
        fresh_reg = ToolRegistry()
        fresh_reg.register(FailOnceTool())

        nodes = [
            PipelineNode(
                id="attempt_node",
                tool_name="fail_once",
                max_retries=2,
                retry_delay_ms=10,
            ),
        ]
        result = await PipelineExecutor(fresh_reg).execute(nodes)

        assert result.node_results["attempt_node"].attempt == 2

    @pytest.mark.asyncio
    async def test_retry_does_not_retry_skipped(self, registry: ToolRegistry) -> None:
        """A node skipped due to a condition should not be retried."""
        nodes = [
            PipelineNode(
                id="source",
                tool_name="echo",
                arguments={"flag": "off"},
            ),
            PipelineNode(
                id="conditional_node",
                tool_name="always_fail",
                depends_on=["source"],
                max_retries=3,
                retry_delay_ms=10,
                condition=NodeCondition(
                    source_node="source",
                    field="flag",
                    operator="eq",
                    value="on",
                ),
            ),
        ]
        result = await PipelineExecutor(registry).execute(nodes)

        assert result.node_results["conditional_node"].status == "skipped"
        assert result.node_results["conditional_node"].condition_met is False
        # Attempt should be 1 (the initial check, no retries)
        assert result.node_results["conditional_node"].attempt == 1


# ── Streaming Callback Tests ─────────────────────────────────────


class TestStreamingCallbacks:
    @pytest.mark.asyncio
    async def test_on_node_start_called(self, registry: ToolRegistry) -> None:
        """on_node_start callback is called with (node_id, tool_name) for each node."""
        start_calls: list[tuple[str, str]] = []

        def on_start(node_id: str, tool_name: str) -> None:
            start_calls.append((node_id, tool_name))

        nodes = [
            PipelineNode(id="n1", tool_name="echo", arguments={"a": 1}),
            PipelineNode(
                id="n2",
                tool_name="echo",
                arguments={"b": 2},
                depends_on=["n1"],
            ),
        ]
        executor = PipelineExecutor(registry, on_node_start=on_start)
        result = await executor.execute(nodes)

        assert result.status == "completed"
        assert len(start_calls) == 2
        node_ids_started = [c[0] for c in start_calls]
        assert "n1" in node_ids_started
        assert "n2" in node_ids_started
        # Verify tool_name is passed correctly
        for node_id, tool_name in start_calls:
            assert tool_name == "echo"

    @pytest.mark.asyncio
    async def test_on_node_complete_called(self, registry: ToolRegistry) -> None:
        """on_node_complete callback is called with (node_id, status, duration_ms, output)."""
        complete_calls: list[tuple[str, str, int, Any]] = []

        def on_complete(
            node_id: str, status: str, duration_ms: int, output: Any
        ) -> None:
            complete_calls.append((node_id, status, duration_ms, output))

        nodes = [
            PipelineNode(id="n1", tool_name="echo", arguments={"x": 42}),
        ]
        executor = PipelineExecutor(registry, on_node_complete=on_complete)
        result = await executor.execute(nodes)

        assert result.status == "completed"
        assert len(complete_calls) == 1
        node_id, status, duration_ms, output = complete_calls[0]
        assert node_id == "n1"
        assert status == "completed"
        assert isinstance(duration_ms, int)
        assert output == {"x": 42}

    @pytest.mark.asyncio
    async def test_callbacks_receive_correct_data(self, registry: ToolRegistry) -> None:
        """Verify callback arguments match actual execution results."""
        start_calls: list[tuple[str, str]] = []
        complete_calls: list[tuple[str, str, int, Any]] = []

        def on_start(node_id: str, tool_name: str) -> None:
            start_calls.append((node_id, tool_name))

        def on_complete(
            node_id: str, status: str, duration_ms: int, output: Any
        ) -> None:
            complete_calls.append((node_id, status, duration_ms, output))

        nodes = [
            PipelineNode(
                id="math_echo",
                tool_name="echo",
                arguments={"value": 100},
            ),
        ]
        executor = PipelineExecutor(
            registry,
            on_node_start=on_start,
            on_node_complete=on_complete,
        )
        result = await executor.execute(nodes)

        # Verify start callback
        assert len(start_calls) == 1
        assert start_calls[0] == ("math_echo", "echo")

        # Verify complete callback matches actual result
        assert len(complete_calls) == 1
        cb_node_id, cb_status, cb_duration, cb_output = complete_calls[0]
        actual_result = result.node_results["math_echo"]
        assert cb_node_id == actual_result.node_id
        assert cb_status == actual_result.status
        assert cb_duration == actual_result.duration_ms
        assert cb_output == actual_result.output

    @pytest.mark.asyncio
    async def test_callbacks_exception_does_not_break_pipeline(
        self, registry: ToolRegistry
    ) -> None:
        """A callback that raises an exception should not break the pipeline."""

        def bad_on_start(node_id: str, tool_name: str) -> None:
            raise RuntimeError("Callback exploded!")

        def bad_on_complete(
            node_id: str, status: str, duration_ms: int, output: Any
        ) -> None:
            raise ValueError("Callback also exploded!")

        nodes = [
            PipelineNode(id="n1", tool_name="echo", arguments={"ok": True}),
            PipelineNode(
                id="n2",
                tool_name="echo",
                arguments={"still": "running"},
                depends_on=["n1"],
            ),
        ]
        executor = PipelineExecutor(
            registry,
            on_node_start=bad_on_start,
            on_node_complete=bad_on_complete,
        )
        result = await executor.execute(nodes)

        # Pipeline should still complete despite callback exceptions
        assert result.status == "completed"
        assert "n1" in result.execution_path
        assert "n2" in result.execution_path
        assert result.node_results["n1"].output == {"ok": True}
        assert result.node_results["n2"].output == {"still": "running"}
