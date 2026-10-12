"""What every collector shares: its asset, its status in plain words, and how readings leave it."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from typing import Any, Callable

from abenix_edge.buffer import Reading, now_ms

LOG = logging.getLogger("abenix-edge")
_SAFE = re.compile(r"[^A-Za-z0-9_\-]+")


def slug(s: Any, default: str = "x") -> str:
    out = _SAFE.sub("-", str(s or "").strip()).strip("-")
    return out[:64] or default


class Collector:
    """One configured source on the gateway. Subclasses implement run()."""

    type = ""
    label = ""

    def __init__(
        self,
        spec: dict[str, Any],
        sink: Callable[[list[Reading]], None],
        gateway_id: str,
    ) -> None:
        self.spec = spec
        self.id = str(spec.get("id") or slug(spec.get("name"), self.type))
        self.name = str(spec.get("name") or self.id)
        self._sink = sink
        asset = spec.get("asset") or {}
        self.group = slug(asset.get("group"), "edge")
        self.node = slug(asset.get("node"), slug(gateway_id, "gateway"))
        self.device = (
            slug(asset.get("device"), "")
            if asset.get("device")
            else slug(self.name, self.type)
        )
        self.interval = max(0.1, float(spec.get("interval_s") or 1.0))
        self.status = "starting"
        self.error: str | None = None
        self.readings = 0
        self.last_reading_at: int | None = None
        self.started_at = time.time()
        self.extra: dict[str, Any] = {}
        self._rate: list[tuple[float, int]] = []
        self._latest: dict[tuple[str, str], tuple[Any, int, str | None, str]] = {}
        self._latest_lock = threading.Lock()

    def subject(self, device: str | None = None) -> str:
        d = self.device if device is None else device
        return f"{self.group}/{self.node}/{d}" if d else f"{self.group}/{self.node}"

    def ok(self) -> None:
        if self.status != "running" or self.error:
            LOG.info("collector_running id=%s type=%s", self.id, self.type)
        self.status, self.error = "running", None

    def fail(self, plain: str, status: str = "error") -> None:
        if plain != self.error:
            LOG.warning("collector_problem id=%s type=%s %s", self.id, self.type, plain)
        self.status, self.error = status, plain

    def emit(
        self,
        name: str,
        value: Any,
        *,
        device: str | None = None,
        ts: int | None = None,
        unit: str | None = None,
        quality: str = "good",
    ) -> None:
        self.emit_many([(name, value, unit, quality)], device=device, ts=ts)

    def emit_many(
        self,
        rows: list[tuple[str, Any, str | None, str]],
        *,
        device: str | None = None,
        ts: int | None = None,
    ) -> None:
        t = ts or now_ms()
        subject = self.subject(device)
        out = [Reading(subject, n, v, t, u, q) for n, v, u, q in rows if v is not None]
        if not out:
            return
        self._sink(out)
        self.readings += len(out)
        self.last_reading_at = t

    # high-rate sources keep the newest value per signal and send it every interval

    def update(
        self,
        device: str,
        name: str,
        value: Any,
        unit: str | None = None,
        quality: str = "good",
    ) -> None:
        with self._latest_lock:
            self._latest[(device, name)] = (value, now_ms(), unit, quality)

    def publish_latest(self) -> int:
        with self._latest_lock:
            latest, self._latest = self._latest, {}
        by_dev: dict[str, list[Reading]] = {}
        for (device, name), (v, ts, unit, q) in latest.items():
            by_dev.setdefault(device, []).append(
                Reading(self.subject(device), name, v, ts, unit, q)
            )
        n = 0
        for rows in by_dev.values():
            self._sink(rows)
            n += len(rows)
        if n:
            self.readings += n
            self.last_reading_at = now_ms()
        return n

    async def publisher(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self.publish_latest()

    def rate(self) -> float:
        now = time.time()
        self._rate.append((now, self.readings))
        self._rate = [x for x in self._rate if now - x[0] <= 60]
        t0, n0 = self._rate[0]
        return round((self.readings - n0) / (now - t0), 2) if now - t0 > 1 else 0.0

    def health(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "status": self.status,
            "error": self.error,
            "readings": self.readings,
            "readings_per_s": self.rate(),
            "last_reading_at": self.last_reading_at,
            "subject": self.subject(),
            **self.extra,
        }

    async def run(self, stop: asyncio.Event) -> None:
        raise NotImplementedError


async def retry_sleep(stop: asyncio.Event, attempt: int, cap: float = 30.0) -> None:
    import random

    delay = random.uniform(0.5, min(cap, 2 ** min(attempt, 5)))
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except asyncio.TimeoutError:
        pass
