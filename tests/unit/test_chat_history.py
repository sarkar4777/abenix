"""Chat memory: thread history shaping and the executor sending it to the LLM."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.chat_history import shape_history
from app.schemas.agents import ExecuteRequest
from engine.agent_executor import AgentExecutor
from engine.execution_router import ExecutionConfig
from engine.llm_router import LLMResponse, LLMRouter
from engine.tools.base import ToolRegistry


def test_shape_history_alternates_and_drops_trailing_user():
    rows = [
        ("assistant", "orphan greeting"),
        ("user", "the code word is PELICAN"),
        ("assistant", "Got it."),
        ("user", "first"),
        ("user", "second"),
        ("assistant", "ok"),
        ("system", "ignored"),
        ("user", "what is the code word?"),
    ]
    out = shape_history(rows)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"]
    assert out[0]["content"] == "the code word is PELICAN"
    assert out[2]["content"] == "first\n\nsecond"


def test_shape_history_drops_oldest_past_budget():
    rows = []
    for i in range(10):
        rows.append(("user", f"q{i} " + "x" * 400))
        rows.append(("assistant", f"a{i} " + "y" * 400))
    out = shape_history(rows, budget_tokens=500)
    assert out and out[0]["role"] == "user"
    assert out[-1]["content"].startswith("a9")
    assert not any(m["content"].startswith("q0") for m in out)
    assert sum(len(m["content"]) for m in out) <= 500 * 4


def test_shape_history_empty():
    assert shape_history([]) == []
    assert shape_history([("user", "only the new message")]) == []


def test_execute_request_accepts_conversation_id():
    req = ExecuteRequest(message="hi", conversation_id="abc")
    assert req.conversation_id == "abc"
    assert ExecuteRequest(message="hi").conversation_id is None


def test_execution_config_carries_history():
    cfg = ExecutionConfig(
        message="m", system_prompt="", history=[{"role": "user", "content": "x"}]
    )
    assert cfg.history[0]["content"] == "x"
    assert ExecutionConfig(message="m", system_prompt="").history == []


@pytest.mark.asyncio
async def test_executor_sends_history_before_new_message_and_skips_cache():
    seen: list[list[dict]] = []

    async def capture(**kwargs):
        seen.append(list(kwargs.get("messages") or []))
        return LLMResponse(
            content="PELICAN",
            model="claude-sonnet-4-5-20250929",
            input_tokens=5,
            output_tokens=1,
            cost=0.0,
            latency_ms=1,
            stop_reason="end_turn",
        )

    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = capture
    router._providers["anthropic"] = provider
    cache = AsyncMock()
    cache.prompt_optimizer = None
    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        cache=cache,
        history=[
            {"role": "user", "content": "the code word is PELICAN"},
            {"role": "assistant", "content": "Noted."},
            {"role": "tool", "content": "dropped"},
            {"role": "assistant", "content": ""},
        ],
    )
    result = await executor.invoke("what is the code word?")

    assert result.output == "PELICAN"
    msgs = seen[0]
    assert [m["role"] for m in msgs[:3]] == ["user", "assistant", "user"]
    assert msgs[0]["content"] == "the code word is PELICAN"
    assert msgs[2]["content"] == "what is the code word?"
    cache.check.assert_not_called()
    cache.store.assert_not_called()


def test_executor_without_history_keeps_single_message_default():
    executor = AgentExecutor(llm_router=LLMRouter(), tool_registry=ToolRegistry())
    assert executor.history == []
