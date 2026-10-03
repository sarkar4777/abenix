"""Windowed state — Redis-backed sliding-window store keyed per asset.

Operations:
  append          → push a (ts, payload) member onto the window
  query           → fetch members whose timestamp falls within [since, until]
  count           → number of members since a given timestamp
  pattern_match   → check whether the recent label sequence ends with
                    pattern_seq (a list of expected label strings).

Keys are namespaced as `tenant:{tid}:state:{asset_id}:{name}` so that
two tenants pointing the same Redis URL stay isolated. The tenant id is
read from TENANT_ID env when supplied (the runtime injects this for
context tools); otherwise we fall back to a `tenant_id` argument.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from engine.tools.base import BaseTool, ToolResult

_OPS = ("append", "query", "count", "pattern_match")


def _to_epoch(value: Any) -> float | None:
    """Accept ISO-8601 string OR raw epoch; return epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.replace(".", "", 1).isdigit():
        return float(s)
    try:
        # fromisoformat accepts both naive and aware ISO-8601 strings.
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


class WindowedStateTool(BaseTool):
    name = "windowed_state"
    risk_tier = "low"
    description = (
        "Per-asset sliding-window state primitive. Operations: append, query, "
        "count, pattern_match. Backed by Redis sorted-sets keyed by tenant + "
        "asset + window-name."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": list(_OPS),
                "description": "Which window operation to perform.",
            },
            "asset_id": {
                "type": "string",
                "description": "Asset/tag identifier.",
            },
            "name": {
                "type": "string",
                "description": "Window name (e.g. 'vibration', 'alarm_chain').",
            },
            "payload": {
                "description": "JSON payload (append). May include a 'label' field used by pattern_match.",
            },
            "since": {
                "type": "string",
                "description": "ISO-8601 lower bound (query/count).",
            },
            "until": {
                "type": "string",
                "description": "ISO-8601 upper bound (query). Defaults to now.",
            },
            "pattern_seq": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Expected suffix of recent labels (pattern_match).",
            },
            "max_age_seconds": {
                "type": "integer",
                "default": 86400,
                "description": "Auto-trim members older than this on append. Default 24h.",
            },
            "tenant_id": {
                "type": "string",
                "description": "Tenant scope override — runtime injects via env normally.",
            },
        },
        "required": ["operation", "asset_id", "name"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "ok": {"type": "boolean"},
            "items": {"type": "array"},
            "count": {"type": "integer"},
            "matched": {"type": "boolean"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = (arguments.get("operation") or "").strip()
        if op not in _OPS:
            return ToolResult(content=f"operation must be one of {_OPS}", is_error=True)
        asset_id = (arguments.get("asset_id") or "").strip()
        name = (arguments.get("name") or "").strip()
        if not asset_id or not name:
            return ToolResult(content="asset_id and name are required", is_error=True)

        tenant_id = (
            (arguments.get("tenant_id") or "").strip()
            or os.environ.get("TENANT_ID", "").strip()
            or "default"
        )
        key = f"tenant:{tenant_id}:state:{asset_id}:{name}"

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
            if op == "append":
                payload = arguments.get("payload")
                if payload is None:
                    payload = {}
                if not isinstance(payload, (dict, list, str, int, float, bool)):
                    payload = str(payload)
                ts = float(
                    payload.get("ts")
                    if isinstance(payload, dict) and payload.get("ts")
                    else time.time()
                )
                # Score = ts; member is the JSON payload (with ts inlined so
                # readers don't have to look it up separately).
                if isinstance(payload, dict):
                    payload = {**payload, "ts": ts}
                member = json.dumps(payload, default=str)
                await r.zadd(key, {member: ts})

                max_age = int(arguments.get("max_age_seconds") or 86400)
                cutoff = ts - max_age
                await r.zremrangebyscore(key, "-inf", cutoff)

                return ToolResult(
                    content=json.dumps({"operation": "append", "ok": True, "ts": ts}),
                    metadata={"key": key, "ts": ts},
                )

            if op == "query":
                since = _to_epoch(arguments.get("since")) or 0
                until = _to_epoch(arguments.get("until")) or time.time()
                raw = await r.zrangebyscore(key, since, until)
                items: list[Any] = []
                for m in raw:
                    try:
                        items.append(json.loads(m))
                    except json.JSONDecodeError:
                        items.append({"raw": m})
                return ToolResult(
                    content=json.dumps(
                        {"operation": "query", "items": items, "count": len(items)}
                    ),
                    metadata={"count": len(items)},
                )

            if op == "count":
                since = _to_epoch(arguments.get("since")) or 0
                until = _to_epoch(arguments.get("until")) or time.time()
                count = await r.zcount(key, since, until)
                return ToolResult(
                    content=json.dumps({"operation": "count", "count": int(count)}),
                    metadata={"count": int(count)},
                )

            # pattern_match: read the most-recent N labels, compare suffix
            # to pattern_seq. Useful for cascade detection (warning →
            # warning → alarm).
            pattern_seq = arguments.get("pattern_seq") or []
            if not isinstance(pattern_seq, list) or not pattern_seq:
                return ToolResult(
                    content="pattern_seq must be a non-empty list",
                    is_error=True,
                )
            recent = await r.zrange(key, -len(pattern_seq), -1)
            recent_labels: list[str] = []
            for m in recent:
                try:
                    obj = json.loads(m)
                    label = obj.get("label") if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    label = None
                recent_labels.append(str(label) if label is not None else "")
            matched = recent_labels == [str(x) for x in pattern_seq]
            return ToolResult(
                content=json.dumps(
                    {
                        "operation": "pattern_match",
                        "matched": matched,
                        "recent": recent_labels,
                        "expected": pattern_seq,
                    }
                ),
                metadata={"matched": matched},
            )
        finally:
            try:
                await r.aclose()
            except Exception:
                pass
