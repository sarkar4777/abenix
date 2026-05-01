from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.llm_router import (
    LLMResponse,
    LLMRouter,
    MODEL_TO_PROVIDER,
    PRICING,
    StreamEvent,
    _calc_cost,
)


def test_calc_cost_known_model():
    cost = _calc_cost("gpt-4o", 1000, 500)
    expected = 1000 * PRICING["gpt-4o"]["input"] + 500 * PRICING["gpt-4o"]["output"]
    assert cost == pytest.approx(expected)


def test_calc_cost_unknown_model():
    cost = _calc_cost("unknown-model", 1000, 500)
    assert cost == 0.0


def test_model_to_provider_mapping():
    assert MODEL_TO_PROVIDER["gpt-4o"] == "openai"
    assert MODEL_TO_PROVIDER["claude-sonnet-4-5-20250929"] == "anthropic"
    assert MODEL_TO_PROVIDER["gemini-2.0-flash"] == "google"


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_router_route_by_model():
    router = LLMRouter()
    provider = router.route("gpt-4o")
    assert provider.__class__.__name__ == "OpenAIProvider"


def test_router_route_claude_prefix():
    router = LLMRouter()
    provider = router.route("claude-new-model")
    assert provider.__class__.__name__ == "AnthropicProvider"


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_router_route_gpt_prefix():
    router = LLMRouter()
    provider = router.route("gpt-5-turbo")
    assert provider.__class__.__name__ == "OpenAIProvider"


@patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"})
def test_router_route_gemini_prefix():
    router = LLMRouter()
    provider = router.route("gemini-3.0-ultra")
    assert provider.__class__.__name__ == "GoogleProvider"


def test_router_route_unknown_defaults_anthropic():
    router = LLMRouter()
    provider = router.route("random-model-name")
    assert provider.__class__.__name__ == "AnthropicProvider"


@patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
def test_router_caches_providers():
    router = LLMRouter()
    p1 = router.route("gpt-4o")
    p2 = router.route("gpt-4o")
    assert p1 is p2


@pytest.mark.asyncio
async def test_router_complete_non_stream():
    router = LLMRouter()
    mock_response = LLMResponse(
        content="Hello!",
        model="gpt-4o",
        input_tokens=10,
        output_tokens=5,
        cost=0.001,
        latency_ms=100,
    )

    provider_mock = AsyncMock()
    provider_mock.complete = AsyncMock(return_value=mock_response)
    router._providers["openai"] = provider_mock

    result = await router.complete(
        messages=[{"role": "user", "content": "Hi"}],
        model="gpt-4o",
        stream=False,
    )
    assert isinstance(result, LLMResponse)
    assert result.content == "Hello!"
    assert result.input_tokens == 10


@pytest.mark.asyncio
async def test_router_retry_on_failure():
    router = LLMRouter()

    call_count = 0
    async def failing_then_success(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        return LLMResponse(
            content="OK",
            model="gpt-4o",
            input_tokens=5,
            output_tokens=3,
            cost=0.0001,
            latency_ms=50,
        )

    provider_mock = MagicMock()
    provider_mock.complete = failing_then_success
    router._providers["openai"] = provider_mock

    with patch("engine.llm_router.asyncio.sleep", new_callable=AsyncMock):
        result = await router.complete(
            messages=[{"role": "user", "content": "Test"}],
            model="gpt-4o",
            stream=False,
        )
    assert result.content == "OK"
    assert call_count == 3


@pytest.mark.asyncio
async def test_router_raises_after_max_retries():
    router = LLMRouter()

    async def always_fail(**kwargs):
        raise ValueError("Permanent failure")

    provider_mock = MagicMock()
    provider_mock.complete = always_fail
    router._providers["openai"] = provider_mock

    with patch("engine.llm_router.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ValueError, match="Permanent failure"):
            await router.complete(
                messages=[{"role": "user", "content": "Test"}],
                model="gpt-4o",
                stream=False,
            )


def test_llm_response_fields():
    r = LLMResponse(
        content="text",
        model="test",
        input_tokens=100,
        output_tokens=50,
        cost=0.01,
        latency_ms=200,
        tool_calls=[{"id": "1", "name": "calc", "arguments": {}}],
    )
    assert r.content == "text"
    assert r.tool_calls[0]["name"] == "calc"


def test_stream_event_fields():
    e = StreamEvent(event="token", data="hello")
    assert e.event == "token"
    assert e.data == "hello"


def test_pricing_has_all_mapped_models():
    for model in MODEL_TO_PROVIDER:
        if model in PRICING:
            assert "input" in PRICING[model]
            assert "output" in PRICING[model]
