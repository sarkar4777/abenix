"""Comprehensive tests for the DAG-based pipeline executor."""

from __future__ import annotations

import asyncio
import json
import pytest

from engine.pipeline import (
    InputMapping,
    NodeCondition,
    PipelineExecutor,
    PipelineNode,
    PipelineResult,
    _extract_field,
    _topological_sort,
    parse_pipeline_nodes,
    serialize_pipeline_result,
)
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


# ── Test helpers ──────────────────────────────────────────────────

class EchoTool(BaseTool):
    """Returns its arguments as JSON output."""
    name = "echo"
    description = "Echo arguments"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(content=json.dumps(arguments))


class FailTool(BaseTool):
    """Always returns an error."""
    name = "fail"
    description = "Always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        return ToolResult(content="Intentional failure", is_error=True)


class SlowTool(BaseTool):
    """Takes some time to execute."""
    name = "slow"
    description = "Slow tool"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        await asyncio.sleep(0.1)
        return ToolResult(content=json.dumps({"delayed": True}))


class MathTool(BaseTool):
    """Performs simple arithmetic from arguments."""
    name = "math_op"
    description = "Math operations"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        op = arguments.get("operation", "add")
        a = float(arguments.get("a", 0))
        b = float(arguments.get("b", 0))
        if op == "add":
            result = a + b
        elif op == "multiply":
            result = a * b
        elif op == "subtract":
            result = a - b
        else:
            result = a + b
        return ToolResult(
            content=json.dumps({"result": result, "operation": op}),
        )


class ConditionalOutputTool(BaseTool):
    """Returns different output based on a 'mode' argument."""
    name = "conditional_output"
    description = "Returns output based on mode"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict) -> ToolResult:
        mode = arguments.get("mode", "default")
        value = arguments.get("value", 0)
        if mode == "high":
            output = {"outlook": "bullish", "score": 85, "action": "buy"}
        elif mode == "low":
            output = {"outlook": "bearish", "score": 25, "action": "sell"}
        else:
            output = {"outlook": "neutral", "score": 50, "action": "hold"}
        output["input_value"] = value
        return ToolResult(content=json.dumps(output))


def _build_registry(*tools: BaseTool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ── Unit tests for helpers ────────────────────────────────────────

class TestExtractField:
    def test_simple_key(self):
        assert _extract_field({"a": 1, "b": 2}, "a") == 1

    def test_nested_key(self):
        assert _extract_field({"a": {"b": {"c": 42}}}, "a.b.c") == 42

    def test_all(self):
        data = {"x": 1}
        assert _extract_field(data, "__all__") == data

    def test_missing_key(self):
        assert _extract_field({"a": 1}, "z") is None

    def test_json_string(self):
        data = json.dumps({"key": "val"})
        assert _extract_field(data, "key") == "val"

    def test_list_index(self):
        data = {"items": [10, 20, 30]}
        assert _extract_field(data, "items.1") == 20

    def test_plain_string(self):
        assert _extract_field("hello", "") == "hello"


class TestTopologicalSort:
    def test_linear_chain(self):
        nodes = [
            PipelineNode(id="a", tool_name="t"),
            PipelineNode(id="b", tool_name="t", depends_on=["a"]),
            PipelineNode(id="c", tool_name="t", depends_on=["b"]),
        ]
        layers = _topological_sort(nodes)
        assert layers == [["a"], ["b"], ["c"]]

    def test_parallel_independent(self):
        nodes = [
            PipelineNode(id="a", tool_name="t"),
            PipelineNode(id="b", tool_name="t"),
            PipelineNode(id="c", tool_name="t"),
        ]
        layers = _topological_sort(nodes)
        assert len(layers) == 1
        assert sorted(layers[0]) == ["a", "b", "c"]

    def test_diamond(self):
        nodes = [
            PipelineNode(id="a", tool_name="t"),
            PipelineNode(id="b", tool_name="t", depends_on=["a"]),
            PipelineNode(id="c", tool_name="t", depends_on=["a"]),
            PipelineNode(id="d", tool_name="t", depends_on=["b", "c"]),
        ]
        layers = _topological_sort(nodes)
        assert layers[0] == ["a"]
        assert sorted(layers[1]) == ["b", "c"]
        assert layers[2] == ["d"]

    def test_cycle_detection(self):
        nodes = [
            PipelineNode(id="a", tool_name="t", depends_on=["c"]),
            PipelineNode(id="b", tool_name="t", depends_on=["a"]),
            PipelineNode(id="c", tool_name="t", depends_on=["b"]),
        ]
        with pytest.raises(ValueError, match="Cycle detected"):
            _topological_sort(nodes)


class TestNodeCondition:
    def test_eq_true(self):
        cond = NodeCondition(source_node="n1", field="outlook", operator="eq", value="bullish")
        assert cond.evaluate({"n1": {"outlook": "bullish"}}) is True

    def test_eq_false(self):
        cond = NodeCondition(source_node="n1", field="outlook", operator="eq", value="bullish")
        assert cond.evaluate({"n1": {"outlook": "bearish"}}) is False

    def test_neq(self):
        cond = NodeCondition(source_node="n1", field="score", operator="neq", value=0)
        assert cond.evaluate({"n1": {"score": 50}}) is True

    def test_gt(self):
        cond = NodeCondition(source_node="n1", field="score", operator="gt", value=50)
        assert cond.evaluate({"n1": {"score": 75}}) is True
        assert cond.evaluate({"n1": {"score": 25}}) is False

    def test_lt(self):
        cond = NodeCondition(source_node="n1", field="price", operator="lt", value=100)
        assert cond.evaluate({"n1": {"price": 42.5}}) is True

    def test_contains(self):
        cond = NodeCondition(source_node="n1", field="text", operator="contains", value="error")
        assert cond.evaluate({"n1": {"text": "no error found"}}) is True
        assert cond.evaluate({"n1": {"text": "all good"}}) is False

    def test_missing_source(self):
        cond = NodeCondition(source_node="missing", field="x", operator="eq", value=1)
        assert cond.evaluate({"other": {"x": 1}}) is False

    def test_nested_field(self):
        cond = NodeCondition(source_node="n1", field="data.metrics.score", operator="gte", value=80)
        assert cond.evaluate({"n1": {"data": {"metrics": {"score": 90}}}}) is True


# ── Pipeline executor integration tests ───────────────────────────

class TestPipelineExecutorBasic:
    @pytest.mark.asyncio
    async def test_single_node(self):
        reg = _build_registry(EchoTool())
        executor = PipelineExecutor(reg)
        nodes = [PipelineNode(id="n1", tool_name="echo", arguments={"msg": "hello"})]
        result = await executor.execute(nodes)

        assert result.status == "completed"
        assert len(result.execution_path) == 1
        assert result.node_results["n1"].status == "completed"
        assert result.node_results["n1"].output == {"msg": "hello"}

    @pytest.mark.asyncio
    async def test_linear_chain(self):
        reg = _build_registry(EchoTool(), MathTool())
        nodes = [
            PipelineNode(id="n1", tool_name="echo", arguments={"value": 10}),
            PipelineNode(
                id="n2", tool_name="math_op",
                arguments={"operation": "add", "b": 5},
                depends_on=["n1"],
                input_mappings={"a": InputMapping(source_node="n1", source_field="value")},
            ),
        ]
        executor = PipelineExecutor(reg)
        result = await executor.execute(nodes)

        assert result.status == "completed"
        assert result.execution_path == ["n1", "n2"]
        assert result.node_results["n2"].output["result"] == 15.0

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        reg = _build_registry(SlowTool())
        nodes = [
            PipelineNode(id="a", tool_name="slow"),
            PipelineNode(id="b", tool_name="slow"),
            PipelineNode(id="c", tool_name="slow"),
        ]
        executor = PipelineExecutor(reg)
        result = await executor.execute(nodes)

        assert result.status == "completed"
        assert len(result.execution_path) == 3
        # Parallel execution: total should be ~100ms, not ~300ms
        assert result.total_duration_ms < 250

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        reg = _build_registry(EchoTool())
        nodes = [PipelineNode(id="n1", tool_name="nonexistent")]
        result = await executor.execute(nodes) if (executor := PipelineExecutor(reg)) else None
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.node_results["n1"].status == "failed"
        assert "Unknown tool" in result.node_results["n1"].error

    @pytest.mark.asyncio
    async def test_failed_tool(self):
        reg = _build_registry(FailTool())
        nodes = [PipelineNode(id="n1", tool_name="fail")]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.node_results["n1"].status == "failed"
        assert result.failed_nodes == ["n1"]

    @pytest.mark.asyncio
    async def test_context_injection(self):
        reg = _build_registry(MathTool())
        nodes = [
            PipelineNode(
                id="n1", tool_name="math_op",
                arguments={"operation": "multiply", "b": 3},
                input_mappings={"a": InputMapping(source_node="ctx", source_field="base_value")},
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes, context={"ctx": {"base_value": 7}})

        assert result.status == "completed"
        assert result.node_results["n1"].output["result"] == 21.0


class TestPipelineConditionalBranching:
    @pytest.mark.asyncio
    async def test_condition_branches_bullish(self):
        """Test if/then/else branching: bullish path taken."""
        reg = _build_registry(ConditionalOutputTool(), MathTool())
        nodes = [
            PipelineNode(
                id="evaluate", tool_name="conditional_output",
                arguments={"mode": "high", "value": 100},
            ),
            PipelineNode(
                id="bullish_path", tool_name="math_op",
                arguments={"operation": "multiply", "a": 100, "b": 1.5},
                depends_on=["evaluate"],
                condition=NodeCondition(
                    source_node="evaluate", field="outlook",
                    operator="eq", value="bullish",
                ),
            ),
            PipelineNode(
                id="bearish_path", tool_name="math_op",
                arguments={"operation": "multiply", "a": 100, "b": 0.5},
                depends_on=["evaluate"],
                condition=NodeCondition(
                    source_node="evaluate", field="outlook",
                    operator="eq", value="bearish",
                ),
            ),
            PipelineNode(
                id="final", tool_name="echo",
                depends_on=["bullish_path", "bearish_path"],
                arguments={"summary": "done"},
            ),
        ]
        reg.register(EchoTool())
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert "bullish_path" in result.execution_path
        assert "bearish_path" in result.skipped_nodes
        assert result.node_results["bullish_path"].condition_met is True
        assert result.node_results["bearish_path"].condition_met is False
        assert result.node_results["bullish_path"].output["result"] == 150.0

    @pytest.mark.asyncio
    async def test_condition_branches_bearish(self):
        """Test if/then/else branching: bearish path taken."""
        reg = _build_registry(ConditionalOutputTool(), MathTool(), EchoTool())
        nodes = [
            PipelineNode(
                id="evaluate", tool_name="conditional_output",
                arguments={"mode": "low", "value": 100},
            ),
            PipelineNode(
                id="bullish_path", tool_name="math_op",
                arguments={"operation": "multiply", "a": 100, "b": 1.5},
                depends_on=["evaluate"],
                condition=NodeCondition(
                    source_node="evaluate", field="outlook",
                    operator="eq", value="bullish",
                ),
            ),
            PipelineNode(
                id="bearish_path", tool_name="math_op",
                arguments={"operation": "multiply", "a": 100, "b": 0.5},
                depends_on=["evaluate"],
                condition=NodeCondition(
                    source_node="evaluate", field="outlook",
                    operator="eq", value="bearish",
                ),
            ),
            PipelineNode(
                id="final", tool_name="echo",
                depends_on=["bullish_path", "bearish_path"],
                arguments={"summary": "done"},
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert "bearish_path" in result.execution_path
        assert "bullish_path" in result.skipped_nodes
        assert result.node_results["bearish_path"].output["result"] == 50.0

    @pytest.mark.asyncio
    async def test_numeric_condition_gt(self):
        reg = _build_registry(EchoTool(), MathTool())
        nodes = [
            PipelineNode(
                id="source", tool_name="echo",
                arguments={"score": 85},
            ),
            PipelineNode(
                id="high_branch", tool_name="echo",
                arguments={"action": "execute_high"},
                depends_on=["source"],
                condition=NodeCondition(
                    source_node="source", field="score",
                    operator="gt", value=70,
                ),
            ),
            PipelineNode(
                id="low_branch", tool_name="echo",
                arguments={"action": "execute_low"},
                depends_on=["source"],
                condition=NodeCondition(
                    source_node="source", field="score",
                    operator="lte", value=70,
                ),
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert "high_branch" in result.execution_path
        assert "low_branch" in result.skipped_nodes

    @pytest.mark.asyncio
    async def test_multi_level_branching(self):
        """Three levels: evaluate → branch → sub-branch."""
        reg = _build_registry(ConditionalOutputTool(), EchoTool())
        nodes = [
            PipelineNode(
                id="eval1", tool_name="conditional_output",
                arguments={"mode": "high"},
            ),
            PipelineNode(
                id="branch_a", tool_name="echo",
                arguments={"level": "a"},
                depends_on=["eval1"],
                condition=NodeCondition(source_node="eval1", field="outlook", operator="eq", value="bullish"),
            ),
            PipelineNode(
                id="sub_branch_a1", tool_name="echo",
                arguments={"level": "a1"},
                depends_on=["branch_a"],
                condition=NodeCondition(source_node="eval1", field="score", operator="gt", value=80),
            ),
            PipelineNode(
                id="sub_branch_a2", tool_name="echo",
                arguments={"level": "a2"},
                depends_on=["branch_a"],
                condition=NodeCondition(source_node="eval1", field="score", operator="lte", value=80),
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert "branch_a" in result.execution_path
        assert "sub_branch_a1" in result.execution_path
        assert "sub_branch_a2" in result.skipped_nodes


class TestPipelineDataFlow:
    @pytest.mark.asyncio
    async def test_chained_math(self):
        """n1: 10+5=15, n2: 15*3=45, n3: 45-10=35."""
        reg = _build_registry(MathTool())
        nodes = [
            PipelineNode(
                id="n1", tool_name="math_op",
                arguments={"operation": "add", "a": 10, "b": 5},
            ),
            PipelineNode(
                id="n2", tool_name="math_op",
                arguments={"operation": "multiply", "b": 3},
                depends_on=["n1"],
                input_mappings={"a": InputMapping(source_node="n1", source_field="result")},
            ),
            PipelineNode(
                id="n3", tool_name="math_op",
                arguments={"operation": "subtract", "b": 10},
                depends_on=["n2"],
                input_mappings={"a": InputMapping(source_node="n2", source_field="result")},
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        assert result.node_results["n1"].output["result"] == 15.0
        assert result.node_results["n2"].output["result"] == 45.0
        assert result.node_results["n3"].output["result"] == 35.0

    @pytest.mark.asyncio
    async def test_multiple_inputs_from_different_nodes(self):
        """Final node gets inputs from two parallel branches."""
        reg = _build_registry(EchoTool(), MathTool())
        nodes = [
            PipelineNode(id="left", tool_name="echo", arguments={"value": 10}),
            PipelineNode(id="right", tool_name="echo", arguments={"value": 20}),
            PipelineNode(
                id="combine", tool_name="math_op",
                arguments={"operation": "add"},
                depends_on=["left", "right"],
                input_mappings={
                    "a": InputMapping(source_node="left", source_field="value"),
                    "b": InputMapping(source_node="right", source_field="value"),
                },
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.node_results["combine"].output["result"] == 30.0

    @pytest.mark.asyncio
    async def test_all_output_mapping(self):
        """Map entire output of one node as input to another."""
        reg = _build_registry(EchoTool())
        nodes = [
            PipelineNode(id="n1", tool_name="echo", arguments={"x": 1, "y": 2}),
            PipelineNode(
                id="n2", tool_name="echo",
                depends_on=["n1"],
                input_mappings={"data": InputMapping(source_node="n1", source_field="__all__")},
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.node_results["n2"].output["data"]["x"] == 1
        assert result.node_results["n2"].output["data"]["y"] == 2


class TestPipelineErrorHandling:
    @pytest.mark.asyncio
    async def test_failed_dependency_skips_downstream(self):
        reg = _build_registry(FailTool(), EchoTool())
        nodes = [
            PipelineNode(id="n1", tool_name="fail"),
            PipelineNode(id="n2", tool_name="echo", depends_on=["n1"]),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.node_results["n1"].status == "failed"
        assert result.node_results["n2"].status == "skipped"
        assert "Dependency" in result.node_results["n2"].error

    @pytest.mark.asyncio
    async def test_timeout(self):
        reg = _build_registry(SlowTool())
        nodes = [
            PipelineNode(id="n1", tool_name="slow"),
            PipelineNode(id="n2", tool_name="slow", depends_on=["n1"]),
        ]
        # Timeout of 0.05s < 0.1s per SlowTool
        executor = PipelineExecutor(reg, timeout_seconds=0.05)
        result = await executor.execute(nodes)

        # At least the second node should fail due to timeout
        has_timeout = any(
            nr.error and "timeout" in nr.error.lower()
            for nr in result.node_results.values()
            if nr.error
        )
        # The pipeline should not complete successfully
        assert result.status in ("failed", "partial")

    @pytest.mark.asyncio
    async def test_cycle_detection(self):
        reg = _build_registry(EchoTool())
        nodes = [
            PipelineNode(id="a", tool_name="echo", depends_on=["b"]),
            PipelineNode(id="b", tool_name="echo", depends_on=["a"]),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "failed"
        assert "Cycle" in str(result.final_output)

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        """One branch fails, other succeeds → partial status."""
        reg = _build_registry(EchoTool(), FailTool())
        nodes = [
            PipelineNode(id="root", tool_name="echo", arguments={"x": 1}),
            PipelineNode(id="good", tool_name="echo", arguments={"y": 2}, depends_on=["root"]),
            PipelineNode(id="bad", tool_name="fail", depends_on=["root"]),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "partial"
        assert "root" in result.execution_path
        assert "good" in result.execution_path
        assert "bad" in result.failed_nodes


class TestPipelineComplexFlow:
    @pytest.mark.asyncio
    async def test_diamond_with_conditional_branch(self):
        """Full diamond DAG with conditional branching:"""
        reg = _build_registry(EchoTool(), MathTool(), ConditionalOutputTool())
        nodes = [
            PipelineNode(id="source", tool_name="echo", arguments={"base": 50}),
            PipelineNode(
                id="left", tool_name="math_op",
                arguments={"operation": "add", "b": 10},
                depends_on=["source"],
                input_mappings={"a": InputMapping(source_node="source", source_field="base")},
            ),
            PipelineNode(
                id="right", tool_name="math_op",
                arguments={"operation": "multiply", "b": 2},
                depends_on=["source"],
                input_mappings={"a": InputMapping(source_node="source", source_field="base")},
            ),
            PipelineNode(
                id="evaluate", tool_name="conditional_output",
                arguments={"mode": "high"},
                depends_on=["left", "right"],
                input_mappings={"value": InputMapping(source_node="right", source_field="result")},
            ),
            PipelineNode(
                id="high_action", tool_name="math_op",
                arguments={"operation": "multiply", "b": 1.5},
                depends_on=["evaluate"],
                condition=NodeCondition(source_node="evaluate", field="outlook", operator="eq", value="bullish"),
                input_mappings={"a": InputMapping(source_node="left", source_field="result")},
            ),
            PipelineNode(
                id="low_action", tool_name="math_op",
                arguments={"operation": "multiply", "b": 0.5},
                depends_on=["evaluate"],
                condition=NodeCondition(source_node="evaluate", field="outlook", operator="eq", value="bearish"),
                input_mappings={"a": InputMapping(source_node="left", source_field="result")},
            ),
            PipelineNode(
                id="final", tool_name="echo",
                arguments={"pipeline": "complete"},
                depends_on=["high_action", "low_action"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        # source(50) → left: 50+10=60, right: 50*2=100
        assert result.node_results["left"].output["result"] == 60.0
        assert result.node_results["right"].output["result"] == 100.0
        # evaluate: mode=high → bullish
        assert result.node_results["evaluate"].output["outlook"] == "bullish"
        # high_action: 60*1.5=90 (bullish taken)
        assert "high_action" in result.execution_path
        assert result.node_results["high_action"].output["result"] == 90.0
        # low_action skipped
        assert "low_action" in result.skipped_nodes
        # Final ran
        assert "final" in result.execution_path
        # Execution path is correct order
        assert result.execution_path.index("source") < result.execution_path.index("left")
        assert result.execution_path.index("evaluate") < result.execution_path.index("high_action")

    @pytest.mark.asyncio
    async def test_six_step_pipeline_with_data_flow(self):
        """6-step pipeline simulating an energy valuation:"""
        reg = _build_registry(EchoTool(), MathTool(), ConditionalOutputTool())
        nodes = [
            # Step 1: Extract data
            PipelineNode(
                id="extract",
                tool_name="echo",
                arguments={"ppa_price": 42.5, "capacity_mw": 150, "term_years": 25},
            ),
            # Step 2: Parse / enrich
            PipelineNode(
                id="parse",
                tool_name="math_op",
                arguments={"operation": "multiply", "b": 8760},
                depends_on=["extract"],
                input_mappings={"a": InputMapping(source_node="extract", source_field="capacity_mw")},
            ),
            # Step 3: Market data (parallel with step 2)
            PipelineNode(
                id="market",
                tool_name="echo",
                arguments={"electricity_price": 45.2, "gas_price": 3.85, "volatility": 0.23},
            ),
            # Step 4: Evaluate conditions
            PipelineNode(
                id="evaluate",
                tool_name="conditional_output",
                arguments={"mode": "high"},  # market price > ppa → bullish
                depends_on=["parse", "market"],
                input_mappings={"value": InputMapping(source_node="market", source_field="electricity_price")},
            ),
            # Step 5a: Bullish PnL
            PipelineNode(
                id="bullish_pnl",
                tool_name="math_op",
                arguments={"operation": "multiply", "b": 25},
                depends_on=["evaluate", "parse"],
                condition=NodeCondition(source_node="evaluate", field="outlook", operator="eq", value="bullish"),
                input_mappings={"a": InputMapping(source_node="parse", source_field="result")},
            ),
            # Step 5b: Bearish risk
            PipelineNode(
                id="bearish_risk",
                tool_name="math_op",
                arguments={"operation": "multiply", "b": 0.1},
                depends_on=["evaluate", "parse"],
                condition=NodeCondition(source_node="evaluate", field="outlook", operator="eq", value="bearish"),
                input_mappings={"a": InputMapping(source_node="parse", source_field="result")},
            ),
            # Step 6: Final valuation
            PipelineNode(
                id="final_valuation",
                tool_name="echo",
                arguments={"status": "valuation_complete"},
                depends_on=["bullish_pnl", "bearish_risk"],
            ),
        ]
        result = await PipelineExecutor(reg).execute(nodes)

        assert result.status == "completed"
        # 150 * 8760 = 1,314,000
        assert result.node_results["parse"].output["result"] == 1314000.0
        # Bullish path taken
        assert "bullish_pnl" in result.execution_path
        assert "bearish_risk" in result.skipped_nodes
        # 1,314,000 * 25 = 32,850,000
        assert result.node_results["bullish_pnl"].output["result"] == 32850000.0
        # Final completed
        assert result.execution_path[-1] == "final_valuation"
        # Verify execution order
        path = result.execution_path
        assert path.index("extract") < path.index("parse")
        assert path.index("parse") < path.index("evaluate")
        assert path.index("evaluate") < path.index("bullish_pnl")


class TestParsePipelineNodes:
    def test_round_trip(self):
        raw = [
            {
                "id": "n1",
                "tool_name": "echo",
                "arguments": {"x": 1},
                "depends_on": [],
                "condition": None,
                "input_mappings": {},
            },
            {
                "id": "n2",
                "tool_name": "math_op",
                "arguments": {"op": "add"},
                "depends_on": ["n1"],
                "condition": {
                    "source_node": "n1",
                    "field": "x",
                    "operator": "gt",
                    "value": 0,
                },
                "input_mappings": {
                    "a": {"source_node": "n1", "source_field": "x"},
                },
            },
        ]
        nodes = parse_pipeline_nodes(raw)
        assert len(nodes) == 2
        assert nodes[1].condition.operator == "gt"
        assert nodes[1].input_mappings["a"].source_node == "n1"


class TestSerializePipelineResult:
    @pytest.mark.asyncio
    async def test_serialization(self):
        reg = _build_registry(EchoTool())
        nodes = [PipelineNode(id="n1", tool_name="echo", arguments={"hello": "world"})]
        result = await PipelineExecutor(reg).execute(nodes)

        serialized = serialize_pipeline_result(result)
        assert serialized["status"] == "completed"
        assert "n1" in serialized["node_results"]
        assert serialized["node_results"]["n1"]["output"] == {"hello": "world"}
        assert isinstance(serialized["total_duration_ms"], int)

        # Should be JSON-serializable
        json.dumps(serialized)
