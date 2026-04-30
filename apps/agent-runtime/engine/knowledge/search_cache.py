"""Redis-backed query result cache for KB hybrid search."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Module-level connection. Lazily initialised; one client per worker
# process is plenty since redis-py is connection-pooled internally.
_redis_client: Any | None = None
_redis_unavailable = False


def _get_client() -> Any | None:
    """Lazy-init the redis client. Returns None on any failure."""
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        import redis.asyncio as aioredis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = aioredis.from_url(
            url, encoding="utf-8", decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
        return _redis_client
    except Exception as e:
        logger.warning("Search cache: redis unavailable, disabling: %s", e)
        _redis_unavailable = True
        return None


def cache_key(
    *,
    tenant_id: str,
    kb_ids: list[str],
    query: str,
    mode: str,
    top_k: int,
) -> str:
    """Stable cache key — sorts kb_ids so order doesn't matter."""
    payload = json.dumps({
        "t": tenant_id,
        "k": sorted(kb_ids),
        "q": query.strip().lower(),
        "m": mode,
        "n": top_k,
    }, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"kbsearch:{digest}"


async def get(key: str) -> dict | None:
    """Return cached search response dict, or None on miss/failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def set(key: str, value: dict, ttl_seconds: int = 300) -> None:
    """Store a search response dict. Failures are silent — caller
    has already returned the result; cache is best-effort."""
    client = _get_client()
    if client is None:
        return
    try:
        await client.setex(key, ttl_seconds, json.dumps(value))
    except Exception:
        pass


async def invalidate_tenant(tenant_id: str) -> None:
    """Drop every cached entry for a tenant."""
    client = _get_client()
    if client is None:
        return
    try:
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match="kbsearch:*", count=200)
            if keys:
                await client.delete(*keys)
                deleted += len(keys)
            if cursor == 0:
                break
        if deleted:
            logger.info("Search cache: invalidated %d entries (tenant=%s)", deleted, tenant_id)
    except Exception:
        pass
