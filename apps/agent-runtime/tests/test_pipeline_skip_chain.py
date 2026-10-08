from __future__ import annotations

from typing import Any

from engine.pipeline import PipelineExecutor, PipelineNode
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class Broken(BaseTool):
    name = "broken"
    description = "always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            content="url must start with http:// or https://", is_error=True
        )


class Counter(BaseTool):
    name = "counter"
    description = "counts calls"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls += 1
        return ToolResult(content="ok")


def _registry() -> tuple[ToolRegistry, Counter]:
    reg = ToolRegistry()
    reg.register(Broken())
    counter = Counter()
    reg.register(counter)
    return reg, counter


async def test_failure_skips_the_whole_downstream_chain():
    reg, counter = _registry()
    result = await PipelineExecutor(reg).execute(
        [
            PipelineNode(id="fetch", tool_name="broken"),
            PipelineNode(id="extract", tool_name="counter", depends_on=["fetch"]),
            PipelineNode(id="stats", tool_name="counter", depends_on=["extract"]),
            PipelineNode(id="summary", tool_name="counter", depends_on=["stats"]),
        ]
    )
    assert result.status == "failed"
    assert counter.calls == 0
    for nid in ("extract", "stats", "summary"):
        nr = result.node_results[nid]
        assert nr.status == "skipped"
        assert nr.error == "Dependency 'fetch' failed"


async def test_condition_skip_does_not_block_dependents():
    from engine.pipeline import NodeCondition

    reg, counter = _registry()
    result = await PipelineExecutor(reg).execute(
        [
            PipelineNode(id="a", tool_name="counter"),
            PipelineNode(
                id="maybe",
                tool_name="counter",
                depends_on=["a"],
                condition=NodeCondition(
                    source_node="a", field="__all__", operator="eq", value="never"
                ),
            ),
            PipelineNode(id="after", tool_name="counter", depends_on=["maybe"]),
        ]
    )
    assert result.node_results["maybe"].status == "skipped"
    assert result.node_results["after"].status == "completed"
