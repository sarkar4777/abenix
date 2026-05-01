from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.agent_executor import AgentExecutor, ExecutionResult, build_tool_registry
from engine.llm_router import LLMResponse, LLMRouter
from engine.tools.base import BaseTool, ToolRegistry, ToolResult


class EchoTool(BaseTool):
    name = "echo"
    description = "Echoes back the input"
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, arguments):
        return ToolResult(content=arguments.get("text", ""), metadata={})


def _mock_router(response: LLMResponse) -> LLMRouter:
    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=response)
    router._providers["anthropic"] = provider
    return router


@pytest.mark.asyncio
async def test_invoke_simple_response():
    response = LLMResponse(
        content="Hello back!",
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=5,
        cost=0.0001,
        latency_ms=100,
    )
    router = _mock_router(response)
    registry = ToolRegistry()

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=registry,
        system_prompt="You are helpful.",
    )
    result = await executor.invoke("Hi")
    assert isinstance(result, ExecutionResult)
    assert result.output == "Hello back!"
    assert result.input_tokens == 10
    assert result.output_tokens == 5


@pytest.mark.asyncio
async def test_invoke_with_tool_call():
    call_count = 0

    async def mock_complete(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return LLMResponse(
                content="",
                model="claude-sonnet-4-5-20250929",
                input_tokens=10,
                output_tokens=5,
                cost=0.0001,
                latency_ms=100,
                tool_calls=[
                    {"id": "tc1", "name": "echo", "arguments": {"text": "hello"}}
                ],
            )
        return LLMResponse(
            content="Tool said: hello",
            model="claude-sonnet-4-5-20250929",
            input_tokens=20,
            output_tokens=10,
            cost=0.0002,
            latency_ms=150,
        )

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = mock_complete
    router._providers["anthropic"] = provider

    registry = ToolRegistry()
    registry.register(EchoTool())

    executor = AgentExecutor(llm_router=router, tool_registry=registry)
    result = await executor.invoke("Use the echo tool")
    assert result.output == "Tool said: hello"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "echo"


@pytest.mark.asyncio
async def test_invoke_max_iterations():
    response = LLMResponse(
        content="",
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=5,
        cost=0.0001,
        latency_ms=100,
        tool_calls=[{"id": "tc1", "name": "echo", "arguments": {"text": "loop"}}],
    )
    router = _mock_router(response)
    registry = ToolRegistry()
    registry.register(EchoTool())

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=registry,
        max_iterations=3,
    )
    result = await executor.invoke("Loop forever")
    assert result.output == "Max iterations reached."
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_invoke_unknown_tool():
    response = LLMResponse(
        content="",
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=5,
        cost=0.0001,
        latency_ms=100,
        tool_calls=[{"id": "tc1", "name": "nonexistent", "arguments": {}}],
    )

    call_count = 0

    async def mock_complete(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return response
        return LLMResponse(
            content="Done",
            model="claude-sonnet-4-5-20250929",
            input_tokens=5,
            output_tokens=3,
            cost=0.0001,
            latency_ms=50,
        )

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = mock_complete
    router._providers["anthropic"] = provider

    registry = ToolRegistry()
    executor = AgentExecutor(llm_router=router, tool_registry=registry)
    result = await executor.invoke("Use unknown tool")
    assert result.output == "Done"


@pytest.mark.asyncio
async def test_invoke_tracks_cost():
    response = LLMResponse(
        content="Paid response",
        model="claude-sonnet-4-5-20250929",
        input_tokens=100,
        output_tokens=50,
        cost=0.0045,
        latency_ms=200,
    )
    router = _mock_router(response)
    executor = AgentExecutor(llm_router=router, tool_registry=ToolRegistry())
    result = await executor.invoke("Cost test")
    assert result.cost == 0.0045
    assert result.model == "claude-sonnet-4-5-20250929"


@pytest.mark.asyncio
async def test_stream_simple():
    async def mock_stream(**kwargs):
        yield LLMResponse.__class__  # unused

    from engine.llm_router import StreamEvent

    async def mock_complete(**kwargs):
        async def gen():
            yield StreamEvent(event="token", data="Hi ")
            yield StreamEvent(event="token", data="there!")
            yield StreamEvent(
                event="done",
                data={
                    "model": "claude-sonnet-4-5-20250929",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost": 0.001,
                    "latency_ms": 100,
                    "tool_calls": [],
                },
            )

        return gen()

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = mock_complete
    router._providers["anthropic"] = provider

    executor = AgentExecutor(llm_router=router, tool_registry=ToolRegistry())
    events = []
    async for event in executor.stream("Hello"):
        events.append(event)

    token_events = [e for e in events if e.event == "token"]
    done_events = [e for e in events if e.event == "done"]
    assert len(token_events) == 2
    assert len(done_events) == 1


def test_build_tool_registry():
    registry = build_tool_registry(["calculator", "current_time"])
    assert "calculator" in registry.names()
    assert "current_time" in registry.names()


def test_build_tool_registry_unknown_tool():
    registry = build_tool_registry(["calculator", "nonexistent_tool"])
    assert "calculator" in registry.names()
    assert "nonexistent_tool" not in registry.names()


def test_build_tool_registry_empty():
    registry = build_tool_registry([])
    assert len(registry.names()) == 0
