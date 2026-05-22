"""Tool stream consumer — runs in every agent-runtime pod as a background task.

Subscribes to the ``tools:queue`` Redis stream that the api pod XADDs to
when ``ToolRuntimeConfig.pool == 'runtime'``. Pulls jobs, instantiates
the tool from ``_TOOL_CLASSES``, runs it, publishes the result on the
per-job result channel that the api pod is waiting on.

This co-loops inside the agent-runtime pod so the pod's KEDA scaler
(which already scales on agent queue depth) gives us tool worker
capacity proportional to agent capacity — no separate deployment.
Tool-only scaling can later be split into its own deployment by
flipping ``TOOL_WORKER_ENABLED=0`` here and standing up a new one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("agent-runtime.tool_consumer")

TOOL_STREAM = "tools:queue"
TOOL_CONSUMER_GROUP = "tool-workers"
TOOL_CONSUMER_NAME = os.environ.get("HOSTNAME") or f"tool-worker-{os.getpid()}"
RESULT_CHANNEL_PREFIX = "tools:result:"
MAX_INFLIGHT = int(os.environ.get("TOOL_WORKER_CONCURRENCY", "10"))


async def _get_redis():
    import redis.asyncio as aioredis

    url = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    return aioredis.from_url(url, decode_responses=True)


async def _ensure_group(r) -> None:
    try:
        await r.xgroup_create(TOOL_STREAM, TOOL_CONSUMER_GROUP, id="$", mkstream=True)
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            logger.debug("group create: %s", e)


async def _run_one(r, job: dict[str, Any]) -> None:
    started = time.time()
    job_id = job.get("job_id")
    tool_slug = job.get("tool_slug")
    tenant_id = job.get("tenant_id") or ""
    result_channel = job.get("result_channel") or f"{RESULT_CHANNEL_PREFIX}{job_id}"

    try:
        arguments = json.loads(job.get("arguments") or "{}")
    except Exception:
        arguments = {}
    try:
        config = json.loads(job.get("config") or "{}")
    except Exception:
        config = {}

    payload: dict[str, Any]
    try:
        from engine.agent_executor import get_tool_class

        cls = get_tool_class(tool_slug)
        if cls is None:
            payload = {
                "content": f"unknown tool: {tool_slug}",
                "metadata": {},
                "is_error": True,
            }
        else:
            try:
                tool = cls(
                    tenant_id=tenant_id,
                    execution_id="",
                    api_key="",
                    api_base="",
                    **config,
                )
            except TypeError:
                tool = cls()
            result = await tool.execute(arguments)
            payload = {
                "content": getattr(result, "content", None),
                "metadata": getattr(result, "metadata", None),
                "is_error": getattr(result, "is_error", False),
                "duration_ms": int((time.time() - started) * 1000),
                "worker": TOOL_CONSUMER_NAME,
            }
    except Exception as e:
        payload = {
            "content": f"tool worker error: {e}",
            "metadata": {},
            "is_error": True,
            "duration_ms": int((time.time() - started) * 1000),
        }

    try:
        await r.publish(result_channel, json.dumps(payload, default=str))
    except Exception as e:
        logger.warning("publish reply failed for job %s: %s", job_id, e)


async def consumer_loop() -> None:
    """Long-running coroutine. Started in server.py lifespan."""
    if os.environ.get("TOOL_WORKER_ENABLED", "1") != "1":
        logger.info("tool_consumer: disabled by env (TOOL_WORKER_ENABLED=0)")
        return

    try:
        r = await _get_redis()
    except Exception as e:
        logger.warning("tool_consumer: redis unavailable, not starting: %s", e)
        return

    await _ensure_group(r)
    logger.info(
        "tool_consumer: started group=%s consumer=%s",
        TOOL_CONSUMER_GROUP,
        TOOL_CONSUMER_NAME,
    )
    sem = asyncio.Semaphore(MAX_INFLIGHT)

    async def _handle(msg_id: str, fields: dict[str, Any]) -> None:
        async with sem:
            try:
                await _run_one(r, fields)
            finally:
                try:
                    await r.xack(TOOL_STREAM, TOOL_CONSUMER_GROUP, msg_id)
                except Exception:
                    pass

    while True:
        try:
            resp = await r.xreadgroup(
                TOOL_CONSUMER_GROUP,
                TOOL_CONSUMER_NAME,
                {TOOL_STREAM: ">"},
                count=10,
                block=2000,
            )
            if not resp:
                continue
            for _stream, entries in resp:
                for msg_id, fields in entries:
                    asyncio.create_task(_handle(msg_id, fields))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("tool_consumer loop error (sleeping 1s): %s", e)
            await asyncio.sleep(1)
