"""Text from separate turns of a tool loop must not run together in the joined reply."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from engine.agent_executor import AgentExecutor
from engine.llm_router import LLMRouter, StreamEvent
from engine.tools.base import READ_ONLY, BaseTool, ToolRegistry, ToolResult


class Lookup(BaseTool):
    name = "lookup"
    description = "Looks something up"
    risk_tier = "low"
    effect = READ_ONLY
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content="Paris")


def _router(first_text: str, second_text: str) -> LLMRouter:
    turns = {"n": 0}

    async def complete(**kwargs):
        turns["n"] += 1
        first = turns["n"] == 1

        async def gen():
            yield StreamEvent(event="token", data=first_text if first else second_text)
            yield StreamEvent(
                event="done",
                data={
                    "model": "claude-sonnet-4-5-20250929",
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost": 0.0,
                    "latency_ms": 1,
                    "tool_calls": (
                        [{"id": "tc1", "name": "lookup", "arguments": {}}]
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


async def _reply(first_text: str, second_text: str) -> str:
    reg = ToolRegistry()
    reg.register(Lookup())
    ex = AgentExecutor(llm_router=_router(first_text, second_text), tool_registry=reg)
    return "".join([e.data async for e in ex.stream("capital?") if e.event == "token"])


async def test_turns_are_separated_in_the_joined_reply():
    reply = await _reply("Let me look that up for you.", "The capital is Paris.")
    assert reply == "Let me look that up for you.\n\nThe capital is Paris."


@pytest.mark.parametrize(
    "first,second",
    [("Checking. ", "Paris."), ("Checking.", " Paris."), ("", "Paris.")],
)
async def test_no_extra_gap_when_the_turn_already_has_one(first, second):
    assert "\n" not in await _reply(first, second)
