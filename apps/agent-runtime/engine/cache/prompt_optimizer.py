from __future__ import annotations

from typing import Any

EPHEMERAL = {"type": "ephemeral"}


class PromptCacheOptimizer:
    """Structures Anthropic API calls to maximize prompt cache hits."""

    def optimize(
        self,
        *,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        rag_context: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if tools:
            optimized_tools = []
            for i, tool in enumerate(tools):
                t = dict(tool)
                if i == len(tools) - 1:
                    t["cache_control"] = EPHEMERAL
                optimized_tools.append(t)
            result["tools"] = optimized_tools

        system_blocks: list[dict[str, Any]] = []
        if system:
            system_blocks.append(
                {
                    "type": "text",
                    "text": system,
                    "cache_control": EPHEMERAL,
                }
            )
        if rag_context:
            system_blocks.append(
                {
                    "type": "text",
                    "text": rag_context,
                    "cache_control": EPHEMERAL,
                }
            )
        if system_blocks:
            result["system"] = system_blocks

        result["messages"] = messages
        return result
