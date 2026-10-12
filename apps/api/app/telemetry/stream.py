"""Live telemetry for viewers: one Redis subscriber per API process, fanned out to SSE queues.

The ingest publishes per node on tel:{tenant}:pub:{group}:{node}. A viewer that
names its nodes rides exact channel subscriptions, one that wants the whole
workspace rides a pattern. Either way a message is decoded once per process and
handed to each matching viewer, so a viewer costs the same at 2 or 200.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.telemetry import keys as K

logger = logging.getLogger(__name__)

QUEUE_MAX = 2000
THROTTLE_S = 0.1


@dataclass(eq=False)
class Viewer:
    tenant: str
    scope: Any
    nodes: set[tuple[str, str]] | None = None
    device: str | None = None
    group: str | None = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(QUEUE_MAX))
    dropped: int = 0

    def channels(self) -> list[str]:
        return [K.channel(self.tenant, g, n) for g, n in sorted(self.nodes or ())]

    def wants(self, doc: dict[str, Any]) -> bool:
        if self.group is not None and doc.get("group") != self.group:
            return False
        if (
            self.nodes is not None
            and (doc.get("group"), doc.get("node")) not in self.nodes
        ):
            return False
        if self.device is not None and doc.get("device", "") != self.device:
            return False
        return self.scope.sees(doc.get("connection_id"))

    def offer(self, kind: str, doc: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait((kind, doc))
        except asyncio.QueueFull:
            # a slow reader loses the oldest updates, never the newest
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.dropped += 1
            try:
                self.queue.put_nowait((kind, doc))
            except asyncio.QueueFull:
                pass


class Hub:
    def __init__(self) -> None:
        self.by_channel: dict[str, set[Viewer]] = defaultdict(set)
        self.by_pattern: dict[str, set[Viewer]] = defaultdict(set)
        self.ps: Any = None
        self.redis: Any = None
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.delivered = 0

    async def _ensure(self) -> None:
        if self.ps is None:
            import redis.asyncio as aioredis

            from app.core.config import settings

            self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            self.ps = self.redis.pubsub()
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._read())

    async def add(self, v: Viewer) -> None:
        async with self.lock:
            await self._ensure()
            if v.nodes is None:
                pat = K.tenant_channels(v.tenant)
                if not self.by_pattern[pat]:
                    await self.ps.psubscribe(pat)
                self.by_pattern[pat].add(v)
            else:
                for ch in v.channels():
                    if not self.by_channel[ch]:
                        await self.ps.subscribe(ch)
                    self.by_channel[ch].add(v)

    async def remove(self, v: Viewer) -> None:
        async with self.lock:
            if v.nodes is None:
                pat = K.tenant_channels(v.tenant)
                self.by_pattern[pat].discard(v)
                if not self.by_pattern[pat]:
                    self.by_pattern.pop(pat, None)
                    if self.ps is not None:
                        await self.ps.punsubscribe(pat)
            else:
                for ch in v.channels():
                    self.by_channel[ch].discard(v)
                    if not self.by_channel[ch]:
                        self.by_channel.pop(ch, None)
                        if self.ps is not None:
                            await self.ps.unsubscribe(ch)

    def dispatch(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "pmessage":
            viewers = self.by_pattern.get(msg.get("pattern") or "", ())
        elif kind == "message":
            viewers = self.by_channel.get(msg.get("channel") or "", ())
        else:
            return
        if not viewers:
            return
        try:
            doc = json.loads(msg.get("data") or "{}")
        except (TypeError, ValueError):
            return
        ev = doc.pop("type", "metrics")
        for v in list(viewers):
            if v.wants(doc):
                v.offer(ev, doc)
                self.delivered += 1

    async def _read(self) -> None:
        while True:
            try:
                if not (self.by_channel or self.by_pattern):
                    await asyncio.sleep(0.5)
                    continue
                msg = await self.ps.get_message(timeout=1.0)
                if msg:
                    self.dispatch(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("telemetry stream reader restarting: %s", exc)
                await asyncio.sleep(1)
                await self._resubscribe()

    async def _resubscribe(self) -> None:
        async with self.lock:
            try:
                if self.ps is not None:
                    await self.ps.aclose()
            except Exception:  # noqa: BLE001
                pass
            self.ps = self.redis.pubsub()
            for pat in self.by_pattern:
                await self.ps.psubscribe(pat)
            for ch in self.by_channel:
                await self.ps.subscribe(ch)


hub = Hub()


class Coalescer:
    """Holds metric updates per device and lets them out at most ten times a second."""

    def __init__(self, every: float = THROTTLE_S) -> None:
        self.every = every
        self.pending: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.sent_at: dict[tuple[str, str, str], float] = {}

    def add(self, doc: dict[str, Any]) -> None:
        key = (doc.get("group", ""), doc.get("node", ""), doc.get("device", ""))
        cur = self.pending.get(key)
        if cur is None:
            self.pending[key] = {
                **doc,
                "metrics": {m["name"]: m for m in doc.get("metrics") or []},
            }
            return
        for m in doc.get("metrics") or []:
            cur["metrics"][m["name"]] = m

    def due(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.monotonic() if now is None else now
        out = []
        for key in list(self.pending):
            if now - self.sent_at.get(key, 0.0) < self.every:
                continue
            doc = self.pending.pop(key)
            doc["metrics"] = sorted(doc["metrics"].values(), key=lambda m: m["name"])
            self.sent_at[key] = now
            out.append(doc)
        return out


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


def parse_nodes(
    raw: str | None, group: str | None, node: str | None
) -> set[tuple[str, str]] | None:
    """?nodes=grp/node,grp/node or ?group=&node=. None means every node in view."""
    out: set[tuple[str, str]] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "/" not in part:
            raise ValueError("nodes must look like group/node, separated by commas")
        g, n = part.split("/", 1)
        out.add((g.strip(), n.strip()))
    if group and node:
        out.add((group, node))
    if len(out) > 200:
        raise ValueError("At most 200 nodes in one live view")
    return out or None
