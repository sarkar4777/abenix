"""Dispatch tool calls to a worker pool via Redis Streams.

Used when ToolRuntimeConfig.pool == 'runtime'. Keeps the api pod's event
loop free: the api pod XADDs a job, then SUBSCRIBEs to a per-job result
channel and awaits the worker's response. The worker (in
apps/worker/tool_worker.py) does the heavy lifting.

If the worker pool is not running (dev mode), we fall back to running
inline so the platform still works without the extra deployment.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from app.core.execution_state import _get_redis

logger = logging.getLogger(__name__)

TOOL_STREAM = "tools:queue"
RESULT_CHANNEL_PREFIX = "tools:result:"
DEFAULT_TIMEOUT = 30.0


async def enqueue_and_wait(
    tool_slug: str,
    tenant_id: str,
    arguments: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout_s: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Push a job onto the tools stream and await the worker's pub/sub reply.

    Returns ``{"content", "metadata", "is_error", "error"}`` shaped exactly
    like the inline path. Raises TimeoutError on no response.
    """
    r = await _get_redis()
    if r is None:
        raise RuntimeError("redis unavailable — cannot dispatch to runtime pool")

    job_id = str(uuid.uuid4())
    result_ch = f"{RESULT_CHANNEL_PREFIX}{job_id}"

    payload = {
        "job_id": job_id,
        "tool_slug": tool_slug,
        "tenant_id": tenant_id,
        "arguments": json.dumps(arguments or {}, default=str),
        "config": json.dumps(config or {}, default=str),
        "result_channel": result_ch,
        "enqueued_at": str(time.time()),
    }

    pubsub = r.pubsub()
    await pubsub.subscribe(result_ch)

    try:
        await r.xadd(TOOL_STREAM, payload)
    except Exception as e:
        await pubsub.unsubscribe(result_ch)
        await pubsub.close()
        raise RuntimeError(f"xadd to {TOOL_STREAM} failed: {e}") from e

    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("type") == "message":
                try:
                    return json.loads(msg["data"])
                except Exception:
                    return {
                        "content": str(msg["data"]),
                        "metadata": {},
                        "is_error": False,
                    }
        raise asyncio.TimeoutError(
            f"no worker reply within {timeout_s}s for {tool_slug}"
        )
    finally:
        await pubsub.unsubscribe(result_ch)
        await pubsub.close()


async def queue_depth() -> int:
    """For the admin UI / metrics."""
    r = await _get_redis()
    if r is None:
        return -1
    try:
        return int(await r.xlen(TOOL_STREAM))
    except Exception:
        return -1
