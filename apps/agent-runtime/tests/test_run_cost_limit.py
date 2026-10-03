"""A plain agent run stops at its per-run cost limit with BUDGET_EXCEEDED."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.agent_budget import BUDGET_EXCEEDED, run_cost_limit
from engine.agent_executor import AgentExecutor
from engine.llm_router import LLMResponse
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class CountTool(BaseTool):
    name = "lookup"
    description = "Looks something up"
    input_schema = {"type": "object", "properties": {"q": {"type": "string"}}}

    def __init__(self) -> None:
        self.runs = 0

    async def execute(self, arguments):
        self.runs += 1
        return ToolResult(content=f"result {self.runs}", metadata={})


def _tool_call(n: int) -> dict:
    return {"id": f"t{n}", "name": "lookup", "arguments": {"q": str(n)}}


class Router:
    """Answers with a tool call every turn at a fixed cost, or a final answer when told to."""

    def __init__(self, cost: float, final_after: int | None = None) -> None:
        self.cost = cost
        self.final_after = final_after
        self.calls = 0

    async def complete(self, **kw):
        self.calls += 1
        final = self.final_after is not None and self.calls > self.final_after
        text = "done" if final else f"thinking {self.calls}"
        calls = [] if final else [_tool_call(self.calls)]
        if not kw.get("stream"):
            return LLMResponse(
                content=text,
                model="claude-sonnet-4-5",
                input_tokens=10,
                output_tokens=5,
                cost=self.cost,
                latency_ms=1,
                tool_calls=calls,
            )

        async def gen():
            yield SimpleNamespace(event="token", data=text)
            for c in calls:
                yield SimpleNamespace(event="tool_call", data=c)
            yield SimpleNamespace(
                event="done",
                data={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost": self.cost,
                    "model": "claude-sonnet-4-5",
                    "tool_calls": calls,
                },
            )

        return gen()


def _executor(router: Router, cost_limit, max_iterations: int = 10):
    tool = CountTool()
    reg = ToolRegistry()
    reg.register(tool)
    ex = AgentExecutor(
        llm_router=router,
        tool_registry=reg,
        max_iterations=max_iterations,
        cost_limit=cost_limit,
        model="claude-sonnet-4-5",
    )
    return ex, tool


def test_run_cost_limit_takes_the_tightest_positive_cap():
    assert run_cost_limit(None, 0, "") is None
    assert run_cost_limit(2.0, None, 0.5) == 0.5
    assert run_cost_limit("1.25") == 1.25
    assert run_cost_limit(-1, "junk") is None


@pytest.mark.asyncio
async def test_invoke_stops_after_the_call_that_reaches_the_limit():
    router = Router(cost=0.4)
    ex, tool = _executor(router, cost_limit=1.0)
    result = await ex.invoke("go")
    assert router.calls == 3
    assert tool.runs == 2
    assert result.budget_exceeded is True
    assert result.failure_code == BUDGET_EXCEEDED
    assert result.cost == pytest.approx(1.2)
    assert "per-run budget of $1.00" in result.output
    assert result.output.startswith("thinking 3")
    assert len(result.tool_calls) == 2
    assert result.node_traces[-1].node_type == "budget_stop"
    assert result.node_traces[-1].output_data["spent"] == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_a_final_answer_on_the_last_paid_call_is_kept():
    router = Router(cost=0.6, final_after=1)
    ex, tool = _executor(router, cost_limit=1.0)
    result = await ex.invoke("go")
    assert result.budget_exceeded is False
    assert result.failure_code == ""
    assert result.output == "done"
    assert tool.runs == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [None, 0, -5])
async def test_no_cap_means_no_stop(cap):
    router = Router(cost=5.0)
    ex, tool = _executor(router, cost_limit=cap, max_iterations=3)
    result = await ex.invoke("go")
    assert result.budget_exceeded is False
    assert tool.runs == 3


@pytest.mark.asyncio
async def test_stream_stops_with_a_done_event_carrying_the_code():
    router = Router(cost=0.3)
    ex, tool = _executor(router, cost_limit=0.5)
    events = [e async for e in ex.stream("go")]
    done = events[-1]
    assert done.event == "done"
    assert done.data["failure_code"] == BUDGET_EXCEEDED
    assert done.data["budget_exceeded"] is True
    assert "per-run budget of $0.50" in done.data["error"]
    assert done.data["cost"] == pytest.approx(0.6)
    assert router.calls == 2 and tool.runs == 1
    tokens = "".join(e.data for e in events if e.event == "token")
    assert "thinking 1" in tokens and "per-run budget" in tokens
    stops = [
        e
        for e in events
        if e.event == "node_trace" and e.data["node_type"] == "budget_stop"
    ]
    assert len(stops) == 1
    assert ex.get_trace_summary()[-1]["node_type"] == "budget_stop"
    assert [t["node_type"] for t in ex.get_trace_summary()] == [
        "tool_call",
        "budget_stop",
    ]
