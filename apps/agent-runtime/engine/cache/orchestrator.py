from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter

from engine.cache.exact_cache import ExactCache
from engine.cache.prompt_optimizer import PromptCacheOptimizer
from engine.cache.semantic_cache import SemanticCache

logger = logging.getLogger(__name__)

cache_hits = Counter(
    "abenix_cache_hits_total",
    "Cache hits by layer",
    ["layer"],
)
cache_misses = Counter(
    "abenix_cache_misses_total",
    "Cache misses (full waterfall miss)",
)


@dataclass
class CacheResult:
    hit: bool
    layer: str  # "exact", "semantic", "prompt", or "none"
    response: dict[str, Any] | None = None
    optimized_kwargs: dict[str, Any] | None = None


class CacheOrchestrator:
    def __init__(
        self,
        redis_url: str | None = None,
        enable_exact: bool = True,
        enable_semantic: bool = True,
        enable_prompt: bool = True,
    ) -> None:
        self.exact = ExactCache(redis_url) if enable_exact else None
        self.semantic = SemanticCache(redis_url) if enable_semantic else None
        self.prompt_optimizer = PromptCacheOptimizer() if enable_prompt else None

    async def check(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        system: str | None = None,
        agent_id: str = "",
        rag_context: str | None = None,
    ) -> CacheResult:
        if self.exact:
            cached = await self.exact.get(model, messages, tools, temperature)
            if cached is not None:
                cache_hits.labels(layer="exact").inc()
                return CacheResult(hit=True, layer="exact", response=cached)

        if self.semantic and agent_id:
            last_user_msg = _extract_last_user_text(messages)
            if last_user_msg:
                cached = await self.semantic.get(last_user_msg, agent_id)
                if cached is not None:
                    cache_hits.labels(layer="semantic").inc()
                    return CacheResult(hit=True, layer="semantic", response=cached)

        if self.prompt_optimizer and model.startswith("claude"):
            optimized = self.prompt_optimizer.optimize(
                messages=messages,
                system=system,
                tools=tools,
                rag_context=rag_context,
            )
            cache_hits.labels(layer="prompt").inc()
            return CacheResult(hit=False, layer="prompt", optimized_kwargs=optimized)

        cache_misses.inc()
        return CacheResult(hit=False, layer="none")

    async def store(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        response: dict[str, Any],
        agent_id: str = "",
    ) -> None:
        if _looks_like_error_fallback(response, had_tools=bool(tools)):
            logger.info("skipping cache store — response looks like an error fallback")
            return

        if self.exact:
            await self.exact.set(model, messages, tools, temperature, response)

        if self.semantic and agent_id:
            last_user_msg = _extract_last_user_text(messages)
            if last_user_msg:
                await self.semantic.set(last_user_msg, response, agent_id)

    async def close(self) -> None:
        if self.exact:
            await self.exact.close()
        if self.semantic:
            await self.semantic.close()


def _extract_last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    return block["text"]
                if isinstance(block, str):
                    return block
    return ""


_ERROR_FALLBACK_MARKERS = (
    "i apologize",
    "technical issue",
    "unable to access",
    "database configuration problem",
    "database hasn't been initialized",
    "i'm experiencing a technical",
    "encountering an error",
    "cannot access the",
    "failed to connect",
)


def _looks_like_error_fallback(response: dict[str, Any], *, had_tools: bool) -> bool:
    """Return True if this response looks like an LLM apologising because"""
    content = (response or {}).get("content") or ""
    if not isinstance(content, str):
        return False
    text = content.lower()
    has_marker = any(m in text for m in _ERROR_FALLBACK_MARKERS)
    if not has_marker:
        return False
    # If the agent was expected to use tools but didn't, that's a strong
    # signal the apology is because the tools failed. A legitimate "I
    # can't help with that" answer on an agent with no tools is fine
    # to cache.
    tool_calls = (response or {}).get("tool_calls") or []
    if had_tools and not tool_calls:
        return True
    return False
