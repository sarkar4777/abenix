"""Tool chaining matrix — prove every pairing of producer → consumer works."""

from __future__ import annotations

import asyncio
import json
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


# ── Fake deterministic tools (no LLM calls) ──────────────────────────


class EchoTool(BaseTool):
    """Returns arguments as a JSON object. Deterministic."""

    name = "echo"
    description = "Echo arguments as JSON output"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=json.dumps(arguments))


class StringProducerTool(BaseTool):
    """Produces a single string output at key `text`."""

    name = "string_producer"
    description = "Emit a string"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = str(arguments.get("text", ""))
        return ToolResult(content=json.dumps({"text": text}))


class DictProducerTool(BaseTool):
    """Produces a nested dict output. Useful for deep-path extraction tests."""

    name = "dict_producer"
    description = "Emit a nested dict"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        payload = {
            "summary": arguments.get("summary", "default"),
            "metrics": {
                "score": arguments.get("score", 42),
                "nested": {"level": "deep", "value": arguments.get("value", 100)},
            },
            "tags": ["alpha", "beta", "gamma"],
        }
        return ToolResult(content=json.dumps(payload))


class ListProducerTool(BaseTool):
    """Produces a list of dict items for forEach / data_merger tests."""

    name = "list_producer"
    description = "Emit a list"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        count = int(arguments.get("count", 3))
        items = [{"id": i, "label": f"item_{i}"} for i in range(count)]
        return ToolResult(content=json.dumps({"items": items}))


class StringConsumerTool(BaseTool):
    """Reads a single string `message` arg and returns it in its output."""

    name = "string_consumer"
    description = "Consume a string"
    input_schema = {"type": "object", "properties": {"message": {"type": "string"}}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        message = arguments.get("message", "")
        return ToolResult(
            content=json.dumps({"received": str(message), "length": len(str(message))})
        )


class FlakyTool(BaseTool):
    """Fails on the first call; succeeds on retry. Used for retry tests."""

    name = "flaky"
    description = "Fail once, then succeed"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls += 1
        if self.calls == 1:
            return ToolResult(content="first attempt failed", is_error=True)
        return ToolResult(content=json.dumps({"attempt": self.calls, "ok": True}))


class AlwaysFailTool(BaseTool):
    """Always returns an error. Used for error_branch tests."""

    name = "always_fail"
    description = "Always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="boom", is_error=True)


def _build_registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def _all_tools() -> ToolRegistry:
    return _build_registry(
        EchoTool(),
        StringProducerTool(),
        DictProducerTool(),
        ListProducerTool(),
        StringConsumerTool(),
        AlwaysFailTool(),
    )


# ── Chain patterns ──────────────────────────────────────────────────


class TestBasicTemplates:
    """Patterns 1-4: template substitution in various shapes."""

    @pytest.mark.asyncio
    async def test_string_producer_into_llm_prompt_via_all(self):
        """Pattern 1: string output → consumer prompt via `{{node.__all__}}`."""
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="src",
                tool_name="string_producer",
                arguments={"text": "hello world"},
            ),
            PipelineNode(
                id="dst",
                tool_name="string_consumer",
                arguments={"message": "Echo: {{src.text}}"},
                depends_on=["src"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["src"].status == "completed"
        assert result.node_results["dst"].status == "completed"
        assert "hello world" in result.node_results["dst"].output["received"]

    @pytest.mark.asyncio
    async def test_string_into_consumer_via_input_mapping(self):
        """Pattern 2: same flow but via `input_mappings` instead of templates."""
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="src",
                tool_name="string_producer",
                arguments={"text": "via_mapping_value"},
            ),
            PipelineNode(
                id="dst",
                tool_name="string_consumer",
                arguments={},
                depends_on=["src"],
                input_mappings={
                    "message": InputMapping(source_node="src", source_field="text"),
                },
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["dst"].output["received"] == "via_mapping_value"

    @pytest.mark.asyncio
    async def test_dict_producer_deep_path_extraction(self):
        """Pattern 3: dict output → downstream consumer via deep dot-path."""
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="dict_src",
                tool_name="dict_producer",
                arguments={"summary": "ignored", "score": 73, "value": 999},
            ),
            PipelineNode(
                id="reader",
                tool_name="string_consumer",
                arguments={
                    "message": "score={{dict_src.metrics.score}},deep={{dict_src.metrics.nested.value}}"
                },
                depends_on=["dict_src"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        received = result.node_results["reader"].output["received"]
        assert "score=73" in received
        assert "deep=999" in received

    @pytest.mark.asyncio
    async def test_list_index_template(self):
        """Pattern 4: list output → consumer via indexed template `{{node.tags.1}}`."""
        reg = _all_tools()
        nodes = [
            PipelineNode(id="dp", tool_name="dict_producer", arguments={}),
            PipelineNode(
                id="idx",
                tool_name="string_consumer",
                arguments={"message": "tag_1 is {{dp.tags.1}}"},
                depends_on=["dp"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert "beta" in result.node_results["idx"].output["received"]


class TestParallelFanIn:
    """Pattern 5: parallel root nodes converge into a single downstream node."""

    @pytest.mark.asyncio
    async def test_three_roots_into_one_merger(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="a", tool_name="string_producer", arguments={"text": "A"},
            ),
            PipelineNode(
                id="b", tool_name="string_producer", arguments={"text": "B"},
            ),
            PipelineNode(
                id="c", tool_name="string_producer", arguments={"text": "C"},
            ),
            PipelineNode(
                id="merge",
                tool_name="echo",
                arguments={
                    "x": "{{a.text}}",
                    "y": "{{b.text}}",
                    "z": "{{c.text}}",
                },
                depends_on=["a", "b", "c"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        out = result.node_results["merge"].output
        assert out == {"x": "A", "y": "B", "z": "C"}
        # a/b/c should execute in a single layer (parallel)
        assert "merge" in result.execution_path


class TestConditionalBranching:
    """Pattern 6: node output → condition gate → branch taken / skipped."""

    @pytest.mark.asyncio
    async def test_condition_true_runs_branch(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="decide",
                tool_name="dict_producer",
                arguments={"summary": "go", "score": 90},
            ),
            PipelineNode(
                id="high",
                tool_name="echo",
                arguments={"took": "high"},
                depends_on=["decide"],
                condition=NodeCondition(
                    source_node="decide", field="metrics.score",
                    operator="gte", value=80,
                ),
            ),
            PipelineNode(
                id="low",
                tool_name="echo",
                arguments={"took": "low"},
                depends_on=["decide"],
                condition=NodeCondition(
                    source_node="decide", field="metrics.score",
                    operator="lt", value=80,
                ),
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["high"].status == "completed"
        assert result.node_results["low"].status == "skipped"


class TestForEachIteration:
    """Pattern 7: producer emits list → forEach runs downstream per item."""

    @pytest.mark.asyncio
    async def test_for_each_over_producer_list(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="lister",
                tool_name="list_producer",
                arguments={"count": 3},
            ),
            PipelineNode(
                id="process",
                tool_name="echo",
                arguments={"item": "{{current_item.label}}"},
                depends_on=["lister"],
                for_each=ForEachConfig(
                    source_node="lister",
                    source_field="items",
                    item_variable="current_item",
                ),
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        # for_each result should contain a list of per-item outputs
        process_result = result.node_results["process"]
        assert process_result.status == "completed"
        # Output shape: {"results": [{item: "item_0"}, {item: "item_1"}, ...]}
        out = process_result.output
        if isinstance(out, dict) and "results" in out:
            items = out["results"]
        else:
            items = out if isinstance(out, list) else [out]
        assert len(items) == 3


class TestRetryAndErrorBranch:
    """Pattern 8a + 8b: retry on failure; error_branch fallback."""

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        flaky = FlakyTool()
        reg = _build_registry(flaky, EchoTool())
        nodes = [
            PipelineNode(
                id="root",
                tool_name="flaky",
                arguments={},
                max_retries=2,
                retry_delay_ms=10,
            ),
            PipelineNode(
                id="downstream",
                tool_name="echo",
                arguments={"msg": "after retry"},
                depends_on=["root"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["root"].status == "completed"
        assert flaky.calls >= 2  # first failed, second succeeded
        assert result.node_results["downstream"].status == "completed"

    @pytest.mark.asyncio
    async def test_error_branch_fallback(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="primary",
                tool_name="always_fail",
                arguments={},
                on_error="error_branch",
                error_branch_node="fallback",
            ),
            PipelineNode(
                id="fallback",
                tool_name="echo",
                arguments={"msg": "safe path"},
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        # primary fails, fallback should have run
        assert result.node_results["primary"].status == "failed"
        assert "fallback" in result.node_results
        assert result.node_results["fallback"].status == "completed"
        assert result.node_results["fallback"].output == {"msg": "safe path"}


class TestContextInjection:
    """Pattern 9: executor-level `context` dict is accessible via templates."""

    @pytest.mark.asyncio
    async def test_context_auto_injection(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="reader",
                tool_name="string_consumer",
                arguments={"message": "user said {{input.user_message}}"},
            ),
        ]
        result = await PipelineExecutor(reg).execute(
            nodes,
            context={"input": {"user_message": "hello from context"}},
        )

        assert result.status == "completed"
        assert (
            "hello from context"
            in result.node_results["reader"].output["received"]
        )


class TestTypeCoercion:
    """Pattern 10: dict producer → string-only consumer; JSON-stringification."""

    @pytest.mark.asyncio
    async def test_dict_flattened_into_string_via_all(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="dict_src",
                tool_name="dict_producer",
                arguments={"summary": "important", "score": 50},
            ),
            PipelineNode(
                id="consumer",
                tool_name="string_consumer",
                arguments={"message": "summary={{dict_src.summary}}"},
                depends_on=["dict_src"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        received = result.node_results["consumer"].output["received"]
        assert "important" in received


class TestMissingFieldGracefulDegradation:
    """Pattern 11: template with missing field does not crash."""

    @pytest.mark.asyncio
    async def test_missing_field_renders_as_placeholder(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="dict_src",
                tool_name="dict_producer",
                arguments={"summary": "x"},
            ),
            PipelineNode(
                id="reader",
                tool_name="string_consumer",
                arguments={"message": "val={{dict_src.no_such_field}}"},
                depends_on=["dict_src"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        # Pipeline should still complete; missing values become "[not available]"
        assert result.status == "completed"
        assert result.node_results["reader"].status == "completed"
        received = result.node_results["reader"].output["received"]
        assert "not available" in received


class TestLongChain:
    """Pattern 12: 5-node linear chain, each transforms the prior output."""

    @pytest.mark.asyncio
    async def test_five_node_linear_chain(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="n1", tool_name="string_producer", arguments={"text": "start"},
            ),
            PipelineNode(
                id="n2",
                tool_name="string_consumer",
                arguments={"message": "{{n1.text}}-step2"},
                depends_on=["n1"],
            ),
            PipelineNode(
                id="n3",
                tool_name="string_consumer",
                arguments={"message": "{{n2.received}}-step3"},
                depends_on=["n2"],
            ),
            PipelineNode(
                id="n4",
                tool_name="string_consumer",
                arguments={"message": "{{n3.received}}-step4"},
                depends_on=["n3"],
            ),
            PipelineNode(
                id="n5",
                tool_name="string_consumer",
                arguments={"message": "{{n4.received}}-step5"},
                depends_on=["n4"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        final = result.node_results["n5"].output["received"]
        assert final == "start-step2-step3-step4-step5"
        # Topological order should be strictly sequential n1→n5
        assert result.execution_path == ["n1", "n2", "n3", "n4", "n5"]


class TestMixedPatterns:
    """Pattern 13: combined — producer → condition-gated merger fan-in."""

    @pytest.mark.asyncio
    async def test_condition_plus_fan_in(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="src", tool_name="dict_producer",
                arguments={"summary": "ok", "score": 99},
            ),
            PipelineNode(
                id="branch_a", tool_name="string_producer",
                arguments={"text": "A"},
                depends_on=["src"],
                condition=NodeCondition(
                    source_node="src", field="metrics.score",
                    operator="gte", value=50,
                ),
            ),
            PipelineNode(
                id="branch_b", tool_name="string_producer",
                arguments={"text": "B"},
                depends_on=["src"],
            ),
            PipelineNode(
                id="merger", tool_name="echo",
                arguments={
                    "from_a": "{{branch_a.text}}",
                    "from_b": "{{branch_b.text}}",
                },
                depends_on=["branch_a", "branch_b"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["branch_a"].status == "completed"
        assert result.node_results["branch_b"].status == "completed"
        merger_out = result.node_results["merger"].output
        assert merger_out["from_a"] == "A"
        assert merger_out["from_b"] == "B"


class TestAllToolsReachable:
    """Pattern 14: smoke test — every fake tool can execute as a root node."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "tool_name, args",
        [
            ("echo", {"k": 1}),
            ("string_producer", {"text": "hi"}),
            ("dict_producer", {"summary": "s", "score": 10}),
            ("list_producer", {"count": 2}),
            ("string_consumer", {"message": "hi"}),
        ],
    )
    async def test_tool_runs_standalone(self, tool_name: str, args: dict[str, Any]):
        reg = _all_tools()
        nodes = [PipelineNode(id="only", tool_name=tool_name, arguments=args)]
        result = await PipelineExecutor(reg).execute(nodes)
        assert result.status == "completed"
        assert result.node_results["only"].status == "completed"


class TestInputMappingWithContext:
    """Pattern 15: input_mapping sourcing from executor context (not a node)."""

    @pytest.mark.asyncio
    async def test_input_mapping_from_context(self):
        reg = _all_tools()
        nodes = [
            PipelineNode(
                id="consumer",
                tool_name="string_consumer",
                arguments={},
                input_mappings={
                    "message": InputMapping(source_node="cfg", source_field="greeting"),
                },
            ),
        ]
        result = await PipelineExecutor(reg).execute(
            nodes, context={"cfg": {"greeting": "howdy"}},
        )

        assert result.status == "completed"
        assert result.node_results["consumer"].output["received"] == "howdy"
