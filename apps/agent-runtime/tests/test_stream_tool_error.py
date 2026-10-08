from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from engine.llm_router import LLMRouter, StreamEvent
from engine.tools.base import READ_ONLY, BaseTool, ToolRegistry, ToolResult


class Dead(BaseTool):
    name = "dead_feed"
    description = "Reads a feed that is down"
    risk_tier = "low"
    effect = READ_ONLY
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            content="HTTP request failed: name not resolved", is_error=True
        )


def _router() -> LLMRouter:
    turns = {"n": 0}

    async def complete(**kwargs):
        turns["n"] += 1
        first = turns["n"] == 1

        async def gen():
            if not first:
                yield StreamEvent(event="token", data="the feed is down")
            yield StreamEvent(
                event="done",
                data={
                    "model": "claude-sonnet-4-5-20250929",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost": 0.0,
                    "latency_ms": 1,
                    "tool_calls": (
                        [{"id": "tc1", "name": "dead_feed", "arguments": {}}]
                        if first
                        else []
                    ),
                },
            )

        return gen()

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = complete
    router._providers["anthropic"] = provider
    return router


async def test_stream_tool_result_says_when_the_tool_failed():
    from engine.agent_executor import AgentExecutor

    reg = ToolRegistry()
    reg.register(Dead())
    ex = AgentExecutor(llm_router=_router(), tool_registry=reg)
    events = [e async for e in ex.stream("rate?")]
    tr = next(e for e in events if e.event == "tool_result").data
    assert tr["is_error"] is True
    assert tr["result"].startswith("HTTP request failed")
