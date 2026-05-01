"""WebSocket fan-out across API pods."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_FANOUT_CHANNEL = "ws:fanout"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._redis: Any = None
        self._subscriber_task: asyncio.Task | None = None
        self._started = False

    async def start(self) -> None:
        """Subscribe to the fan-out channel. Safe to call many times."""
        if self._started:
            return
        self._started = True
        url = (os.environ.get("REDIS_URL") or "").strip()
        if not url:
            logger.info("ws_manager: REDIS_URL not set, running in single-pod mode")
            return
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning("ws_manager: redis.asyncio not importable, single-pod mode")
            return
        try:
            self._redis = aioredis.from_url(url, decode_responses=True)
            self._subscriber_task = asyncio.create_task(self._run_subscriber())
            logger.info("ws_manager: subscribed to Redis channel '%s'", _FANOUT_CHANNEL)
        except Exception as e:
            logger.warning(
                "ws_manager: Redis subscribe failed (%s), single-pod mode", e
            )
            self._redis = None

    async def stop(self) -> None:
        if self._subscriber_task and not self._subscriber_task.done():
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def _run_subscriber(self) -> None:
        """Long-running task: receive publishes, deliver to local sockets."""
        while True:
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(_FANOUT_CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    raw = msg.get("data")
                    if not raw:
                        continue
                    try:
                        env = json.loads(raw)
                    except Exception:
                        continue
                    await self._deliver_local(
                        env.get("user_id", ""),
                        env.get("event", ""),
                        env.get("data", {}),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("ws_manager subscriber restarting after error: %s", e)
                await asyncio.sleep(1.0)

    async def _deliver_local(self, user_id: str, event: str, data: dict) -> None:
        """Write to the in-memory sockets on THIS pod (only)."""
        payload = json.dumps({"event": event, "data": data})
        stale: list[WebSocket] = []
        for ws in list(self._connections.get(user_id, [])):
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections[user_id] = [
                c for c in self._connections[user_id] if c is not ws
            ]
            if not self._connections[user_id]:
                self._connections.pop(user_id, None)

    async def connect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[str(user_id)].append(ws)

    def disconnect(self, user_id: uuid.UUID, ws: WebSocket) -> None:
        key = str(user_id)
        if key in self._connections:
            self._connections[key] = [c for c in self._connections[key] if c is not ws]
            if not self._connections[key]:
                del self._connections[key]

    async def send_to_user(self, user_id: uuid.UUID, event: str, data: dict) -> None:
        """Publish to fan-out if Redis is available; otherwise deliver
        to local sockets directly (single-pod mode)."""
        key = str(user_id)
        if self._redis is not None:
            try:
                await self._redis.publish(
                    _FANOUT_CHANNEL,
                    json.dumps({"user_id": key, "event": event, "data": data}),
                )
                return
            except Exception as e:
                logger.warning("ws_manager publish failed, falling back local: %s", e)
        await self._deliver_local(key, event, data)

    async def broadcast_to_tenant(
        self, tenant_user_ids: list[uuid.UUID], event: str, data: dict
    ) -> None:
        for uid in tenant_user_ids:
            await self.send_to_user(uid, event, data)

    @property
    def active_connections_count(self) -> int:
        return sum(len(v) for v in self._connections.values())


ws_manager = ConnectionManager()
