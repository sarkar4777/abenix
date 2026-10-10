"""An agent that runs out of steps answers from what it gathered."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from engine.agent_executor import AgentExecutor
from engine.llm_router import LLMResponse, LLMRouter, StreamEvent
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes back the input"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, arguments):
        return ToolResult(content=arguments.get("text", ""), metadata={})


def _executor(final_text: str):
    calls: list[dict] = []

    async def complete(**kwargs):
        calls.append(kwargs)
        last = kwargs["messages"][-1]
        content = last.get("content")
        asked_to_stop = "used all the steps" in str(content)
        if asked_to_stop:
            # the final turn offers no tools, so the model has to answer in text
            assert not kwargs.get("tools")
            return LLMResponse(
                content=final_text,
                model="claude-sonnet-4-5",
                input_tokens=7,
                output_tokens=3,
                cost=0.0,
                latency_ms=1,
            )
        tc = {"id": f"t{len(calls)}", "name": "echo", "arguments": {"text": "x"}}
        if kwargs.get("stream"):

            async def gen():
                yield StreamEvent(event="tool_call", data=tc)
                yield StreamEvent(
                    event="done",
                    data={
                        "model": "claude-sonnet-4-5",
                        "input_tokens": 5,
                        "output_tokens": 1,
                        "cost": 0.0,
                        "tool_calls": [tc],
                    },
                )

            return gen()
        return LLMResponse(
            content="",
            model="claude-sonnet-4-5",
            input_tokens=5,
            output_tokens=1,
            cost=0.0,
            latency_ms=1,
            tool_calls=[
                {"id": f"t{len(calls)}", "name": "echo", "arguments": {"text": "x"}}
            ],
        )

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = complete
    router._providers["anthropic"] = provider
    reg = ToolRegistry()
    reg.register(EchoTool())
    ex = AgentExecutor(llm_router=router, tool_registry=reg, max_iterations=3)
    return ex, calls


@pytest.mark.asyncio
async def test_step_limit_gives_a_final_answer():
    ex, calls = _executor('{"coded_terms": []}')
    result = await ex.invoke("code these")
    assert result.output == '{"coded_terms": []}'
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_step_limit_falls_back_when_no_answer():
    ex, _ = _executor("")
    result = await ex.invoke("code these")
    assert result.output == "Max iterations reached."


@pytest.mark.asyncio
async def test_streamed_step_limit_gives_a_final_answer():
    ex, _ = _executor('{"fields": []}')
    tokens = []
    async for ev in ex.stream("extract these"):
        if ev.event == "token":
            tokens.append(ev.data if isinstance(ev.data, str) else "")
    assert '{"fields": []}' in "".join(tokens)


def test_tool_history_is_written_out_as_text():
    from engine.agent_executor import _tools_as_text

    msgs = [
        {"role": "user", "content": "extract"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "checking"},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "ml_model",
                    "input": {"op": "list"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "19 models"}
            ],
        },
    ]
    out = _tools_as_text(msgs)
    assert all(isinstance(m["content"], str) for m in out)
    assert "[called ml_model" in out[1]["content"]
    assert "[tool result: 19 models]" in out[2]["content"]
