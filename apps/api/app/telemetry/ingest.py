"""Telemetry ingest: python -m app.telemetry.ingest

Every enabled connection runs its transport (a SourceConnector) on this
process. Envelopes go through the connection's decoder and mapping into
Records, and the store keeps those in Redis, TimescaleDB, events and alerts.

Replicas share connections through per-connection Redis leases placed by
rendezvous hashing over the live replicas, so a joining replica takes its share
and a dead one's connections move once its lease lapses. A connection whose
transport reads shared (a consumer group, $share) runs on every replica.
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
import uuid
from collections import defaultdict, deque
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.telemetry import evaluators as EV
from app.telemetry import history, perf
from app.telemetry import keys as K
from app.telemetry import pipeline as P
from app.telemetry import quota as Q
from app.telemetry import sources
from app.telemetry.connectors.base import Envelope
from app.telemetry.decoders.base import MappingError, Skipped
from app.telemetry.store import Batch, Store
from app.telemetry.writer import MERGE_LUA, Writer

logger = logging.getLogger("telemetry.ingest")

QUEUE_MAX = int(os.environ.get("TELEMETRY_QUEUE_MAX", "20000"))
PER_CONN_TURN = 256
HISTORY_MAX = int(os.environ.get("TELEMETRY_HISTORY_BUFFER", "200000"))
HTTP_PORT = int(os.environ.get("TELEMETRY_INGEST_PORT", "8090"))
LAT_WINDOW_S = 60.0
# message ids remembered per source: the last 15 minutes, at most 200,000
DEDUPE_WINDOW_S = 900
SCAN_GRACE_S = 30


def _transport_set(name: str) -> frozenset[str]:
    return frozenset(
        t.strip() for t in os.environ.get(name, "").split(",") if t.strip()
    )


# a pool of replicas can take only some transports, or every transport but some
POOL = os.environ.get("TELEMETRY_POOL", "default").strip() or "default"
TRANSPORTS = _transport_set("TELEMETRY_TRANSPORTS")
TRANSPORTS_EXCLUDE = _transport_set("TELEMETRY_TRANSPORTS_EXCLUDE")


def takes(
    transport: str, only: frozenset[str] | set[str], but: frozenset[str] | set[str]
) -> bool:
    if only and transport not in only:
        return False
    return transport not in but


DEDUPE_MAX = 200_000

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

__all__ = ["Ingest", "MERGE_LUA", "RELEASE_LUA", "RENEW_LUA", "owner_of", "percentile"]


def owner_of(conn_id: str, replicas: list[str]) -> str | None:
    """Rendezvous hashing: every replica computes the same owner from the same live set."""
    best, score = None, -1
    for r in replicas:
        s = int.from_bytes(hashlib.sha1(f"{conn_id}|{r}".encode()).digest()[:8], "big")
        if s > score:
            best, score = r, s
    return best


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    i = min(len(v) - 1, max(0, int(round(p / 100.0 * (len(v) - 1)))))
    return round(v[i], 2)


class Ingest:
    def __init__(self) -> None:
        self.replica = f"{socket.gethostname()}-{os.getpid()}"
        self.r = aioredis.from_url(settings.redis_url, decode_responses=True)
        self.runtimes: dict[str, P.Runtime] = {}
        self.rows: dict[str, dict[str, Any]] = {}
        self.history_interval_ms = 1000
        self.max_payload = 1_048_576
        self.writer = Writer(self.r)
        self.store = Store(self._lookup)
        self.history: deque = deque()
        self.history_dropped = 0
        self.history_written = 0
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.alerts: list[tuple[bool, dict[str, Any]]] = []
        self.gap_event_at: dict[tuple[str, str, str], float] = {}
        self.lat: dict[str, perf.Ring] = defaultdict(perf.Ring)
        self.e2e: dict[str, perf.Ring] = defaultdict(perf.Ring)
        self.tracer = perf.StallTracer()
        self.gc_timer = perf.GcTimer()
        self.cpu_wait = perf.CpuWait()
        self._alert_http: Any = None
        self.quotas: dict[str, dict[str, int]] = {}
        self.throttle_reason: dict[str, tuple[str, int, float]] = {}
        self.processed = 0
        self.stop_event = asyncio.Event()
        self.wake = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.changed = asyncio.Event()
        self.last_beat = 0.0
        self.pool: Any = None
        self.engine: Any = None
        self.session: Any = None
        self.evaluators: list[Any] = []
        # how late the event loop wakes, and how long a store flush takes, for the latency budget
        self.loop_lag: deque = deque(maxlen=1500)
        self.flush_ms: deque = deque(maxlen=2000)

    # wiring

    async def _setup(self) -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker

        self.loop = asyncio.get_running_loop()
        self.engine = create_async_engine(
            settings.database_url, pool_pre_ping=True, pool_size=3, max_overflow=2
        )
        self.session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self._scripts()
        from app.core.platform_settings import get_int_setting

        self.history_interval_ms = await get_int_setting(
            "telemetry.history_interval_ms", 1000
        )
        self.store.history_interval_ms = self.history_interval_ms
        self.max_payload = await get_int_setting(
            "telemetry.max_payload_bytes", 1_048_576
        )

    def _scripts(self) -> None:
        self.writer = Writer(self.r)
        self.merge = self.writer.merge
        self.renew = self.r.register_script(RENEW_LUA)
        self.release = self.r.register_script(RELEASE_LUA)

    async def _lookup(self, kind: str, t: str, g: str, n: str, d: str = "") -> Any:
        return await self.writer.lookup(kind, t, g, n, d)

    def _wake(self) -> None:
        self.wake.set()

    # connections, leases and rebalancing

    async def _load_rows(self) -> None:
        from sqlalchemy import select

        from models.telemetry import TelemetryConnection

        async with self.session() as db:
            rows = (await db.execute(select(TelemetryConnection))).scalars().all()
        out = {}
        for c in rows:
            try:
                row = P.connection_row(c)
            except Exception as exc:  # noqa: BLE001
                logger.warning("connection %s unreadable: %s", c.id, exc)
                continue
            out[row["id"]] = row
        self.rows = out

    def _shared(self, row: dict[str, Any]) -> bool:
        from app.telemetry import registry

        cls = registry.connectors().get(row["transport"])
        return bool(row["shared"] or (cls is not None and cls.scale_mode == "shared"))

    def _start(self, row: dict[str, Any]) -> None:
        assert self.loop is not None
        try:
            rt = P.Runtime(
                row, self.replica, self.loop, self._wake, self._lookup, QUEUE_MAX
            )
        except KeyError as exc:
            logger.warning("connection %s cannot start: %s", row["name"], exc)
            return
        self.runtimes[row["id"]] = rt
        rt.start()
        logger.info(
            "connection %s (%s, %s) started on %s",
            row["name"],
            row["transport"],
            row["id"],
            self.replica,
        )

    async def _stop(self, cid: str, release: bool = True) -> None:
        rt = self.runtimes.pop(cid, None)
        if rt is not None:
            await rt.stop()
            logger.info("connection %s stopped on %s", cid, self.replica)
            # its devices are now another replica's to watch
            self.store.drop_connection(cid)
        if release:
            await self.release(keys=[K.lease(cid)], args=[self.replica])
        await self.r.hdel(K.conn_status(cid), self.replica)

    async def alive(self) -> list[str]:
        now = int(time.time() * 1000)
        live = await self.r.zrangebyscore(K.REPLICAS, now - K.ALIVE_MS, "+inf")
        if self.replica not in live:
            live.append(self.replica)
        return sorted(live)

    async def _pools(self, alive: list[str]) -> dict[str, tuple[set[str], set[str]]]:
        """What each live replica takes, as (only, but). Missing means everything."""
        pipe = self.r.pipeline(transaction=False)
        for rid in alive:
            pipe.hmget(K.replica(rid), "transports", "transports_exclude")
        out = {}
        for rid, (only, but) in zip(alive, await pipe.execute()):
            out[rid] = (
                set(json.loads(only)) if only else set(),
                set(json.loads(but)) if but else set(),
            )
        out[self.replica] = (set(TRANSPORTS), set(TRANSPORTS_EXCLUDE))
        return out

    async def reconcile(self) -> None:
        alive = await self.alive()
        pools = await self._pools(alive)
        for cid, row in self.rows.items():
            rt = self.runtimes.get(cid)
            if rt is not None and rt.sig != row["sig"]:
                await self._stop(cid, release=False)
                rt = None
            mine = takes(row["transport"], TRANSPORTS, TRANSPORTS_EXCLUDE)
            if not row["enabled"] or not mine:
                if rt is not None:
                    await self._stop(cid)
                continue
            if self._shared(row):
                if rt is None:
                    self._start(row)
                continue
            eligible = [
                r
                for r in alive
                if takes(row["transport"], *pools.get(r, (set(), set())))
            ]
            want = owner_of(cid, eligible or [self.replica]) == self.replica
            if rt is not None:
                held = await self.renew(
                    keys=[K.lease(cid)], args=[self.replica, K.LEASE_MS]
                )
                if not held:
                    await self._stop(cid, release=False)
                elif not want:
                    # a replica joined and this connection is now its share
                    await self._stop(cid)
            elif want:
                got = await self.r.set(
                    K.lease(cid), self.replica, nx=True, px=K.LEASE_MS
                )
                if not got and await self.r.get(K.lease(cid)) == self.replica:
                    got = True
                if got:
                    self._start(row)
        for cid in [c for c in self.runtimes if c not in self.rows]:
            await self._stop(cid)

    async def reconcile_loop(self) -> None:
        last_load = 0.0
        while not self.stop_event.is_set():
            try:
                if self.changed.is_set() or time.monotonic() - last_load > 5.0:
                    self.changed.clear()
                    await self._load_rows()
                    last_load = time.monotonic()
                await self.reconcile()
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile failed: %s", exc)
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def change_listener(self) -> None:
        while not self.stop_event.is_set():
            try:
                ps = self.r.pubsub()
                await ps.subscribe(K.CHANGED, K.FORGOTTEN)
                async for msg in ps.listen():
                    if msg.get("type") != "message":
                        pass
                    elif msg.get("channel") == K.FORGOTTEN:
                        self._forgotten(msg.get("data"))
                    else:
                        self.changed.set()
                    if self.stop_event.is_set():
                        break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("change listener restarting: %s", exc)
                await asyncio.sleep(2)

    def _forgotten(self, raw: Any) -> None:
        try:
            doc = json.loads(raw)
            self.store.forget(str(doc["t"]), [tuple(x) for x in doc.get("items") or []])
        except (TypeError, ValueError, KeyError) as exc:
            logger.debug("bad forget notice: %s", exc)

    # the hot path

    async def consume(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            while True:
                taken: list[tuple[P.Runtime, Envelope]] = []
                # round robin, so one busy source cannot starve the others
                for rt in list(self.runtimes.values()):
                    q = rt.ctx.queue
                    for _ in range(min(len(q), PER_CONN_TURN)):
                        taken.append((rt, q.popleft()))
                    rt.ctx.taken()
                if not taken:
                    break
                try:
                    await self.process(taken)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("store write failed: %s", exc)
                    await asyncio.sleep(0.2)
                self.processed += len(taken)

    async def _dedupe(self, taken: list[tuple[P.Runtime, Envelope]]) -> set[int]:
        """Positions of envelopes whose msg_id this source sent in the last window."""
        ids = [(i, rt, env) for i, (rt, env) in enumerate(taken) if env.msg_id]
        if not ids:
            return set()
        now = time.time()
        pipe = self.r.pipeline(transaction=False)
        for _, rt, env in ids:
            pipe.zadd(K.dedupe(rt.info.id), {env.msg_id: now}, nx=True)
        res = await pipe.execute()
        if now - getattr(self, "_dedupe_trim_at", 0) > 5:
            self._dedupe_trim_at = now
            pipe = self.r.pipeline(transaction=False)
            for cid in {rt.info.id for _, rt, _ in ids}:
                key = K.dedupe(cid)
                pipe.zremrangebyscore(key, 0, now - DEDUPE_WINDOW_S)
                pipe.zremrangebyrank(key, 0, -DEDUPE_MAX - 1)
                pipe.expire(key, DEDUPE_WINDOW_S * 2)
            await pipe.execute()
        dup = set()
        seen_now: set[tuple[str, str]] = set()
        for (i, rt, env), added in zip(ids, res):
            k = (rt.info.id, env.msg_id)
            if not added or k in seen_now:
                dup.add(i)
            seen_now.add(k)
        return dup

    async def process(self, taken: list[tuple[P.Runtime, Envelope]]) -> None:
        b = Batch()
        dupes = await self._dedupe(taken)
        tokens: dict[str, list[Any]] = defaultdict(list)
        extra: list[tuple[str, tuple, dict]] = []
        now = time.time()
        for i, (rt, env) in enumerate(taken):
            if env.offset_token is not None:
                tokens[rt.info.id].append(env.offset_token)
            t = rt.info.tenant
            if i in dupes:
                b.stats[t]["duplicates"] += 1
                rt.bump(
                    "duplicates",
                    f"Message {env.msg_id} was already taken, so it was skipped.",
                )
                continue
            if not self.store.admit(rt.info, env.t_recv, b):
                cap = (self.quotas.get(t) or {}).get("max_msgs_per_sec", 0)
                rt.bump("throttled", Q.throttle_words("messages", cap))
                continue
            if len(env.payload) > self.max_payload:
                reason = (
                    f"The message is {len(env.payload)} bytes, more than the "
                    f"{self.max_payload} byte limit. Send smaller messages, or an admin can raise "
                    "telemetry.max_payload_bytes under Admin, Settings, Telemetry."
                )
                self._dead(rt, env, reason, extra, b, "too_large")
                continue
            try:
                records = await rt.decode(env)
                if env.headers:
                    records = sources.enforce(env.headers, records)
            except Skipped as exc:
                rt.bump("skipped", str(exc))
                if rt.inspect_ok(now):
                    self._ring(
                        K.inspector(t, rt.info.id),
                        P.inspector_entry(env, [], None, skipped=str(exc)),
                        P.INSPECTOR_RING,
                        extra,
                    )
                continue
            except MappingError as exc:
                self._dead(rt, env, f"Mapping: {exc}", extra, b, "mapping_failed")
                continue
            except Exception as exc:  # noqa: BLE001
                self._dead(
                    rt, env, P.plain_decode_error(exc), extra, b, "decode_failed"
                )
                continue
            rt.bump("decoded")
            useful = [
                r
                for r in records
                if r.metrics
                or r.frames
                or r.event is not None
                or r.kind in ("birth", "death", "state")
            ]
            if not useful:
                rt.bump(
                    "empty",
                    "The message was read but gave no readings. Check the mapping's signals, "
                    "include and exclude lists in the connection's mapping editor.",
                )
            else:
                rt.bump("mapped")
            if rt.inspect_ok(now):
                self._ring(
                    K.inspector(t, rt.info.id),
                    P.inspector_entry(env, records, None),
                    P.INSPECTOR_RING,
                    extra,
                )
            try:
                await self.store.apply(rt.info, records, env.t_recv, b)
                if useful:
                    rt.bump("stored")
                for ev in self.evaluators:
                    try:
                        ev.observe(rt.info, records, env.t_recv)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("evaluator %s failed: %s", ev.name, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("records from %s failed: %s", env.subject, exc)
                self._dead(
                    rt,
                    env,
                    f"Could not store these records: {exc}",
                    extra,
                    b,
                    "store_failed",
                )
        for rt in {id(rt): rt for rt, _ in taken}.values():
            for st in rt.states():
                if st.stats:
                    for k, v in st.stats.items():
                        b.stats[rt.info.tenant][k] += v
                    st.stats.clear()
                outbox, st.outbox = st.outbox, []
                for subject, payload in outbox:
                    asyncio.create_task(self._send(rt, subject, payload))
        f0 = time.perf_counter()
        counts = await self.writer.flush(b, extra)
        self.flush_ms.append((time.perf_counter() - f0) * 1000)
        if self.writer.gaps:
            await self._numbered_gaps(self.writer.gaps)
        await self._after(b, counts)
        for cid, toks in tokens.items():
            rt = self.runtimes.get(cid)
            if rt is not None:
                try:
                    await rt.connector.commit(toks)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("commit on %s failed: %s", rt.row["name"], exc)

    def _ring(self, key: str, item: str, cap: int, extra: list) -> None:
        extra.append(("lpush", (key, item), {}))
        extra.append(("ltrim", (key, 0, cap - 1), {}))

    def _dead(
        self,
        rt: P.Runtime,
        env: Envelope,
        reason: str,
        extra: list,
        b: Batch,
        kind: str = "decode_failed",
    ) -> None:
        t = rt.info.tenant
        rt.decode_errors += 1
        rt.bump("dlq", reason)
        rt.bump(kind, reason)
        b.stats[t]["dead_letters"] += 1
        self._ring(K.dlq(t, rt.info.id), P.dlq_entry(env, reason), P.DLQ_RING, extra)
        self._ring(
            K.inspector(t, rt.info.id),
            P.inspector_entry(env, None, reason),
            P.INSPECTOR_RING,
            extra,
        )

    async def _send(self, rt: P.Runtime, subject: str, payload: bytes) -> None:
        try:
            await rt.connector.write(
                rt.ctx.config,
                rt.ctx.secrets,
                {"topic": subject, "payload": payload, "connection_id": rt.info.id},
                None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("send on %s failed: %s", rt.row["name"], exc)

    async def _numbered_gaps(
        self, gaps: list[tuple[str, str, str, str, int, int]]
    ) -> None:
        """Missing batch numbers from sources that number them, such as Abenix Edge."""
        g2 = Batch()
        for t, g, n, cid, seq, delta in gaps:
            g2.stats[t]["seq_gaps"] += delta
            g2.index.append((t, K.index_field(g, n, ""), {"inc": {"seq_gaps": delta}}))
            g2.events.append(
                (
                    t,
                    "telemetry.seq_gap",
                    {
                        "group": g,
                        "node": n,
                        "received": seq,
                        "missing": delta,
                        "connection_id": cid,
                    },
                )
            )
        self.writer.gaps = []
        await self.writer.flush(g2)
        self.writer.gaps = []
        await self._after(g2, {})

    async def _after(self, b: Batch, counts: dict[str, int]) -> None:
        now = time.time()
        sec = int(now)
        for t, t_recv, ts in b.latencies:
            self.lat[t].add(now, (now - t_recv) * 1000.0)
            self.e2e[t].add(now, now * 1000.0 - ts)
        for t, used in counts.items():
            cap = (self.quotas.get(t) or {}).get("max_msgs_per_sec")
            if cap and used > cap:
                self.store.throttled[t] = sec
                self.throttle_reason[t] = ("messages", cap, now)
        for t, c in b.stats.items():
            if c.get("_cap_hit"):
                cap = (self.quotas.get(t) or {}).get("max_devices", 0)
                self.throttle_reason[t] = ("devices", cap, now)
        if b.history:
            room = HISTORY_MAX - len(self.history)
            if room < len(b.history):
                self.history_dropped += len(b.history) - max(room, 0)
            self.history.extend(b.history[: max(room, 0)])
        for ev in b.events:
            if ev[1] == "telemetry.seq_gap":
                key = (ev[0], ev[2]["group"], ev[2]["node"])
                if now - self.gap_event_at.get(key, 0) < 10:
                    continue
                self.gap_event_at[key] = now
            if len(self.events) < 5000:
                self.events.append(ev)
        self.alerts.extend(b.alerts)

    # periodic work

    async def fast_flush(self) -> None:
        while not self.stop_event.is_set():
            await asyncio.sleep(0.1)
            try:
                pubs = self.store.take_sse()
                if pubs:
                    pipe = self.r.pipeline(transaction=False)
                    for ch, msg in pubs:
                        pipe.publish(ch, msg)
                    await pipe.execute()
            except Exception as exc:  # noqa: BLE001
                logger.debug("live flush failed: %s", exc)

    async def slow_flush(self) -> None:
        tick = 0
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            tick += 1
            try:
                await self._flush_seen_and_feeds()
                await self._write_health()
                await self._sweep()
                if tick % 30 == 3:
                    await self.offline_scan()
                if tick % 5 == 0:
                    await self._refresh_counts()
                if tick % 30 == 1:
                    await self._refresh_quotas()
            except Exception as exc:  # noqa: BLE001
                logger.warning("periodic flush failed: %s", exc)

    async def beat(self) -> None:
        """Liveness and lease renewal on their own, so a slow health pass never loses the leases."""
        while not self.stop_event.is_set():
            try:
                now = int(time.time() * 1000)
                await self.r.zadd(K.REPLICAS, {self.replica: now})
                for cid in list(self.runtimes):
                    row = self.rows.get(cid)
                    if row is not None and not self._shared(row):
                        await self.renew(
                            keys=[K.lease(cid)], args=[self.replica, K.LEASE_MS]
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def lag_watch(self) -> None:
        self.tracer.start()
        started = time.monotonic()
        refrozen = False
        while not self.stop_event.is_set():
            t0 = time.perf_counter()
            self.tracer.tick()
            await asyncio.sleep(0.02)
            self.loop_lag.append(max(0.0, (time.perf_counter() - t0 - 0.02) * 1000))
            self.cpu_wait.sample()
            if not refrozen and time.monotonic() - started > 45:
                # the client libraries are imported once connections start, freeze them too
                refrozen = True
                perf.tune_gc()
        self.tracer.stop()

    async def _sweep(self) -> None:
        now = time.time()
        due = self.store.due(now)
        shared = [x for x in due if x[1].shared]
        if shared:
            # another replica may still be hearing a device of a shared source
            pipe = self.r.pipeline(transaction=False)
            for (t, g, n, d), _, _, _ in shared:
                pipe.hmget(K.device(t, g, n, d), "_last_seen", "_online")
            heard = await pipe.execute()
            keep = set()
            for (key, conn, at, limit), (raw, online) in zip(shared, heard):
                if online != "1":
                    # another replica already took it offline
                    self.store.last_data.pop(key, None)
                    keep.add(key)
                    continue
                last = K.as_int(raw) / 1000.0
                if last > at:
                    self.store.last_data[key] = (last, conn)
                    if now - last <= limit:
                        keep.add(key)
            due = [x for x in due if x[0] not in keep]
            due = [
                (key, conn, self.store.last_data.get(key, (at,))[0], limit)
                for key, conn, at, limit in due
            ]
        b = Batch()
        self.store.take_offline(due, now, b)
        if b.index or b.hset or b.events or b.alerts:
            await self.writer.flush(b)
            await self._after(b, {})

    async def offline_scan(self) -> None:
        """One replica checks every device a source without births left online.

        It catches devices no replica has heard from since a restart, a little after the replica
        that is hearing them would have, so the two never both announce it.
        """
        if not await self._hold("offline-scan", 60000):
            return
        now = time.time()
        b = Batch()
        conns: dict[str, dict[str, Any]] = defaultdict(dict)
        for cid, row in list(self.rows.items()):
            if row["enabled"] and row.get("decoder") != "sparkplug_b":
                conns[row["tenant"]][cid] = P.conn_info(row)
        for t, mine in conns.items():
            gone = []
            for raw in (await self.r.hgetall(K.index(t)) or {}).values():
                try:
                    doc = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                conn = mine.get(doc.get("connection_id") or "")
                if conn is None or not doc.get("online"):
                    continue
                g, n, d = doc.get("group"), doc.get("node"), doc.get("device") or ""
                if not g or not n or (t, g, n, d) in self.store.last_data:
                    continue
                seen = (doc.get("last_seen") or 0) / 1000.0
                gap = doc.get("gap_s")
                limit = self.store.offline_after(conn, float(gap) if gap else None)
                if seen and now - seen > limit + SCAN_GRACE_S:
                    ts = int((seen + limit) * 1000)
                    self.store._offline(conn, t, g, n, d, ts, b)
                    gone.append((conn, g, n, d, ts))
            if gone:
                self.store.announce_offline(gone, now, b)
        self.store.flush_offline(now, b)
        if b.index or b.hset or b.events or b.alerts:
            await self.writer.flush(b)
            await self._after(b, {})

    async def _flush_seen_and_feeds(self) -> None:
        pipe = self.r.pipeline(transaction=False)
        for key, val in self.store.take_feeds(time.time()).items():
            pipe.set(key, val, ex=86400)
        now_ms = int(time.time() * 1000)
        for (t, cid), names in self.store.take_signals().items():
            sk = K.signals(t, cid)
            seen = self.store.signals_seen.get((t, cid)) or {}
            for name in names:
                doc = dict(seen.get(name) or {})
                doc["last_seen"] = now_ms
                pipe.hset(sk, name, json.dumps(doc, default=str))
        seen = self.store.take_seen()
        prev = int(time.time()) - 1
        rates: dict[str, dict[str, str]] = {}
        for t in {s[0] for s in seen}:
            rates[t] = await self.r.hgetall(K.rate(t, prev))
        for t, g, n, d, at, cid in seen:
            for dev in {d, ""}:
                field = K.index_field(g, n, dev)
                mps = (
                    rates.get(t, {}).get(field)
                    if dev
                    else rates.get(t, {}).get(f"{g}/{n}")
                )
                pipe.hset(
                    K.device(t, g, n, dev),
                    mapping={"_last_seen": str(at), "_mps": str(mps or 0)},
                )
                await self.merge(
                    keys=[K.index(t)],
                    args=[
                        field,
                        json.dumps(
                            {
                                "max": {"last_seen": at},
                                "connection_id": cid,
                                "group": g,
                                "node": n,
                                "device": dev,
                                # the usual gap, so a restarted ingest still knows when it went quiet
                                "gap_s": self.store.interval_s((t, g, n, dev)),
                            }
                        ),
                    ],
                    client=pipe,
                )
        await pipe.execute()

    async def _write_health(self) -> None:
        now = time.time()
        pipe = self.r.pipeline(transaction=False)
        total_mps = 0.0
        queued = 0
        dropped = 0
        for cid, rt in self.runtimes.items():
            ctx = rt.ctx
            mps = rt.mps()
            total_mps += mps
            queued += len(ctx.queue)
            dropped += ctx.dropped
            skew = self.store.skew.get(cid)
            status = {
                "status": ctx.status,
                "last_error": ctx.last_error,
                "messages_per_second": mps,
                "last_message_at": (
                    int(ctx.last_message_at * 1000) if ctx.last_message_at else None
                ),
                "queued": len(ctx.queue),
                "dropped": ctx.dropped,
                "decode_errors": rt.decode_errors,
                "pipeline": {
                    "received": ctx.received,
                    "dropped": ctx.dropped,
                    **rt.counts,
                },
                "last_reasons": {
                    **rt.reasons,
                    **(
                        {
                            "dropped": {
                                "reason": "The queue for this connection was full, so new messages were dropped. Add ingest replicas or mark the source shared.",
                                "at": None,
                            }
                        }
                        if ctx.dropped
                        else {}
                    ),
                },
                "clock_skew_ms": round(skew) if skew is not None else None,
                "replica": self.replica,
                "at": int(now * 1000),
            }
            pipe.hset(K.conn_status(cid), self.replica, json.dumps(status))
            pipe.expire(K.conn_status(cid), 30)
        lat_all: list[float] = []
        for t in set(self.lat) | set(self.e2e):
            vals = self.lat[t].since(now - LAT_WINDOW_S)
            e2e = self.e2e[t].since(now - LAT_WINDOW_S)
            lat_all.extend(vals)
            if vals:
                pipe.hset(
                    K.latency(t),
                    self.replica,
                    json.dumps(
                        {
                            "p50": percentile(vals, 50),
                            "p99": percentile(vals, 99),
                            "e2e_p50": percentile(e2e, 50),
                            "e2e_p99": percentile(e2e, 99),
                            "n": len(vals),
                            "at": int(now * 1000),
                        }
                    ),
                )
                pipe.expire(K.latency(t), 15)
        for t, (kind, cap, at) in list(self.throttle_reason.items()):
            back_under = kind == "devices" and self.store.device_count.get(t, 0) < cap
            if back_under:
                # devices were forgotten, the banner goes now rather than in a minute
                self.throttle_reason.pop(t, None)
                pipe.delete(K.throttle(t))
                continue
            if now - at > 60:
                self.throttle_reason.pop(t, None)
                continue
            pipe.hset(
                K.throttle(t),
                mapping={
                    "kind": kind,
                    "limit": cap,
                    "reason": Q.throttle_words(kind, cap),
                    "at": int(at * 1000),
                },
            )
            pipe.expire(K.throttle(t), 60)
        rep = {
            "replica": self.replica,
            "connections": json.dumps(sorted(self.runtimes)),
            "messages_per_second": round(total_mps, 1),
            "queued": queued,
            "dropped": dropped,
            "history_buffer": len(self.history),
            "history_dropped": self.history_dropped,
            "history_written": self.history_written,
            "processed": self.processed,
            "pool": POOL,
            "transports": json.dumps(sorted(TRANSPORTS)) if TRANSPORTS else "",
            "transports_exclude": (
                json.dumps(sorted(TRANSPORTS_EXCLUDE)) if TRANSPORTS_EXCLUDE else ""
            ),
            "loop_lag_ms_max": round(max(self.loop_lag or [0]), 1),
            "stalls": self.tracer.stalls,
            "gc": json.dumps(self.gc_timer.snapshot()),
            "last_stall": self.tracer.last or "",
            "loop_lag_ms_p99": percentile(list(self.loop_lag), 99) or 0,
            "cpu_wait_pct": self.cpu_wait.pct,
            "loop_cpu_pct": self.cpu_wait.cpu_pct,
            "flush_ms_p99": percentile(list(self.flush_ms), 99) or 0,
            "evaluators": json.dumps([getattr(e, "name", "") for e in self.evaluators]),
            "latency_p50": percentile(lat_all, 50) or 0,
            "latency_p99": percentile(lat_all, 99) or 0,
            "at": int(now * 1000),
        }
        pipe.hset(K.replica(self.replica), mapping=rep)
        pipe.expire(K.replica(self.replica), 10)
        pipe.zadd(K.REPLICAS, {self.replica: int(now * 1000)})
        pipe.zremrangebyscore(K.REPLICAS, 0, int(now * 1000) - 60000)
        await pipe.execute()
        self.last_beat = now

    async def _refresh_counts(self) -> None:
        for t in {row["tenant"] for row in self.rows.values()}:
            self.store.device_count[t] = await self.r.hlen(K.index(t))

    async def _refresh_quotas(self) -> None:
        tenants = {row["tenant"] for row in self.rows.values()}
        if not tenants:
            return
        from sqlalchemy import select

        from models.tenant import Tenant

        base = await Q.defaults()
        async with self.session() as db:
            rows = (
                await db.execute(
                    select(Tenant.id, Tenant.settings).where(
                        Tenant.id.in_([uuid.UUID(t) for t in tenants])
                    )
                )
            ).all()
        for tid, st in rows:
            q = Q.merge(base, st)
            self.quotas[str(tid)] = q
            self.store.device_cap[str(tid)] = q["max_devices"]
        from app.core.platform_settings import get_int_setting

        self.store.default_offline_s = await get_int_setting(
            "telemetry.default_offline_after_s", 0
        )

    async def history_writer(self) -> None:
        failures = 0
        while not self.stop_event.is_set():
            await asyncio.sleep(0.25)
            if not self.history:
                continue
            if self.pool is None:
                try:
                    self.pool = await history.create_pool()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("history store unreachable: %s", exc)
                    await asyncio.sleep(5)
                    continue
            n = min(len(self.history), 20000)
            rows = [self.history.popleft() for _ in range(n)]
            try:
                self.history_written += await history.write(self.pool, rows)
                failures = 0
            except Exception as exc:  # noqa: BLE001
                failures += 1
                logger.warning("history write failed (%s rows): %s", n, exc)
                if failures < 5:
                    self.history.extendleft(reversed(rows))
                else:
                    self.history_dropped += n
                await asyncio.sleep(min(10, failures))

    async def events_writer(self) -> None:
        from app.services import events as E

        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            if not self.events:
                continue
            batch, self.events = self.events, []
            try:
                async with self.session() as db:
                    for t, kind, payload in batch:
                        await E.emit(db, t, kind, payload)
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("event write failed: %s", exc)

    async def alerts_loop(self) -> None:
        refresh_at = 0.0
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            batch, self.alerts = self.alerts, []
            for firing, a in batch:
                await self._alert(firing, a)
            if time.monotonic() - refresh_at > 60 and await self._hold("maint", 90000):
                refresh_at = time.monotonic()
                for raw in (await self.r.hgetall("tel:alerts:firing")).values():
                    try:
                        await self._post_alert(json.loads(raw), True)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("alert refresh failed: %s", exc)

    async def _alert(self, firing: bool, a: dict[str, Any]) -> None:
        lab = a["labels"]
        key = "|".join(lab[k] for k in ("tenant_id", "group", "node", "device"))
        if a.get("once"):
            pass
        elif firing:
            await self.r.hset("tel:alerts:firing", key, json.dumps(a))
        else:
            existed = await self.r.hdel("tel:alerts:firing", key)
            if not existed:
                return
        try:
            await self._post_alert(a, firing)
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert post failed: %s", exc)

    async def _post_alert(self, a: dict[str, Any], firing: bool) -> None:
        from datetime import datetime, timezone

        import httpx

        starts = datetime.fromtimestamp(a["at"] / 1000.0, tz=timezone.utc).isoformat()
        base = (os.environ.get("ALERTMANAGER_URL") or "").strip().rstrip("/")
        if base:
            body = {
                "labels": a["labels"],
                "annotations": a["annotations"],
                "startsAt": starts,
                "generatorURL": "/telemetry",
            }
            if not firing:
                body["endsAt"] = datetime.now(timezone.utc).isoformat()
            if self._alert_http is None:
                # one client, a new one per alert builds an SSL context on the loop
                self._alert_http = httpx.AsyncClient(timeout=5.0)
            r = await self._alert_http.post(f"{base}/api/v2/alerts", json=[body])
            r.raise_for_status()
            return
        from app.core import notifications as notif

        async with self.session() as db:
            await notif.notify_platform_alert(
                db,
                name=a["labels"]["alertname"],
                severity=a["labels"]["severity"],
                summary=a["annotations"]["summary"],
                since=starts,
                labels=a["labels"],
                link="/telemetry",
                status="firing" if firing else "resolved",
                source="telemetry",
            )
            await db.commit()

    async def _hold(self, name: str, px: int) -> bool:
        key = K.lease(f"job:{name}")
        if await self.r.set(key, self.replica, nx=True, px=px):
            return True
        return bool(await self.renew(keys=[key], args=[self.replica, px]))

    async def forget_sweep(self) -> None:
        """Hourly, one replica forgets devices offline past telemetry.forget_offline_after_days."""
        from app.core.platform_settings import get_int_setting
        from app.telemetry import access, lifecycle

        everyone = access.Scope(
            everything=True, visible=set(), commandable=set(), teams={}, connections=[]
        )
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=3600)
                break
            except asyncio.TimeoutError:
                pass
            try:
                days = await get_int_setting("telemetry.forget_offline_after_days", 30)
                if days <= 0 or not await self._hold("forget", 1_800_000):
                    continue
                for t in sorted({row["tenant"] for row in self.rows.values()}):
                    total = 0
                    for _ in range(50):
                        out = await lifecycle.forget_matching(
                            self.r, t, everyone, offline_for_s=days * 86400
                        )
                        total += out["forgotten"]
                        if not out["forgotten"] or not out["remaining"]:
                            break
                        await asyncio.sleep(0.5)
                    if total:
                        logger.info(
                            "forgot %s devices offline over %s days in %s",
                            total,
                            days,
                            t,
                        )
            except Exception as exc:  # noqa: BLE001
                logger.warning("forget sweep failed: %s", exc)

    async def maintenance(self) -> None:
        while not self.stop_event.is_set():
            try:
                if await self._hold("schema", 120000):
                    if self.pool is None:
                        self.pool = await history.create_pool()
                    base = await Q.defaults()
                    longest = base["retention_days"]
                    from sqlalchemy import select

                    from models.tenant import Tenant

                    async with self.session() as db:
                        tenants = (
                            await db.execute(select(Tenant.id, Tenant.settings))
                        ).all()
                    per = {
                        str(tid): Q.merge(base, st)["retention_days"]
                        for tid, st in tenants
                    }
                    longest = max([longest, *per.values()])
                    await history.ensure_schema(self.pool, longest)
                    await self.r.set("tel:tsdb:schema", history.SCHEMA_VERSION)
                    for tid, days in per.items():
                        if days < longest:
                            await history.prune_tenant(self.pool, tid, days)
            except Exception as exc:  # noqa: BLE001
                logger.warning("history maintenance failed: %s", exc)
                await asyncio.sleep(30)
                continue
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=600)
            except asyncio.TimeoutError:
                pass

    # health endpoint for probes and KEDA

    async def scale_doc(self) -> dict[str, Any]:
        reps = await self.alive()
        mps = 0.0
        queued = 0
        mine = []
        for rid in reps:
            h = await self.r.hgetall(K.replica(rid))
            if (h.get("pool") or "default") != POOL:
                continue
            mine.append(rid)
            mps += float(h.get("messages_per_second") or 0)
            queued += int(h.get("queued") or 0)
        return {
            "pool": POOL,
            "replicas": len(mine),
            "messages_per_second": round(mps, 1),
            "queued": queued,
            "replica": self.replica,
            "connections": sorted(self.runtimes),
        }

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
                body = await self.scale_doc()
            else:
                fresh = time.time() - self.last_beat < 15
                code = 200 if fresh else 503
                body = {
                    "ok": fresh,
                    "replica": self.replica,
                    "connections": len(self.runtimes),
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
        await self._setup()
        self.evaluators = []
        for ev in EV.load():
            try:
                await ev.start(self)
                self.evaluators.append(ev)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "evaluator %s did not start: %s", getattr(ev, "name", ev), exc
                )
        perf.tune_gc()
        self.gc_timer.install()
        server = await asyncio.start_server(self.http, "0.0.0.0", HTTP_PORT)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass
        await self._write_health()
        logger.info("telemetry ingest %s up, health on :%s", self.replica, HTTP_PORT)
        tasks = [
            asyncio.create_task(fn())
            for fn in (
                self.reconcile_loop,
                self.change_listener,
                self.consume,
                self.fast_flush,
                self.slow_flush,
                self.history_writer,
                self.events_writer,
                self.alerts_loop,
                self.maintenance,
                self.forget_sweep,
                self.lag_watch,
                self.beat,
            )
        ]
        await self.stop_event.wait()
        logger.info("telemetry ingest %s stopping", self.replica)
        for cid in list(self.runtimes):
            await self._stop(cid)
        await self.r.zrem(K.REPLICAS, self.replica)
        await self.r.delete(K.replica(self.replica))
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.history and self.pool is not None:
            try:
                await history.write(self.pool, list(self.history))
            except Exception:  # noqa: BLE001
                pass
        for ev in self.evaluators:
            try:
                await ev.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("evaluator %s did not stop cleanly: %s", ev.name, exc)
        server.close()
        if self._alert_http is not None:
            await self._alert_http.aclose()
        await self.r.aclose()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("TELEMETRY_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    asyncio.run(Ingest().run())


if __name__ == "__main__":
    main()
