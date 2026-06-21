"""Tests for the moderation gate firing on /api/agents/{id}/execute.

Bug #2 was that PII input ("My SSN is 999-12-3456 and my credit card
is 4532-1234-5678-9010") streamed through the agent loop with no
moderation block event. Two surfaces had to change:

  1. AgentExecutor's pre-LLM gate must enforce a BLOCK before the
     LLM ever sees the prompt and surface moderation_blocked on the
     result (already covered by test_moderation.py's gate tests,
     but here we assert the END-TO-END executor wiring).
  2. The default ModerationPolicy seeded for new tenants must ship
     with PII regex patterns so the gate fires on the documented
     repro input out of the box (previously custom_patterns was
     empty, so SSN/CC slipped through every fresh tenant).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from engine.agent_executor import AgentExecutor
from engine.llm_router import LLMResponse, LLMRouter
from engine.moderation_gate import GateConfig
from engine.tools.base import ToolRegistry


SSN_PROMPT = "My SSN is 999-12-3456"
CC_PROMPT = "card 4532-1234-5678-9010"


def _mock_router(response: LLMResponse) -> LLMRouter:
    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=response)
    router._providers["anthropic"] = provider
    return router


def _mock_provider_clean():
    """OpenAI moderation says "clean" — relies on custom_patterns alone."""

    async def fake(_content, model="omni-moderation-latest"):
        return {
            "results": [
                {
                    "flagged": False,
                    "categories": {},
                    "category_scores": {},
                }
            ]
        }

    return fake


@pytest.mark.asyncio
async def test_executor_blocks_pii_when_policy_has_ssn_pattern():
    """End-to-end: PII input + a policy with the SSN regex must mark
    the run moderation_blocked BEFORE any LLM call fires."""
    llm_called = False

    async def llm_panic(**kwargs):  # pragma: no cover — must NOT run
        nonlocal llm_called
        llm_called = True
        raise AssertionError("LLM must not be called when the gate blocks")

    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = llm_panic
    router._providers["anthropic"] = provider

    gate = GateConfig(
        pre_llm=True,
        default_action="block",
        custom_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"],
    )

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        moderation_gate=gate,
    )

    with patch(
        "engine.moderation_client._call_openai", new=_mock_provider_clean()
    ):
        result = await executor.invoke(SSN_PROMPT)

    assert result.moderation_blocked is True
    assert result.moderation_block_source == "pre_llm"
    assert llm_called is False


@pytest.mark.asyncio
async def test_executor_redacts_pii_when_policy_redact():
    """REDACT action: the LLM should see the masked text, not the raw SSN."""
    seen_prompts: list[str] = []

    async def capture_complete(**kwargs):
        messages = kwargs.get("messages") or []
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                seen_prompts.append(content)
        return LLMResponse(
            content="ok",
            model="claude-sonnet-4-5-20250929",
            input_tokens=5,
            output_tokens=2,
            cost=0.0,
            latency_ms=10,
        )

    router = LLMRouter()
    provider = AsyncMock()
    provider.complete = capture_complete
    router._providers["anthropic"] = provider

    gate = GateConfig(
        pre_llm=True,
        default_action="redact",
        custom_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"],
        redaction_mask="[SSN]",
    )

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        moderation_gate=gate,
    )

    with patch(
        "engine.moderation_client._call_openai", new=_mock_provider_clean()
    ):
        result = await executor.invoke(SSN_PROMPT)

    # No block — the redacted form was forwarded.
    assert result.moderation_blocked is False
    assert any("999-12-3456" not in p for p in seen_prompts)
    assert any("[SSN]" in p for p in seen_prompts)


@pytest.mark.asyncio
async def test_executor_passes_clean_input_unchanged_under_block_policy():
    """A normal-looking message must round-trip untouched even with a
    PII-blocking policy active. Belt-and-suspenders for regressions."""
    response = LLMResponse(
        content="hello",
        model="claude-sonnet-4-5-20250929",
        input_tokens=4,
        output_tokens=2,
        cost=0.0,
        latency_ms=10,
    )
    router = _mock_router(response)

    gate = GateConfig(
        pre_llm=True,
        default_action="block",
        custom_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"],
    )

    executor = AgentExecutor(
        llm_router=router,
        tool_registry=ToolRegistry(),
        moderation_gate=gate,
    )

    with patch(
        "engine.moderation_client._call_openai", new=_mock_provider_clean()
    ):
        result = await executor.invoke("How do I export a CSV from Excel?")

    assert result.moderation_blocked is False
    assert result.output == "hello"


def test_default_pii_patterns_cover_ssn_and_credit_card():
    """The DEFAULT_PII_PATTERNS list seeded into every new tenant's
    policy must include the patterns the user's repro exercises."""
    from app.core.moderation_glue import DEFAULT_PII_PATTERNS

    import re

    # SSN
    assert any(re.search(p, SSN_PROMPT) for p in DEFAULT_PII_PATTERNS)
    # Credit card
    assert any(re.search(p, CC_PROMPT) for p in DEFAULT_PII_PATTERNS)
