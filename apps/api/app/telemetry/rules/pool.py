"""The rules pool: python -m app.telemetry.rules.pool

When a workspace's rules run in the pool, the ingest only matches each record
against the workspace's signal index and appends the matching samples to one
Redis stream per shard. A shard is a slice of tenants. Each pool replica holds
the shards rendezvous hashing gives it, through a Redis lease, reads their
streams and runs the same Engine as the ingest would, so the firings, the
runner and the UI are the same in both modes.

Rule state lives in Redis and moves by compare-and-set, so a shard that changes
hands carries on exactly where it was. An entry is deleted once its samples are
evaluated and their firings published. A replica that dies mid-batch leaves the
entry, the next owner reads it again, and the state and the firing guard make
the repeat a no-op.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import socket
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.telemetry.rules.evaluator import (
    DRAIN_MAX,
    HEALTH_KEY,
    POOL_REPLICAS,
    SHARDS,
    VERSION_KEY,
    Engine,
    RedisGuard,
    RedisShared,
    _pct,
    fill_coords,
    in_stream,
    load_rows,
    publish_fired,
    read_ages,
    shard_of,
    unpack,
)

logger = logging.getLogger("telemetry.rules.pool")

LEASE_MS = 6000
BEAT_S = 2.0
READ_COUNT = 200
PORT = int(os.environ.get("TELEMETRY_RULES_PORT", "8091"))

RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""
RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def _txt(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v or "")


def _before(entry_id: str) -> str:
    """The stream id just before this one, so XREAD returns it again."""
    ms, seq = entry_id.split("-")
    if int(seq) > 0:
        return f"{ms}-{int(seq) - 1}"
    return f"{int(ms) - 1}-18446744073709551615" if int(ms) > 0 else "0-0"


def lease_key(shard: int) -> str:
    return f"tel:rules:pool:lease:{shard}"


def owner_of(shard: int, replicas: list[str]) -> str | None:
    """Rendezvous hashing: each shard goes to the replica with the highest score."""
    best, who = -1, None
    for rep in replicas:
        score = int(hashlib.sha1(f"{rep}:{shard}".encode()).hexdigest()[:12], 16)
        if score > best:
            best, who = score, rep
    return who


class Pool:
    def __init__(self) -> None:
        self.replica = f"{socket.gethostname()}-{os.getpid()}"
        self.r = aioredis.from_url(settings.redis_url, decode_responses=True)
        # the hand-off entries are binary
        self.rb = aioredis.from_url(settings.redis_url, decode_responses=False)
        self.newer = 0
        self.engine = Engine(RedisShared(self.r), RedisGuard(self.r), self._emit)
        # the pool is the pool, its own workspaces always count as pool mode here
        self.engine.pool_alive = True
        self.renew = self.r.register_script(RENEW_LUA)
        self.release = self.r.register_script(RELEASE_LUA)
        self.owned: set[int] = set()
        self.cursor: dict[int, str] = {}
        self.rules: dict[str, Any] = {}
        self.events: list[tuple[str, str, dict]] = []
        self.version: str | None = None
        self.loaded_at = 0.0
        self.stop_event = asyncio.Event()
        self.session: Any = None
        self.last_beat = 0.0
        self.batch_ms: list[float] = []
        self.samples = 0
        self.busy_ns = 0

    async def setup(self) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=2, max_overflow=2
        )
        self.session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await self.reload()

    async def reload(self) -> None:
        rows, assets, default, overrides = await load_rows(self.session)
        self.engine.load(rows, assets)
        self.engine.default_mode = default
        self.engine.modes = overrides
        self.rules = self.engine.by_id()
        self.loaded_at = time.monotonic()

    def mine(self, tenant: str) -> bool:
        return shard_of(tenant) in self.owned and self.engine.mode(tenant) == "pool"

    # membership and leases

    async def alive(self) -> list[str]:
        now = int(time.time() * 1000)
        return sorted(await self.r.zrangebyscore(POOL_REPLICAS, now - LEASE_MS, "+inf"))

    async def beat(self) -> None:
        now = int(time.time() * 1000)
        await self.r.zadd(POOL_REPLICAS, {self.replica: now})
        await self.r.zremrangebyscore(POOL_REPLICAS, 0, now - 60_000)
        reps = await self.alive()
        if self.replica not in reps:
            reps.append(self.replica)
        want = {s for s in range(SHARDS) if owner_of(s, reps) == self.replica}
        for s in sorted(self.owned - want):
            await self.release(keys=[lease_key(s)], args=[self.replica])
            self.owned.discard(s)
            logger.info("shard %s handed over", s)
        for s in sorted(want):
            if s in self.owned:
                if not await self.renew(
                    keys=[lease_key(s)], args=[self.replica, LEASE_MS]
                ):
                    self.owned.discard(s)
                continue
            if await self.r.set(lease_key(s), self.replica, nx=True, px=LEASE_MS):
                # unread entries are exactly the ones nobody finished, start at the top
                self.cursor[s] = "0-0"
                self.owned.add(s)
                logger.info("shard %s taken", s)
        self.last_beat = time.time()

    async def membership(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.beat()
            except Exception as exc:  # noqa: BLE001
                logger.warning("pool heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=BEAT_S)
            except asyncio.TimeoutError:
                pass

    # the work

    async def read(self) -> None:
        while not self.stop_event.is_set():
            owned = sorted(self.owned)
            if not owned:
                await asyncio.sleep(0.5)
                continue
            try:
                resp = await self.rb.xread(
                    {in_stream(s): self.cursor.get(s, "0-0") for s in owned},
                    count=READ_COUNT,
                    block=500,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("pool read failed: %s", exc)
                await asyncio.sleep(1)
                continue
            for key, entries in resp or []:
                shard = int(_txt(key).rsplit(":", 1)[1])
                if shard not in self.owned or not entries:
                    continue
                try:
                    await self.handle(shard, entries)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("pool batch on shard %s failed: %s", shard, exc)
                    await asyncio.sleep(1)

    async def handle(
        self, shard: int, entries: list[tuple[Any, dict[Any, Any]]]
    ) -> None:
        t0 = time.perf_counter_ns()
        items = []
        done: list[str] = []
        for mid, fields in entries:
            mid = _txt(mid)
            tenant = _txt(fields.get(b"t", fields.get("t")))
            if self.engine.mode(tenant) != "pool":
                done.append(mid)
                continue
            try:
                items.extend(unpack(fields, self.rules))
            except ValueError as exc:
                # written by a newer replica, left in the stream for one that reads it
                self.newer += 1
                if self.newer <= 5:
                    logger.warning("skipping entry %s: %s", mid, exc)
                continue
            done.append(mid)
        self.cursor[shard] = _txt(entries[-1][0])
        n = len(items)
        try:
            await fill_coords(self.r, items)
            for i in range(0, len(items), DRAIN_MAX):
                await self.engine.process(items[i : i + DRAIN_MAX])
                await asyncio.sleep(0)
        except Exception as exc:  # noqa: BLE001
            # the entries stay, read again from where they start
            self.cursor[shard] = _before(_txt(entries[0][0]))
            logger.warning("pool evaluation failed on shard %s: %s", shard, exc)
            await asyncio.sleep(1)
            return
        if done:
            await self.r.xdel(in_stream(shard), *done)
        if n:
            self.samples += n
            self.busy_ns += time.perf_counter_ns() - t0
            self.batch_ms.append((time.perf_counter_ns() - t0) / 1e6)
            if len(self.batch_ms) > 5000:
                del self.batch_ms[:2500]

    async def _emit(self, docs: list[dict[str, Any]]) -> None:
        self.events.extend(await publish_fired(self.r, docs))

    async def events_writer(self) -> None:
        from app.services import events as E

        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            if not self.events:
                continue
            batch, self.events = self.events[:5000], self.events[5000:]
            try:
                async with self.session() as db:
                    for t, kind, payload in batch:
                        await E.emit(db, t, kind, payload)
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("rule event write failed: %s", exc)

    async def sweeper(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            try:
                if any(
                    ti.stale and self.mine(t) for t, ti in self.engine.index.items()
                ):
                    await self.engine.sweep(
                        lambda asks: read_ages(self.r, asks), only=self.mine
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("pool stale sweep failed: %s", exc)

    async def loader(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            try:
                v = await self.r.get(VERSION_KEY)
                if v != self.version or time.monotonic() - self.loaded_at > 60:
                    await self.reload()
                    self.version = v
            except Exception as exc:  # noqa: BLE001
                logger.warning("pool rule reload failed: %s", exc)
                await asyncio.sleep(5)

    # health and scaling

    async def lag(self, shards: list[int]) -> int:
        if not shards:
            return 0
        pipe = self.r.pipeline(transaction=False)
        for s in shards:
            pipe.xlen(in_stream(s))
        return int(sum(int(x or 0) for x in await pipe.execute()))

    async def health_doc(self) -> dict[str, Any]:
        doc = self.engine.health()
        doc.update(
            {
                "kind": "pool",
                "replica": self.replica,
                "shards": sorted(self.owned),
                "stream_lag": await self.lag(sorted(self.owned)),
                "samples": self.samples,
                "evaluate_us_per_sample": (
                    round(self.busy_ns / self.samples / 1000.0, 2)
                    if self.samples
                    else None
                ),
                "batch_ms_p99": (
                    round(_pct(self.batch_ms, 99), 2) if self.batch_ms else None
                ),
                "at": int(time.time() * 1000),
            }
        )
        return doc

    async def health(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(5.0)
            try:
                await self.r.hset(
                    HEALTH_KEY,
                    f"pool:{self.replica}",
                    json.dumps(await self.health_doc()),
                )
                await self.r.expire(HEALTH_KEY, 60)
            except Exception as exc:  # noqa: BLE001
                logger.debug("pool health write failed: %s", exc)

    async def http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode("latin-1")
            while (await asyncio.wait_for(reader.readline(), 5)) not in (
                b"\r\n",
                b"\n",
                b"",
            ):
                pass
            path = line.split(" ")[1] if " " in line else "/"
            code, body = 200, {}
            if path.startswith("/scale"):
                body = {
                    "lag": await self.lag(list(range(SHARDS))),
                    "replicas": len(await self.alive()),
                }
            else:
                fresh = time.time() - self.last_beat < 15
                code = 200 if fresh else 503
                body = {
                    "ok": fresh,
                    "replica": self.replica,
                    "shards": sorted(self.owned),
                }
            data = json.dumps(body).encode()
            writer.write(
                f"HTTP/1.1 {code} {'OK' if code == 200 else 'Service Unavailable'}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n"
                "Connection: close\r\n\r\n".encode() + data
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    # lifecycle

    async def run(self) -> None:
        await self.setup()
        server = await asyncio.start_server(self.http, "0.0.0.0", PORT)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass
        await self.beat()
        logger.info(
            "rules pool %s up, %s shards, health on :%s", self.replica, SHARDS, PORT
        )
        tasks = [
            asyncio.create_task(fn())
            for fn in (
                self.membership,
                self.read,
                self.events_writer,
                self.sweeper,
                self.loader,
                self.health,
            )
        ]
        await self.stop_event.wait()
        logger.info("rules pool %s stopping", self.replica)
        # hand the shards over at once rather than after the lease lapses
        for s in sorted(self.owned):
            try:
                await self.release(keys=[lease_key(s)], args=[self.replica])
            except Exception:  # noqa: BLE001
                pass
        await self.r.zrem(POOL_REPLICAS, self.replica)
        await self.r.hdel(HEALTH_KEY, f"pool:{self.replica}")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        server.close()
        await self.r.aclose()
        await self.rb.aclose()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("TELEMETRY_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(Pool().run())


if __name__ == "__main__":
    main()
