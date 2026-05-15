"""Pub/sub progress events for the Desk Copilot narration stream.

Every runtime worker publishes tool-level progress events to Redis on channel
`wingman:progress:<root_execution_id>`. Sub-agents inherit the root id from
the parent's call (set by invoke_agent before kicking off the sub-execution
and looked up here when the runtime starts processing a task).

If REDIS_URL is unset or unreachable, all helpers degrade to no-ops — the
runtime keeps working, the Desk page just shows the platform-level events
without the rich narration overlay.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "")
CHANNEL_PREFIX = "wingman:progress:"
PARENT_KEY_PREFIX = "wingman:parent:"
PARENT_TTL_SECONDS = int(os.environ.get("WINGMAN_PARENT_TTL", "1800"))

_client_singleton: Any | None = None
_client_lock = asyncio.Lock()


async def _client() -> Any | None:
    global _client_singleton
    if not REDIS_URL:
        return None
    if _client_singleton is not None:
        return _client_singleton
    async with _client_lock:
        if _client_singleton is not None:
            return _client_singleton
        try:
            import redis.asyncio as redis_async  # type: ignore
            client = redis_async.from_url(REDIS_URL, decode_responses=True)
            await client.ping()
            _client_singleton = client
            return client
        except Exception as e:
            logger.warning("progress: redis connect failed: %s", e)
            return None


def channel_for(root_execution_id: str) -> str:
    return f"{CHANNEL_PREFIX}{root_execution_id}"


async def set_parent(child_execution_id: str, root_execution_id: str) -> None:
    """Register child -> root mapping so child's runtime publishes to the same channel."""
    if not child_execution_id or not root_execution_id:
        return
    c = await _client()
    if c is None:
        return
    try:
        await c.set(f"{PARENT_KEY_PREFIX}{child_execution_id}", root_execution_id, ex=PARENT_TTL_SECONDS)
    except Exception as e:
        logger.debug("progress.set_parent failed: %s", e)


async def root_for(execution_id: str) -> str:
    """Look up the root execution id for this run; default to self when not mapped."""
    if not execution_id:
        return execution_id
    c = await _client()
    if c is None:
        return execution_id
    try:
        v = await c.get(f"{PARENT_KEY_PREFIX}{execution_id}")
        if v:
            return v
    except Exception:
        pass
    return execution_id


async def publish(
    execution_id: str,
    event: dict[str, Any],
    *,
    root_execution_id: str | None = None,
) -> None:
    """Publish a narration event to the root channel."""
    if not execution_id:
        return
    c = await _client()
    if c is None:
        return
    root = root_execution_id or await root_for(execution_id)
    event = {
        "ts": time.time(),
        "execution_id": execution_id,
        "root_execution_id": root,
        **event,
    }
    try:
        await c.publish(channel_for(root), json.dumps(event, default=str))
    except Exception as e:
        logger.debug("progress.publish failed: %s", e)


async def subscribe(root_execution_id: str) -> AsyncIterator[dict[str, Any]]:
    """Yield events published to this root's channel until the caller cancels."""
    c = await _client()
    if c is None:
        return
    pubsub = c.pubsub()
    try:
        await pubsub.subscribe(channel_for(root_execution_id))
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
            if msg is None:
                yield {"phase": "heartbeat", "ts": time.time()}
                continue
            data = msg.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except Exception:
                continue
    finally:
        try:
            await pubsub.unsubscribe(channel_for(root_execution_id))
            await pubsub.close()
        except Exception:
            pass
