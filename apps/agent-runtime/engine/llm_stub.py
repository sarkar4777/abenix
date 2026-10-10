"""Canned model replies so CI browser tests run without a provider key."""

from __future__ import annotations

import os
from typing import Any, AsyncGenerator

STUB_MODEL_PREFIX = "Stub reply: "


def enabled() -> bool:
    # both flags, so a stray env var on a real deployment cannot turn it on
    return os.environ.get("ABENIX_LLM_STUB") == "1" and os.environ.get("CI") == "true"


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            if parts:
                return " ".join(parts)
    return ""


def reply_for(messages: list[dict[str, Any]]) -> str:
    said = " ".join(_last_user_text(messages).split())[:200]
    return f"{STUB_MODEL_PREFIX}{said}" if said else STUB_MODEL_PREFIX.strip()


async def stream_reply(text: str, model: str) -> AsyncGenerator[Any, None]:
    from engine.llm_router import StreamEvent

    words = text.split(" ")
    for i, w in enumerate(words):
        yield StreamEvent(event="token", data=w if i == 0 else f" {w}")
    yield StreamEvent(
        event="done",
        data={
            "model": model,
            "input_tokens": 0,
            "output_tokens": len(words),
            "cost": 0.0,
            "latency_ms": 0,
            "tool_calls": [],
        },
    )
