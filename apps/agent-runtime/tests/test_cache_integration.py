from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as aioredis

from engine.cache.exact_cache import ExactCache, _cache_key, TTL_SECONDS
from engine.cache.orchestrator import (
    CacheOrchestrator,
    CacheResult,
    cache_hits,
    cache_misses,
)
from engine.cache.prompt_optimizer import PromptCacheOptimizer

REDIS_URL = "redis://localhost:6379/0"
TEST_PREFIX = "abenix:exact:test_"


# ── Helpers ──────────────────────────────────────────────────


async def _redis_available() -> bool:
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not asyncio.get_event_loop_policy()
    .get_event_loop()
    .run_until_complete(_redis_available()),
    reason="Redis not available at localhost:6379",
)


@pytest.fixture
async def redis_client():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def exact_cache():
    cache = ExactCache(REDIS_URL)
    yield cache
    await cache.close()


@pytest.fixture
async def clean_exact_cache(exact_cache, redis_client):
    """Cleans up any test keys before and after the test."""
    keys = []
    async for key in redis_client.scan_iter("abenix:exact:*"):
        keys.append(key)
    if keys:
        await redis_client.delete(*keys)
    yield exact_cache
    keys = []
    async for key in redis_client.scan_iter("abenix:exact:*"):
        keys.append(key)
    if keys:
        await redis_client.delete(*keys)


MSG_HELLO = [{"role": "user", "content": "Hello, world!"}]
MSG_GOODBYE = [{"role": "user", "content": "Goodbye, world!"}]
MSG_SIMILAR = [{"role": "user", "content": "Hello world"}]
TOOLS_CALC = [
    {
        "name": "calculator",
        "description": "Math calculator",
        "input_schema": {"type": "object"},
    }
]
TOOLS_SEARCH = [
    {
        "name": "web_search",
        "description": "Search the web",
        "input_schema": {"type": "object"},
    }
]
RESPONSE_A = {
    "content": "Hi there!",
    "model": "claude-sonnet-4-5-20250929",
    "input_tokens": 10,
    "output_tokens": 5,
}
RESPONSE_B = {
    "content": "Hello again!",
    "model": "claude-sonnet-4-5-20250929",
    "input_tokens": 12,
    "output_tokens": 7,
}


# 1. ExactCache integration with real Redis


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_roundtrip(clean_exact_cache):
    cache = clean_exact_cache
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3)
    assert result is None

    await cache.set(
        "claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3, RESPONSE_A
    )
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3)
    assert result is not None
    assert result["content"] == "Hi there!"
    assert result["model"] == "claude-sonnet-4-5-20250929"
    assert result["input_tokens"] == 10


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_different_model_misses(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set(
        "claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3, RESPONSE_A
    )
    result = await cache.get("gpt-4o", MSG_HELLO, TOOLS_CALC, 0.3)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_different_messages_misses(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set(
        "claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3, RESPONSE_A
    )
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_GOODBYE, TOOLS_CALC, 0.3)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_different_tools_misses(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set(
        "claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3, RESPONSE_A
    )
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_SEARCH, 0.3)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_different_temperature_misses(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set(
        "claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.3, RESPONSE_A
    )
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, TOOLS_CALC, 0.4)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_high_temp_skipped(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.8, RESPONSE_A)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.8)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_boundary_temp(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.5, RESPONSE_A)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.5)
    assert result is not None

    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.51, RESPONSE_A)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.51)
    assert result is None


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_null_tools(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3, RESPONSE_A)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3)
    assert result is not None
    assert result["content"] == "Hi there!"


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_overwrite(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3, RESPONSE_A)
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3, RESPONSE_B)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3)
    assert result is not None
    assert result["content"] == "Hello again!"


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_ttl_set(clean_exact_cache, redis_client):
    cache = clean_exact_cache
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3, RESPONSE_A)
    key = _cache_key("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3)
    ttl = await redis_client.ttl(key)
    assert 0 < ttl <= TTL_SECONDS


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_complex_messages(clean_exact_cache):
    """Multi-turn conversation with tool results."""
    cache = clean_exact_cache
    messages = [
        {"role": "user", "content": "What is 2+2?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me calculate."},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "calculator",
                    "input": {"expr": "2+2"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "4",
                    "is_error": False,
                }
            ],
        },
    ]
    await cache.set("claude-sonnet-4-5-20250929", messages, TOOLS_CALC, 0.3, RESPONSE_A)
    result = await cache.get("claude-sonnet-4-5-20250929", messages, TOOLS_CALC, 0.3)
    assert result is not None
    assert result["content"] == "Hi there!"


# 2. PromptCacheOptimizer thorough tests


def test_prompt_optimizer_tools_only_last_gets_cache_control():
    opt = PromptCacheOptimizer()
    tools = [
        {"name": "a", "description": "A", "input_schema": {}},
        {"name": "b", "description": "B", "input_schema": {}},
        {"name": "c", "description": "C", "input_schema": {}},
    ]
    result = opt.optimize(messages=MSG_HELLO, tools=tools)
    assert "cache_control" not in result["tools"][0]
    assert "cache_control" not in result["tools"][1]
    assert result["tools"][2]["cache_control"]["type"] == "ephemeral"


def test_prompt_optimizer_single_tool_gets_cache_control():
    opt = PromptCacheOptimizer()
    tools = [{"name": "only", "description": "Only tool", "input_schema": {}}]
    result = opt.optimize(messages=MSG_HELLO, tools=tools)
    assert result["tools"][0]["cache_control"]["type"] == "ephemeral"


def test_prompt_optimizer_does_not_mutate_input_tools():
    opt = PromptCacheOptimizer()
    original = {"name": "calc", "description": "Calc", "input_schema": {}}
    tools = [original]
    opt.optimize(messages=MSG_HELLO, tools=tools)
    assert "cache_control" not in original


def test_prompt_optimizer_system_and_rag_order():
    opt = PromptCacheOptimizer()
    result = opt.optimize(
        messages=MSG_HELLO,
        system="System prompt",
        rag_context="Retrieved context about Python",
    )
    assert result["system"][0]["text"] == "System prompt"
    assert result["system"][1]["text"] == "Retrieved context about Python"
    assert all(b["cache_control"]["type"] == "ephemeral" for b in result["system"])


def test_prompt_optimizer_no_tools_no_system():
    opt = PromptCacheOptimizer()
    result = opt.optimize(messages=MSG_HELLO, tools=None, system=None)
    assert "tools" not in result
    assert "system" not in result
    assert result["messages"] == MSG_HELLO


def test_prompt_optimizer_empty_tools_list():
    opt = PromptCacheOptimizer()
    result = opt.optimize(messages=MSG_HELLO, tools=[], system="sys")
    assert "tools" not in result
    assert "system" in result


def test_prompt_optimizer_messages_passed_through():
    opt = PromptCacheOptimizer()
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    result = opt.optimize(messages=msgs, system="sys", tools=TOOLS_CALC)
    assert result["messages"] is msgs


# 3. CacheOrchestrator waterfall with real Redis


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_exact_hit_with_real_redis():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=False,
    )
    try:
        await orch.store(
            model="claude-sonnet-4-5-20250929",
            messages=MSG_HELLO,
            tools=TOOLS_CALC,
            temperature=0.3,
            response=RESPONSE_A,
            agent_id="test-agent-1",
        )

        result = await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=MSG_HELLO,
            tools=TOOLS_CALC,
            temperature=0.3,
            agent_id="test-agent-1",
        )
        assert result.hit is True
        assert result.layer == "exact"
        assert result.response["content"] == "Hi there!"
    finally:
        await orch.close()


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_miss_falls_to_prompt_for_claude():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=True,
    )
    try:
        result = await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=[{"role": "user", "content": "unique-query-" + str(time.time())}],
            tools=TOOLS_CALC,
            temperature=0.3,
            system="Be helpful.",
            agent_id="test-agent-2",
        )
        assert result.hit is False
        assert result.layer == "prompt"
        assert result.optimized_kwargs is not None
        assert "system" in result.optimized_kwargs
        system_blocks = result.optimized_kwargs["system"]
        assert system_blocks[0]["cache_control"]["type"] == "ephemeral"
    finally:
        await orch.close()


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_miss_non_claude_no_prompt():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=True,
    )
    try:
        result = await orch.check(
            model="gpt-4o",
            messages=[{"role": "user", "content": "unique-gpt-" + str(time.time())}],
            temperature=0.3,
        )
        assert result.hit is False
        assert result.layer == "none"
    finally:
        await orch.close()


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_store_and_retrieve_cycle():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=True,
    )
    try:
        msgs = [{"role": "user", "content": "store-cycle-" + str(time.time())}]

        miss = await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=msgs,
            tools=None,
            temperature=0.3,
        )
        assert miss.hit is False

        await orch.store(
            model="claude-sonnet-4-5-20250929",
            messages=msgs,
            tools=None,
            temperature=0.3,
            response=RESPONSE_B,
        )

        hit = await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=msgs,
            tools=None,
            temperature=0.3,
        )
        assert hit.hit is True
        assert hit.layer == "exact"
        assert hit.response["content"] == "Hello again!"
    finally:
        await orch.close()


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_high_temp_bypasses_exact():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=True,
    )
    try:
        msgs = [{"role": "user", "content": "high-temp-test"}]
        await orch.store(
            model="claude-sonnet-4-5-20250929",
            messages=msgs,
            tools=None,
            temperature=0.9,
            response=RESPONSE_A,
        )
        result = await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=msgs,
            tools=None,
            temperature=0.9,
        )
        assert result.layer == "prompt"
        assert result.hit is False
    finally:
        await orch.close()


@requires_redis
@pytest.mark.asyncio
async def test_orchestrator_disabled_layers():
    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=False,
        enable_semantic=False,
        enable_prompt=False,
    )
    assert orch.exact is None
    assert orch.semantic is None
    assert orch.prompt_optimizer is None

    result = await orch.check(
        model="claude-sonnet-4-5-20250929",
        messages=MSG_HELLO,
        temperature=0.3,
    )
    assert result.hit is False
    assert result.layer == "none"
    await orch.close()


# 4. Prometheus metrics


@requires_redis
@pytest.mark.asyncio
async def test_prometheus_counters_increment():
    exact_before = cache_hits.labels(layer="exact")._value.get()
    prompt_before = cache_hits.labels(layer="prompt")._value.get()
    miss_before = cache_misses._value.get()

    orch = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=True,
    )
    try:
        msgs_hit = [{"role": "user", "content": "prom-hit-" + str(time.time())}]
        await orch.store(
            model="claude-sonnet-4-5-20250929",
            messages=msgs_hit,
            tools=None,
            temperature=0.3,
            response=RESPONSE_A,
        )
        await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=msgs_hit,
            tools=None,
            temperature=0.3,
        )
        exact_after = cache_hits.labels(layer="exact")._value.get()
        assert exact_after == exact_before + 1

        msgs_miss = [{"role": "user", "content": "prom-miss-" + str(time.time())}]
        await orch.check(
            model="claude-sonnet-4-5-20250929",
            messages=msgs_miss,
            tools=None,
            temperature=0.3,
        )
        prompt_after = cache_hits.labels(layer="prompt")._value.get()
        assert prompt_after == prompt_before + 1

    finally:
        await orch.close()

    orch2 = CacheOrchestrator(
        redis_url=REDIS_URL,
        enable_exact=True,
        enable_semantic=False,
        enable_prompt=False,
    )
    try:
        msgs_full_miss = [
            {"role": "user", "content": "prom-fullmiss-" + str(time.time())}
        ]
        await orch2.check(
            model="gpt-4o",
            messages=msgs_full_miss,
            temperature=0.3,
        )
        miss_after = cache_misses._value.get()
        assert miss_after == miss_before + 1
    finally:
        await orch2.close()


# 5. AgentExecutor + Cache integration (mock LLM)


@pytest.mark.asyncio
async def test_agent_executor_cache_hit_returns_immediately():
    from engine.agent_executor import AgentExecutor, ExecutionResult
    from engine.tools.base import ToolRegistry

    mock_router = AsyncMock()
    registry = ToolRegistry()
    mock_cache = AsyncMock()
    mock_cache.check = AsyncMock(
        return_value=CacheResult(
            hit=True,
            layer="exact",
            response={
                "content": "cached answer",
                "model": "claude-sonnet-4-5-20250929",
            },
        )
    )
    mock_cache.prompt_optimizer = None

    executor = AgentExecutor(
        llm_router=mock_router,
        tool_registry=registry,
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,
        cache=mock_cache,
        agent_id="test-agent",
    )

    result = await executor.invoke("Hello")
    assert isinstance(result, ExecutionResult)
    assert result.output == "cached answer"
    assert result.cache_hit == "exact"
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    mock_router.complete.assert_not_called()


@pytest.mark.asyncio
async def test_agent_executor_cache_miss_calls_llm_and_stores():
    from engine.agent_executor import AgentExecutor
    from engine.llm_router import LLMResponse
    from engine.tools.base import ToolRegistry

    mock_response = LLMResponse(
        content="LLM response",
        model="claude-sonnet-4-5-20250929",
        input_tokens=50,
        output_tokens=20,
        cost=0.00025,
        latency_ms=200,
        tool_calls=[],
    )
    mock_router = AsyncMock()
    mock_router.complete = AsyncMock(return_value=mock_response)

    registry = ToolRegistry()
    mock_cache = AsyncMock()
    mock_cache.check = AsyncMock(return_value=CacheResult(hit=False, layer="none"))
    mock_cache.store = AsyncMock()
    mock_cache.prompt_optimizer = None

    executor = AgentExecutor(
        llm_router=mock_router,
        tool_registry=registry,
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,
        cache=mock_cache,
        agent_id="test-agent",
    )

    result = await executor.invoke("Hello")
    assert result.output == "LLM response"
    assert result.cache_hit == ""
    assert result.input_tokens == 50
    mock_router.complete.assert_called_once()
    mock_cache.store.assert_called_once()

    store_kwargs = mock_cache.store.call_args.kwargs
    assert store_kwargs["response"]["content"] == "LLM response"
    assert store_kwargs["agent_id"] == "test-agent"


@pytest.mark.asyncio
async def test_agent_executor_no_cache_still_works():
    from engine.agent_executor import AgentExecutor
    from engine.llm_router import LLMResponse
    from engine.tools.base import ToolRegistry

    mock_response = LLMResponse(
        content="normal response",
        model="gpt-4o",
        input_tokens=30,
        output_tokens=10,
        cost=0.0001,
        latency_ms=100,
        tool_calls=[],
    )
    mock_router = AsyncMock()
    mock_router.complete = AsyncMock(return_value=mock_response)

    executor = AgentExecutor(
        llm_router=mock_router,
        tool_registry=ToolRegistry(),
        model="gpt-4o",
        temperature=0.7,
    )

    result = await executor.invoke("Hello")
    assert result.output == "normal response"
    assert result.cache_hit == ""


@pytest.mark.asyncio
async def test_agent_executor_stream_cache_hit():
    from engine.agent_executor import AgentExecutor
    from engine.tools.base import ToolRegistry

    mock_router = AsyncMock()
    mock_cache = AsyncMock()
    mock_cache.check = AsyncMock(
        return_value=CacheResult(
            hit=True,
            layer="semantic",
            response={
                "content": "cached stream",
                "model": "claude-sonnet-4-5-20250929",
            },
        )
    )
    mock_cache.prompt_optimizer = None

    executor = AgentExecutor(
        llm_router=mock_router,
        tool_registry=ToolRegistry(),
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,
        cache=mock_cache,
        agent_id="test-agent",
    )

    events = []
    async for ev in executor.stream("Hello"):
        events.append(ev)

    assert len(events) == 2
    assert events[0].event == "token"
    assert events[0].data == "cached stream"
    assert events[1].event == "done"
    assert events[1].data["cache_hit"] == "semantic"
    mock_router.complete.assert_not_called()


@pytest.mark.asyncio
async def test_agent_executor_prompt_optimization_applied():
    from engine.agent_executor import AgentExecutor
    from engine.llm_router import LLMResponse
    from engine.tools.base import BaseTool, ToolRegistry, ToolResult

    mock_response = LLMResponse(
        content="optimized response",
        model="claude-sonnet-4-5-20250929",
        input_tokens=40,
        output_tokens=15,
        cost=0.0002,
        latency_ms=150,
        tool_calls=[],
    )
    mock_router = AsyncMock()
    mock_router.complete = AsyncMock(return_value=mock_response)

    mock_cache = AsyncMock()
    mock_cache.check = AsyncMock(return_value=CacheResult(hit=False, layer="prompt"))
    mock_cache.store = AsyncMock()
    mock_cache.prompt_optimizer = PromptCacheOptimizer()

    class DummyTool(BaseTool):
        name = "dummy"
        description = "dummy"
        input_schema = {"type": "object"}

        async def execute(self, args):
            return ToolResult(content="ok")

    registry = ToolRegistry()
    registry.register(DummyTool())

    executor = AgentExecutor(
        llm_router=mock_router,
        tool_registry=registry,
        system_prompt="Be helpful.",
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,
        cache=mock_cache,
        agent_id="test-agent",
    )

    await executor.invoke("test prompt optimization")

    call_kwargs = mock_router.complete.call_args.kwargs
    system_val = call_kwargs["system"]
    assert isinstance(system_val, list)
    assert system_val[0]["cache_control"]["type"] == "ephemeral"

    tools_val = call_kwargs["tools"]
    assert tools_val[-1]["cache_control"]["type"] == "ephemeral"


# 6. Edge cases


def test_cache_key_empty_messages():
    key = _cache_key("model", [], None, 0.0)
    assert key.startswith("abenix:exact:")
    assert len(key) > 20


def test_cache_key_unicode_content():
    msgs = [{"role": "user", "content": "Bonjour le monde! \u2603 \ud83d\ude80"}]
    key = _cache_key("model", msgs, None, 0.3)
    assert key.startswith("abenix:exact:")


def test_cache_key_large_payload():
    large_msg = [{"role": "user", "content": "x" * 100_000}]
    key = _cache_key("model", large_msg, None, 0.3)
    assert len(key) == len("abenix:exact:") + 64


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_empty_response(clean_exact_cache):
    cache = clean_exact_cache
    await cache.set("model", MSG_HELLO, None, 0.3, {"content": "", "model": "model"})
    result = await cache.get("model", MSG_HELLO, None, 0.3)
    assert result is not None
    assert result["content"] == ""


@requires_redis
@pytest.mark.asyncio
async def test_exact_cache_nested_json_response(clean_exact_cache):
    cache = clean_exact_cache
    nested = {
        "content": "answer",
        "model": "claude-sonnet-4-5-20250929",
        "metadata": {"tags": ["a", "b"], "nested": {"key": "val"}},
    }
    await cache.set("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3, nested)
    result = await cache.get("claude-sonnet-4-5-20250929", MSG_HELLO, None, 0.3)
    assert result["metadata"]["nested"]["key"] == "val"


@pytest.mark.asyncio
async def test_orchestrator_no_agent_id_skips_semantic():
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.get = AsyncMock(return_value=None)
    orch.semantic = AsyncMock()
    orch.semantic.get = AsyncMock(return_value=RESPONSE_A)
    orch.prompt_optimizer = None

    result = await orch.check(
        model="gpt-4o",
        messages=MSG_HELLO,
        temperature=0.3,
        agent_id="",
    )
    assert result.hit is False
    assert result.layer == "none"
    orch.semantic.get.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_store_no_agent_id_skips_semantic():
    orch = CacheOrchestrator.__new__(CacheOrchestrator)
    orch.exact = AsyncMock()
    orch.exact.set = AsyncMock()
    orch.semantic = AsyncMock()
    orch.semantic.set = AsyncMock()

    await orch.store(
        model="gpt-4o",
        messages=MSG_HELLO,
        tools=None,
        temperature=0.3,
        response=RESPONSE_A,
        agent_id="",
    )
    orch.exact.set.assert_called_once()
    orch.semantic.set.assert_not_called()
