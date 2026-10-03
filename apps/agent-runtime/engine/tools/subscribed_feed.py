"""Subscribed feed — read the latest cached value for a live data stream.

The actual subscription work (MQTT/Kafka/HTTP-poll) is performed by a
cron-driven background job that writes the freshest sample to Redis at
key `tenant:{tid}:feed:{feed_id}`. This tool just reads that cache —
zero direct broker traffic on the hot path.

Returns: {"feed_id", "value", "fetched_at", "age_seconds", "stale"}.
`stale` is true if the cache is older than max_age_seconds (default 60s).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class SubscribedFeedTool(BaseTool):
    name = "subscribed_feed"
    risk_tier = "low"
    description = (
        "Read the latest cached sample of a live feed (MQTT topic, Kafka "
        "stream, or HTTP poller). The feed itself is refreshed by a "
        "platform background job; this tool is the read side."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "feed_id": {
                "type": "string",
                "description": "Identifier of a registered feed.",
            },
            "max_age_seconds": {
                "type": "integer",
                "default": 60,
                "description": "Treat samples older than this as stale.",
            },
            "tenant_id": {
                "type": "string",
                "description": "Tenant scope override — runtime injects via env normally.",
            },
        },
        "required": ["feed_id"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "feed_id": {"type": "string"},
            "value": {},
            "fetched_at": {"type": "number"},
            "age_seconds": {"type": "number"},
            "stale": {"type": "boolean"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        feed_id = (arguments.get("feed_id") or "").strip()
        if not feed_id:
            return ToolResult(content="feed_id is required", is_error=True)

        max_age = int(arguments.get("max_age_seconds") or 60)
        tenant_id = (
            (arguments.get("tenant_id") or "").strip()
            or os.environ.get("TENANT_ID", "").strip()
            or "default"
        )
        key = f"tenant:{tenant_id}:feed:{feed_id}"

        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        try:
            import redis.asyncio as aioredis
        except ImportError:
            return ToolResult(content="redis client not installed", is_error=True)

        try:
            r = aioredis.from_url(url, decode_responses=True)
        except Exception as e:
            return ToolResult(content=f"redis connect failed: {e}", is_error=True)

        try:
            raw = await r.get(key)
        except Exception as e:
            return ToolResult(content=f"feed cache read failed: {e}", is_error=True)
        finally:
            try:
                await r.aclose()
            except Exception:
                pass

        if raw is None:
            return ToolResult(
                content=json.dumps(
                    {
                        "feed_id": feed_id,
                        "value": None,
                        "fetched_at": None,
                        "age_seconds": None,
                        "stale": True,
                        "status": "no_cached_sample",
                    }
                )
            )

        # Cached value should be JSON of shape {"value": ..., "fetched_at": float}.
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = {"value": raw, "fetched_at": None}

        fetched_at = obj.get("fetched_at")
        now = time.time()
        age = (now - float(fetched_at)) if fetched_at else None
        stale = (age is None) or (age > max_age)

        return ToolResult(
            content=json.dumps(
                {
                    "feed_id": feed_id,
                    "value": obj.get("value"),
                    "fetched_at": fetched_at,
                    "age_seconds": age,
                    "stale": stale,
                }
            ),
            metadata={"stale": stale, "age_seconds": age},
        )
