"""API-side proxy for the agent-runtime search cache."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


_redis_client: Any | None = None


async def _get_client() -> Any | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        return _redis_client
    except Exception:
        return None


async def invalidate_tenant_search_cache(tenant_id: str) -> int:
    """Drop kbsearch:* entries; returns count for logging."""
    client = await _get_client()
    if client is None:
        return 0
    deleted = 0
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(
                cursor=cursor,
                match="kbsearch:*",
                count=200,
            )
            if keys:
                await client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.debug("Cache invalidate failed (non-fatal): %s", e)
    return deleted
