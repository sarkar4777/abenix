"""Tests for the grounded-response guardrail wiring.

The agent executor must mark a run as `grounding_violation` whenever
the agent was configured with `require_knowledge_search=True` but
the loop finished without ever invoking the knowledge_search tool.
Two regressions sat behind Bug #1:

  1. The executor's _grounding_violated() check fired in the
     "normal" terminal branch but multiple early-return paths
     (cache hit, sandbox timeout) skipped the check, silently
     passing a parametric-memory answer through the gate.
  2. Two upstream wrappers — ``engine.execution_router`` and
     ``apps/agent-runtime/server.py`` — built ``AgentExecutor``
     without forwarding the flag at all, so RUNTIME_MODE=remote
     and the standalone /execute HTTP entry no-op'd the guardrail.

These tests cover both surfaces. Provider calls are mocked so the
test runs offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from engine.agent_executor import (
    AgentExecutor,
    GROUNDING_REQUIRED_ERROR,
    _grounding_violated,
)
from engine.llm_router import LLMResponse, LLMRouter
from engine.tools.base import ToolRegistry


# ── pure helpers ────────────────────────────────────────────────────


def test_grounding_violated_returns_false_when_flag_off():
    """No flag → always clean, regardless of tool history."""
    assert _grounding_violated(False, []) is False
    assert _grounding_violated(False, [{"name": "anything"}]) is False


def test_grounding_violated_true_when_flag_on_and_no_search():
    """Flag on + no knowledge_search call → violation."""
    assert _grounding_violated(True, []) is True
    assert _grounding_violated(True, [{"name": "calculator"}]) is True


def test_grounding_violated_false_when_search_was_called():
    """Flag on + knowledge_search in tool_calls → clean."""
    tool_calls = [{"name": "knowledge_search", "arguments": {"q": "x"}}]
    assert _grounding_violated(True, tool_calls) is False


def test_grounding_violated_tolerates_garbage_entries():
    """Non-dict tool_call entries must not crash the check."""
    assert _grounding_violated(True, [None, "string", 42]) is True  # type: ignore[list-item]


# ── executor end-to-end (mocked LLM) ────────────────────────────────


def _mock_router(response: LLMResponse) -> LLMRouter:
    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=response)
    router._providers["anthropic"] = provider
    return router


@pytest.mark.asyncio
async def test_invoke_flags_grounding_violation_when_required_and_skipped():
    """The headline Bug #1 regression: a require_knowledge_search agent
    that returns a parametric answer must surface grounding_violation
    and the canonical error message instead of the LLM content."""
    response = LLMResponse(
        content="Paris",
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=2,
        cost=0.0001,
        latency_ms=50,
    )
    router = _mock_router(response)
    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        require_knowledge_search=True,
    )

    result = await executor.invoke("what is the capital of France?")
    assert result.grounding_violation is True
    assert result.grounding_block_source == "no_knowledge_search_invocation"
    assert result.output == GROUNDING_REQUIRED_ERROR


@pytest.mark.asyncio
async def test_invoke_passes_through_when_flag_off():
    """Default (require_knowledge_search=False) must not interfere
    with a happy-path response."""
    response = LLMResponse(
        content="Paris",
        model="claude-sonnet-4-5-20250929",
        input_tokens=10,
        output_tokens=2,
        cost=0.0001,
        latency_ms=50,
    )
    router = _mock_router(response)
    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        # explicit False — represents an unflagged agent
        require_knowledge_search=False,
    )

    result = await executor.invoke("what is the capital of France?")
    assert result.grounding_violation is False
    assert result.output == "Paris"


@pytest.mark.asyncio
async def test_stream_emits_grounding_violation_in_done_payload():
    """The streaming path must also surface grounding_violation in the
    final `done` event so the router can map to
    failure_code=GROUNDING_REQUIRED_VIOLATION."""
    from engine.llm_router import StreamEvent

    async def mock_complete(**kwargs):
        async def gen():
            yield StreamEvent(event="token", data="Paris")
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

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        require_knowledge_search=True,
    )

    events = []
    async for event in executor.stream("what is the capital of France?"):
        events.append(event)

    done_events = [e for e in events if e.event == "done"]
    assert len(done_events) == 1
    done_payload = done_events[0].data
    assert done_payload.get("grounding_violation") is True
    assert done_payload.get("error") == "grounding_required_violation"
    assert done_payload.get("grounding_block_source") == "no_knowledge_search_invocation"


@pytest.mark.asyncio
async def test_stream_clean_when_flag_off():
    """Streaming with flag off should NOT emit grounding fields."""
    from engine.llm_router import StreamEvent

    async def mock_complete(**kwargs):
        async def gen():
            yield StreamEvent(event="token", data="Paris")
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

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        require_knowledge_search=False,
    )

    events = []
    async for event in executor.stream("what is the capital of France?"):
        events.append(event)

    done_events = [e for e in events if e.event == "done"]
    assert len(done_events) == 1
    done_payload = done_events[0].data
    assert not done_payload.get("grounding_violation")
    assert "error" not in done_payload or done_payload.get("error") != "grounding_required_violation"


# ── upstream wrapper wiring (Bug #1.b) ──────────────────────────────


def test_execution_config_carries_grounding_flag():
    """The ExecutionConfig dataclass must expose require_knowledge_search
    so RUNTIME_MODE=remote forwards it. Defaults to False for back-compat."""
    from engine.execution_router import ExecutionConfig

    cfg_default = ExecutionConfig(message="hi", system_prompt="")
    assert cfg_default.require_knowledge_search is False

    cfg_on = ExecutionConfig(
        message="hi", system_prompt="", require_knowledge_search=True
    )
    assert cfg_on.require_knowledge_search is True


def test_execution_config_carries_moderation_gate():
    """Same back-compat contract for the moderation gate snapshot.
    Defaults to None (no gate) which the executor treats as a no-op."""
    from engine.execution_router import ExecutionConfig

    cfg = ExecutionConfig(message="hi", system_prompt="")
    assert cfg.moderation_gate is None

    sentinel = object()
    cfg2 = ExecutionConfig(
        message="hi", system_prompt="", moderation_gate=sentinel
    )
    assert cfg2.moderation_gate is sentinel
