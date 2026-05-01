from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from engine.cache.exact_cache import ExactCache, _cache_key
from engine.cache.prompt_optimizer import PromptCacheOptimizer
from engine.cache.orchestrator import (
    CacheOrchestrator,
    _extract_last_user_text,
)

# ── ExactCache ────────────────────────────────────────────────


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def exact_cache(fake_redis: FakeRedis) -> ExactCache:
    cache = ExactCache.__new__(ExactCache)
    cache._redis = fake_redis
    return cache


SAMPLE_MESSAGES = [{"role": "user", "content": "Hello"}]
SAMPLE_TOOLS = [{"name": "calc", "description": "Calculator", "input_schema": {}}]
SAMPLE_RESPONSE = {"content": "Hi there!", "model": "claude-sonnet-4-5-20250929"}


@pytest.mark.asyncio
async def test_exact_cache_miss(exact_cache: ExactCache) -> None:
    result = await exact_cache.get(
        "claude-sonnet-4-5-20250929", SAMPLE_MESSAGES, SAMPLE_TOOLS, 0.3
    )
    assert result is None


@pytest.mark.asyncio
async def test_exact_cache_hit(exact_cache: ExactCache) -> None:
    await exact_cache.set(
        "claude-sonnet-4-5-20250929",
        SAMPLE_MESSAGES,
        SAMPLE_TOOLS,
        0.3,
        SAMPLE_RESPONSE,
    )
    result = await exact_cache.get(
        "claude-sonnet-4-5-20250929", SAMPLE_MESSAGES, SAMPLE_TOOLS, 0.3
    )
    assert result is not None
    assert result["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_exact_cache_skips_high_temperature(exact_cache: ExactCache) -> None:
    await exact_cache.set(
        "claude-sonnet-4-5-20250929",
        SAMPLE_MESSAGES,
        SAMPLE_TOOLS,
        0.8,
        SAMPLE_RESPONSE,
    )
    result = await exact_cache.get(
        "claude-sonnet-4-5-20250929", SAMPLE_MESSAGES, SAMPLE_TOOLS, 0.8
    )
    assert result is None


@pytest.mark.asyncio
async def test_exact_cache_different_messages_miss(exact_cache: ExactCache) -> None:
    await exact_cache.set(
        "claude-sonnet-4-5-20250929",
        SAMPLE_MESSAGES,
        SAMPLE_TOOLS,
        0.3,
        SAMPLE_RESPONSE,
    )
    different = [{"role": "user", "content": "Goodbye"}]
    result = await exact_cache.get(
        "claude-sonnet-4-5-20250929", different, SAMPLE_TOOLS, 0.3
    )
    assert result is None


def test_cache_key_deterministic() -> None:
    key1 = _cache_key("model", SAMPLE_MESSAGES, SAMPLE_TOOLS, 0.3)
    key2 = _cache_key("model", SAMPLE_MESSAGES, SAMPLE_TOOLS, 0.3)
    assert key1 == key2
    assert key1.startswith("abenix:exact:")


def test_cache_key_different_inputs() -> None:
    key1 = _cache_key("model-a", SAMPLE_MESSAGES, None, 0.3)
    key2 = _cache_key("model-b", SAMPLE_MESSAGES, None, 0.3)
    assert key1 != key2


# ── PromptCacheOptimizer ──────────────────────────────────────


def test_prompt_optimizer_tool_caching() -> None:
    optimizer = PromptCacheOptimizer()
    result = optimizer.optimize(
        messages=SAMPLE_MESSAGES,
        system="You are helpful.",
        tools=SAMPLE_TOOLS,
    )

    assert "cache_control" in result["tools"][-1]
    assert result["tools"][-1]["cache_control"]["type"] == "ephemeral"


def test_prompt_optimizer_system_caching() -> None:
    optimizer = PromptCacheOptimizer()
    result = optimizer.optimize(
        messages=SAMPLE_MESSAGES,
        system="System prompt here.",
        tools=None,
    )

    assert len(result["system"]) == 1
    assert result["system"][0]["cache_control"]["type"] == "ephemeral"


def test_prompt_optimizer_rag_context() -> None:
    optimizer = PromptCacheOptimizer()
    result = optimizer.optimize(
        messages=SAMPLE_MESSAGES,
        system="System prompt.",
        tools=None,
        rag_context="Retrieved docs here.",
    )

    assert len(result["system"]) == 2
    assert result["system"][1]["text"] == "Retrieved docs here."
    assert result["system"][1]["cache_control"]["type"] == "ephemeral"


def test_prompt_optimizer_no_system() -> None:
    optimizer = PromptCacheOptimizer()
    result = optimizer.optimize(messages=SAMPLE_MESSAGES, system=None, tools=None)
    assert "system" not in result
    assert result["messages"] == SAMPLE_MESSAGES


# ── CacheOrchestrator ────────────────────────────────────────


def test_extract_last_user_text_string() -> None:
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    assert _extract_last_user_text(msgs) == "second"


def test_extract_last_user_text_blocks() -> None:
    msgs = [{"role": "user", "content": [{"type": "text", "text": "from blocks"}]}]
    assert _extract_last_user_text(msgs) == "from blocks"


def test_extract_last_user_text_empty() -> None:
    assert _extract_last_user_text([]) == ""


@pytest.mark.asyncio
async def test_orchestrator_exact_hit() -> None:
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.get = AsyncMock(return_value=SAMPLE_RESPONSE)
    orch.semantic = None
    orch.prompt_optimizer = None

    result = await orch.check(
        model="claude-sonnet-4-5-20250929",
        messages=SAMPLE_MESSAGES,
        temperature=0.3,
    )
    assert result.hit is True
    assert result.layer == "exact"
    assert result.response == SAMPLE_RESPONSE


@pytest.mark.asyncio
async def test_orchestrator_semantic_hit() -> None:
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.get = AsyncMock(return_value=None)
    orch.semantic = AsyncMock()
    orch.semantic.get = AsyncMock(return_value=SAMPLE_RESPONSE)
    orch.prompt_optimizer = None

    result = await orch.check(
        model="claude-sonnet-4-5-20250929",
        messages=SAMPLE_MESSAGES,
        temperature=0.3,
        agent_id="agent-123",
    )
    assert result.hit is True
    assert result.layer == "semantic"
    assert result.response == SAMPLE_RESPONSE


@pytest.mark.asyncio
async def test_orchestrator_full_miss() -> None:
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.get = AsyncMock(return_value=None)
    orch.semantic = AsyncMock()
    orch.semantic.get = AsyncMock(return_value=None)
    orch.prompt_optimizer = None

    result = await orch.check(
        model="gpt-4o",
        messages=SAMPLE_MESSAGES,
        temperature=0.3,
        agent_id="agent-123",
    )
    assert result.hit is False
    assert result.layer == "none"


@pytest.mark.asyncio
async def test_orchestrator_prompt_optimization_for_claude() -> None:
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.get = AsyncMock(return_value=None)
    orch.semantic = AsyncMock()
    orch.semantic.get = AsyncMock(return_value=None)
    orch.prompt_optimizer = PromptCacheOptimizer()

    result = await orch.check(
        model="claude-sonnet-4-5-20250929",
        messages=SAMPLE_MESSAGES,
        system="Be helpful.",
        tools=SAMPLE_TOOLS,
        temperature=0.3,
        agent_id="agent-123",
    )
    assert result.hit is False
    assert result.layer == "prompt"
    assert result.optimized_kwargs is not None
    assert "system" in result.optimized_kwargs


@pytest.mark.asyncio
async def test_orchestrator_store() -> None:
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.set = AsyncMock()
    orch.semantic = AsyncMock()
    orch.semantic.set = AsyncMock()

    await orch.store(
        model="claude-sonnet-4-5-20250929",
        messages=SAMPLE_MESSAGES,
        tools=None,
        temperature=0.3,
        response=SAMPLE_RESPONSE,
        agent_id="agent-123",
    )

    orch.exact.set.assert_called_once()
    orch.semantic.set.assert_called_once()
