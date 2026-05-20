"""Narration event store + SSE feed for the Wingman Copilot live canvas.

Events flow:
    1. Runtime publishes per-tool events to Redis channel wingman:progress:<root>.
    2. /desk/narration/{root} subscribes to that channel + forwards to SSE clients.
    3. Same endpoint also persists every event to a JSON-lines file under
       /data/wingman-narrations/{root}.jsonl so past runs can be replayed.
    4. /desk/narration/{root}/replay reads the persisted log back as the same
       SSE shape with a configurable speed multiplier.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

NARRATION_ROOT = Path(os.environ.get("WINGMAN_NARRATION_DIR", "/data/wingman-narrations"))
REDIS_URL = os.environ.get("REDIS_URL", "")
CHANNEL_PREFIX = "wingman:progress:"


def _path(execution_id: str) -> Path:
    return NARRATION_ROOT / f"{execution_id}.jsonl"


def append(execution_id: str, event: dict[str, Any]) -> None:
    if not execution_id:
        return
    try:
        NARRATION_ROOT.mkdir(parents=True, exist_ok=True)
        with _path(execution_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        logger.debug("narration.append failed: %s", e)


def load(execution_id: str) -> list[dict[str, Any]]:
    p = _path(execution_id)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("narration.load failed for %s: %s", execution_id, e)
    return out


def has(execution_id: str) -> bool:
    return _path(execution_id).exists() and _path(execution_id).stat().st_size > 0


async def _subscribe_redis(execution_id: str) -> AsyncIterator[dict[str, Any]]:
    if not REDIS_URL:
        return
    try:
        import redis.asyncio as redis_async  # type: ignore
        client = redis_async.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.warning("narration redis connect failed: %s", e)
        return
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(f"{CHANNEL_PREFIX}{execution_id}")
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
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
            await pubsub.unsubscribe(f"{CHANNEL_PREFIX}{execution_id}")
            await pubsub.close()
            await client.close()
        except Exception:
            pass


async def sse_stream(execution_id: str) -> AsyncIterator[str]:
    """Yield SSE-formatted lines from the live Redis channel for this root execution."""
    yield f"event: start\ndata: {json.dumps({'execution_id': execution_id, 'ts': time.time()})}\n\n"
    persisted = load(execution_id)
    for evt in persisted:
        yield f"event: progress\ndata: {json.dumps(evt, default=str)}\n\n"
    last_hb = time.time()
    try:
        async for evt in _subscribe_redis(execution_id):
            if evt.get("phase") == "heartbeat":
                if time.time() - last_hb > 15:
                    yield f"event: heartbeat\ndata: {json.dumps({'ts': time.time()})}\n\n"
                    last_hb = time.time()
                continue
            append(execution_id, evt)
            yield f"event: progress\ndata: {json.dumps(evt, default=str)}\n\n"
            if evt.get("phase") == "done":
                break
    except asyncio.CancelledError:
        return


async def replay_stream(execution_id: str, speed: float = 4.0) -> AsyncIterator[str]:
    """Replay a persisted narration at `speed` x real time."""
    events = load(execution_id)
    yield f"event: start\ndata: {json.dumps({'execution_id': execution_id, 'replay': True, 'count': len(events)})}\n\n"
    if not events:
        yield "event: done\ndata: {}\n\n"
        return
    t0 = float(events[0].get("ts") or 0)
    wall_start = time.time()
    for evt in events:
        target_offset = max(0.0, (float(evt.get("ts") or t0) - t0) / max(speed, 0.5))
        wait = (wall_start + target_offset) - time.time()
        if wait > 0:
            try:
                await asyncio.sleep(min(wait, 4.0))
            except asyncio.CancelledError:
                return
        yield f"event: progress\ndata: {json.dumps(evt, default=str)}\n\n"
    yield "event: done\ndata: {}\n\n"
