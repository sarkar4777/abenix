from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

TTL_SECONDS = 86400  # 24 hours
TEMP_THRESHOLD = 0.5


def _cache_key(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    temperature: float,
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"abenix:exact:{digest}"


class ExactCache:
    def __init__(self, redis_url: str | None = None) -> None:
        url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def get(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
    ) -> dict[str, Any] | None:
        if temperature > TEMP_THRESHOLD:
            return None

        key = _cache_key(model, messages, tools, temperature)
        raw = await self._redis.get(key)
        if raw is None:
            return None

        logger.debug("exact cache hit key=%s", key[:24])
        return json.loads(raw)

    async def set(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        response: dict[str, Any],
    ) -> None:
        if temperature > TEMP_THRESHOLD:
            return

        key = _cache_key(model, messages, tools, temperature)
        await self._redis.set(key, json.dumps(response, default=str), ex=TTL_SECONDS)

    async def close(self) -> None:
        await self._redis.aclose()
