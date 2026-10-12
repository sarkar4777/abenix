"""Signal rules evaluated in the ingest, at stream time.

observe() runs on the ingest hot path. It only looks the record's signals up in
the workspace's index and queues the matches, so a workspace without rules pays
one dict lookup per record. A worker task then advances each rule's state machine.

Where a rule's state lives depends on the connection:
- a lease connection is read by one replica at a time, so the state stays in memory
- a shared connection (consumer group, $share) spreads one asset over replicas, so
  the state is a JSON blob in Redis, advanced with a compare-and-set and retried

Every fire or clear then passes a Redis guard keyed by rule, asset and sample time,
so the same transition is never sent twice by two replicas, and the cooldown and a
per-rule flood cap hold across replicas too. Stale rules are not message driven: one
replica, holding a lease, sweeps the last-seen times in Redis every second.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.telemetry import keys as K
from app.telemetry.rules.conditions import Outcome, Sample, fmt, step
from app.telemetry.rules.index import (
    AssetFacts,
    Compiled,
    TenantIndex,
    akey,
    build,
    compile_rule,
)

logger = logging.getLogger("telemetry.rules")

STREAM = "tel:rules:fired"
STREAM_MAX = 10_000
VERSION_KEY = "tel:rules:version"
HEALTH_KEY = "tel:rules:health"
QUEUE_MAX = 100_000
MEM_MAX = 200_000
STATE_TTL_MS = 7 * 86_400_000
FLOOD_PER_MIN = 60
# small chunks with a yield between, so evaluation never holds the ingest loop for long
DRAIN_MAX = 500
CAS_TRIES = 4

# the rules pool: samples go to one stream per shard, a shard is owned by one pool replica
SHARDS = 16
IN_STREAM_MAX = 20_000
POOL_REPLICAS = "tel:rules:pool:replicas"
POOL_ALIVE_MS = 6000
MODE_SETTING = "telemetry.rules_mode"
MODE_OVERRIDE = "telemetry_rules_mode"
MODES = ("inprocess", "pool")


def shard_of(tenant: str) -> int:
    return int(hashlib.sha1(str(tenant).encode()).hexdigest()[:8], 16) % SHARDS


def in_stream(shard: int) -> str:
    return f"tel:rules:in:{shard}"


CAS_LUA = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if not cur then cur = '' end
if cur ~= ARGV[2] then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
redis.call('PEXPIRE', KEYS[1], ARGV[4])
return 1
"""

GUARD_LUA = """
if not redis.call('SET', KEYS[1], '1', 'NX', 'PX', 600000) then return 0 end
if ARGV[3] == '1' then
  if tonumber(ARGV[1]) > 0 then
    if not redis.call('SET', KEYS[2], '1', 'NX', 'PX', ARGV[1]) then return -1 end
  end
  local n = redis.call('INCR', KEYS[3])
  if n == 1 then redis.call('PEXPIRE', KEYS[3], 60000) end
  if n > tonumber(ARGV[2]) then return -2 end
end
return 1
"""


def state_key(t: str, rid: str) -> str:
    return f"tel:{t}:rs:{rid}"


def guard_keys(t: str, rid: str, ak: str, ts: int, kind: str) -> list[str]:
    return [
        f"tel:{t}:rg:{rid}:{ak}:{ts}:{kind}",
        f"tel:{t}:rc:{rid}:{ak}",
        f"tel:{t}:rn:{rid}",
    ]


# shared state and the guard, Redis in production and memory in tests and previews


class RedisShared:
    def __init__(self, r: Any) -> None:
        self.r = r
        self.cas_script = r.register_script(CAS_LUA)

    async def load(self, keys: list[tuple[str, str, str]]) -> list[str | None]:
        pipe = self.r.pipeline(transaction=False)
        for t, rid, ak in keys:
            pipe.hget(state_key(t, rid), ak)
        return list(await pipe.execute())

    async def cas(self, items: list[tuple[str, str, str, str, str]]) -> list[bool]:
        pipe = self.r.pipeline(transaction=False)
        for t, rid, ak, old, new in items:
            await self.cas_script(
                keys=[state_key(t, rid)], args=[ak, old, new, STATE_TTL_MS], client=pipe
            )
        return [bool(int(x or 0)) for x in await pipe.execute()]


class RedisGuard:
    def __init__(self, r: Any) -> None:
        self.r = r
        self.script = r.register_script(GUARD_LUA)

    async def admit(
        self, items: list[tuple[str, str, str, int, str, int]]
    ) -> list[int]:
        if not items:
            return []
        pipe = self.r.pipeline(transaction=False)
        for t, rid, ak, ts, kind, cooldown_ms in items:
            await self.script(
                keys=guard_keys(t, rid, ak, ts, kind),
                args=[cooldown_ms, FLOOD_PER_MIN, "1" if kind == "fire" else "0"],
                client=pipe,
            )
        return [int(x or 0) for x in await pipe.execute()]


class MemoryShared:
    """Same contract as RedisShared, for tests and for two engines sharing one store."""

    def __init__(self) -> None:
        self.h: dict[tuple[str, str], dict[str, str]] = {}
        # a hook a test uses to change the store between load and cas
        self.before_cas: Callable[[], None] | None = None

    async def load(self, keys):
        return [self.h.get((t, rid), {}).get(ak) for t, rid, ak in keys]

    async def cas(self, items):
        if self.before_cas:
            hook, self.before_cas = self.before_cas, None
            hook()
        out = []
        for t, rid, ak, old, new in items:
            h = self.h.setdefault((t, rid), {})
            if (h.get(ak) or "") != old:
                out.append(False)
                continue
            h[ak] = new
            out.append(True)
        return out


class MemoryGuard:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self.seen: set[str] = set()
        self.cool: dict[str, float] = {}
        self.counts: dict[str, tuple[float, int]] = {}
        self.clock = clock

    async def admit(self, items):
        out = []
        now = self.clock()
        for t, rid, ak, ts, kind, cooldown_ms in items:
            k1, k2, k3 = guard_keys(t, rid, ak, ts, kind)
            if k1 in self.seen:
                out.append(0)
                continue
            self.seen.add(k1)
            if kind == "fire":
                if cooldown_ms > 0:
                    if self.cool.get(k2, 0) > now:
                        out.append(-1)
                        continue
                    self.cool[k2] = now + cooldown_ms / 1000.0
                start, n = self.counts.get(k3, (now, 0))
                if now - start > 60:
                    start, n = now, 0
                self.counts[k3] = (start, n + 1)
                if n + 1 > FLOOD_PER_MIN:
                    out.append(-2)
                    continue
            out.append(1)
        return out


@dataclass(slots=True)
class Item:
    rule: Compiled
    g: str
    n: str
    d: str
    sample: Sample
    shared: bool
    conn_id: str
    t_recv: float


# hand-off format: the first byte of field b is the version, so mixed replicas can roll
PACK_V2 = 2


def _pack_v1(items: list[Item]) -> dict[int, list[dict[str, str]]]:
    """The first format, JSON rows. Still read, no longer written."""
    by: dict[tuple[int, str], list[list[Any]]] = {}
    for it in items:
        s = it.sample
        by.setdefault((shard_of(it.rule.tenant), it.rule.tenant), []).append(
            [
                it.rule.id,
                it.g,
                it.n,
                it.d,
                s.value,
                s.ts,
                s.signal,
                s.extra or 0,
                it.conn_id,
                round(it.t_recv, 4),
            ]
        )
    out: dict[int, list[dict[str, str]]] = {}
    for (shard, t), rows in by.items():
        out.setdefault(shard, []).append(
            {"t": t, "s": json.dumps(rows, separators=(",", ":"), default=str)}
        )
    return out


def _encodable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, float, str, bytes, list, dict)):
        return v
    return str(v)


def pack(items: list[Item]) -> dict[int, list[dict[str, Any]]]:
    """Samples as stream entries per shard, one msgpack entry per tenant and batch.

    Rule ids, assets, signals and connections repeat a lot inside one batch, so each
    goes once into a table and the rows point at it."""
    import msgpack

    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for it in items:
        t = it.rule.tenant
        key = (shard_of(t), t)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "r": {},
                "a": {},
                "s": {},
                "c": {},
                "rows": [],
            }
        s = it.sample
        ri = g["r"].setdefault(it.rule.id, len(g["r"]))
        ai = g["a"].setdefault((it.g, it.n, it.d), len(g["a"]))
        si = g["s"].setdefault(s.signal, len(g["s"]))
        ci = g["c"].setdefault(it.conn_id, len(g["c"]))
        g["rows"].append(
            (ri, ai, si, _encodable(s.value), s.ts, s.extra or None, ci, it.t_recv)
        )
    out: dict[int, list[dict[str, Any]]] = {}
    for (shard, t), g in groups.items():
        body = msgpack.packb(
            (
                list(g["r"]),
                [list(a) for a in g["a"]],
                list(g["s"]),
                list(g["c"]),
                g["rows"],
            ),
            use_bin_type=True,
        )
        out.setdefault(shard, []).append({"t": t, "b": bytes([PACK_V2]) + body})
    return out


def _txt(v: Any) -> str:
    return v.decode() if isinstance(v, bytes) else str(v or "")


def unpack(fields: dict[Any, Any], rules: dict[str, Compiled]) -> list[Item]:
    """Stream entry back to samples, either format. A rule deleted since is skipped."""
    f = {_txt(k): v for k, v in fields.items()}
    out: list[Item] = []
    raw = f.get("b")
    if raw:
        if isinstance(raw, str):
            raw = raw.encode("latin-1")
        if raw[0] != PACK_V2:
            # a newer replica wrote a format this one does not know, leave it to them
            raise ValueError(f"hand-off format {raw[0]} is newer than this replica")
        import msgpack

        rids, assets, sigs, conns, rows = msgpack.unpackb(raw[1:], raw=False)
        for ri, ai, si, value, ts, extra, ci, t_recv in rows:
            r = rules.get(rids[ri])
            if r is None:
                continue
            g, n, d = assets[ai]
            out.append(
                Item(
                    r,
                    g,
                    n,
                    d,
                    Sample(value, int(ts), sigs[si], dict(extra) if extra else {}),
                    True,
                    conns[ci],
                    float(t_recv),
                )
            )
        return out
    try:
        rows = json.loads(_txt(f.get("s")) or "[]")
    except ValueError:
        return out
    for rid, g, n, d, value, ts, sig, extra, conn, t_recv in rows:
        r = rules.get(rid)
        if r is None:
            continue
        out.append(
            Item(
                r,
                g,
                n,
                d,
                Sample(value, int(ts), sig, dict(extra) if extra else {}),
                True,
                conn,
                float(t_recv),
            )
        )
    return out


Emit = Callable[[list[dict[str, Any]]], Awaitable[None]]


class Engine:
    """Everything but the I/O loops: index, queue, state machines, guard and the firing documents."""

    def __init__(self, shared: Any, guard: Any, emit: Emit) -> None:
        self.shared = shared
        self.guard = guard
        self.emit = emit
        self.index: dict[str, TenantIndex] = {}
        self.mem: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
        self.queue: deque[Item] = deque()
        self.coords: dict[tuple[str, str, str, str, str], Any] = {}
        self.stats = {
            "queued": 0,
            "dropped": 0,
            "fired": 0,
            "cleared": 0,
            "suppressed": 0,
            "flood": 0,
            "duplicate": 0,
            "cas_retry": 0,
            "cas_failed": 0,
        }
        self.lag: deque[float] = deque(maxlen=20_000)
        # where each workspace's rules run, and whether a pool is up to take them
        self.default_mode = "inprocess"
        self.modes: dict[str, str] = {}
        self.pool_alive = False
        self.forwarded = 0

    def mode(self, tenant: str) -> str:
        m = self.modes.get(tenant, self.default_mode)
        return "pool" if m == "pool" and self.pool_alive else "inprocess"

    def by_id(self) -> dict[str, Compiled]:
        out = {}
        for ti in self.index.values():
            for rules in ti.by_signal.values():
                for r in rules:
                    out[r.id] = r
            for r in ti.stale:
                out[r.id] = r
        return out

    def load(self, rules: list[dict[str, Any]], assets: list[dict[str, Any]]) -> None:
        facts: dict[str, AssetFacts] = {}
        for a in assets:
            f = facts.setdefault(str(a["tenant_id"]), AssetFacts())
            f.rows[akey(a["grp"], a["node"], a.get("device") or "")] = {
                "type": a.get("asset_type"),
                "tags": list(a.get("tags") or []),
                "name": a.get("display_name"),
            }
        compiled = []
        for row in rules:
            try:
                compiled.append(compile_rule(row))
            except Exception as exc:  # noqa: BLE001
                logger.warning("rule %s skipped: %s", row.get("id"), exc)
        self.index = build(compiled, facts)

    # hot path

    def observe(
        self, tenant: str, conn_id: str, shared: bool, records: list[Any], t_recv: float
    ) -> int:
        ti = self.index.get(tenant)
        if ti is None or not ti.by_signal:
            return 0
        by = ti.by_signal
        geo = ti.geo_signals
        added = 0
        for rec in records:
            kind = rec.kind
            if kind == "event":
                rules = by.get(f"event:{rec.event_name}")
                if rules:
                    added += self._add(
                        ti,
                        rules,
                        rec,
                        f"event:{rec.event_name}",
                        1,
                        rec.ts,
                        shared,
                        conn_id,
                        t_recv,
                        None,
                    )
                continue
            if kind not in ("data", "birth") or not rec.metrics:
                continue
            g, n, d = rec.group, rec.node, rec.device or ""
            ts0 = rec.ts or int(t_recv * 1000)
            vals = None
            if geo:
                for m in rec.metrics:
                    if m.name in geo and not m.historical:
                        if vals is None:
                            vals = {}
                        vals[m.name] = m.value
                        self.coords[(tenant, g, n, d, m.name)] = m.value
            done_geo: set[str] | None = None
            for m in rec.metrics:
                rules = by.get(m.name)
                if not rules or m.historical:
                    continue
                for r in rules:
                    if not r.matches(g, n, d, ti.facts):
                        continue
                    if r.cond.kind == "geofence":
                        done_geo = done_geo or set()
                        if r.id in done_geo:
                            continue
                        done_geo.add(r.id)
                        c = r.cond
                        extra = {
                            "x": (vals or {}).get(
                                c.x_signal,
                                self.coords.get((tenant, g, n, d, c.x_signal)),
                            ),
                            "y": (vals or {}).get(
                                c.y_signal,
                                self.coords.get((tenant, g, n, d, c.y_signal)),
                            ),
                        }
                    else:
                        extra = None
                    self._push(
                        Item(
                            r,
                            g,
                            n,
                            d,
                            Sample(m.value, int(m.ts or ts0), m.name, extra or {}),
                            shared,
                            conn_id,
                            t_recv,
                        )
                    )
                    added += 1
        return added

    def _add(
        self, ti, rules, rec, sig, value, ts, shared, conn_id, t_recv, extra
    ) -> int:
        g, n, d = rec.group, rec.node, rec.device or ""
        k = 0
        for r in rules:
            if r.matches(g, n, d, ti.facts):
                self._push(
                    Item(
                        r,
                        g,
                        n,
                        d,
                        Sample(value, int(ts or t_recv * 1000), sig, extra or {}),
                        shared,
                        conn_id,
                        t_recv,
                    )
                )
                k += 1
        return k

    def _push(self, it: Item) -> None:
        if len(self.queue) >= QUEUE_MAX:
            self.queue.popleft()
            self.stats["dropped"] += 1
        self.queue.append(it)
        self.stats["queued"] += 1

    # the worker side

    async def drain(
        self,
        coords: Callable[[list[Item]], Awaitable[None]] | None = None,
        forward: Callable[[list[Item]], Awaitable[None]] | None = None,
    ) -> int:
        """Evaluate queued samples here, or hand a pool workspace's samples to forward."""
        n = 0
        while self.queue:
            items = [
                self.queue.popleft() for _ in range(min(len(self.queue), DRAIN_MAX))
            ]
            if coords is not None:
                await coords(items)
            if (
                forward is not None
                and self.pool_alive
                and (self.modes or self.default_mode == "pool")
            ):
                away = [it for it in items if self.mode(it.rule.tenant) == "pool"]
                if away:
                    await forward(away)
                    self.forwarded += len(away)
                    items = [it for it in items if self.mode(it.rule.tenant) != "pool"]
            if items:
                await self.process(items)
            n += len(items)
            await asyncio.sleep(0)
        return n

    def _mem_state(self, key: tuple[str, str]) -> dict[str, Any]:
        st = self.mem.get(key)
        if st is None:
            st = self.mem[key] = {}
            if len(self.mem) > MEM_MAX:
                for _ in range(MEM_MAX // 10):
                    self.mem.popitem(last=False)
        else:
            self.mem.move_to_end(key)
        return st

    async def process(self, items: list[Item]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str, str], list[Item]] = {}
        for it in items:
            groups.setdefault(
                (it.rule.tenant, it.rule.id, akey(it.g, it.n, it.d)), []
            ).append(it)
        outs: list[tuple[Item, Outcome]] = []
        pending: dict[tuple[str, str, str], list[Item]] = {}
        for key, its in groups.items():
            if its[0].shared:
                pending[key] = its
                continue
            st = self._mem_state((key[1], key[2]))
            for it in its:
                o = step(it.rule.cond, st, it.sample, it.rule.cooldown_ms)
                if o.fired or o.cleared or o.suppressed:
                    outs.append((it, o))
        tries = 0
        while pending and tries < CAS_TRIES:
            tries += 1
            if tries > 1:
                self.stats["cas_retry"] += len(pending)
            keys = list(pending)
            raws = await self.shared.load(keys)
            staged = []
            for key, raw in zip(keys, raws):
                try:
                    st = json.loads(raw) if raw else {}
                except ValueError:
                    st = {}
                got = []
                for it in pending[key]:
                    o = step(it.rule.cond, st, it.sample, it.rule.cooldown_ms)
                    if o.fired or o.cleared or o.suppressed:
                        got.append((it, o))
                staged.append(
                    (key, raw or "", json.dumps(st, separators=(",", ":")), got)
                )
            oks = await self.shared.cas(
                [(k[0], k[1], k[2], old, new) for k, old, new, _ in staged]
            )
            nxt = {}
            for (key, _, _, got), ok in zip(staged, oks):
                if ok:
                    outs.extend(got)
                else:
                    nxt[key] = pending[key]
            pending = nxt
        if pending:
            self.stats["cas_failed"] += len(pending)
            logger.warning(
                "rule state kept changing under %s assets, skipped", len(pending)
            )
        return await self._decide(outs)

    async def _decide(self, outs: list[tuple[Item, Outcome]]) -> list[dict[str, Any]]:
        cands = []
        for it, o in outs:
            if o.suppressed:
                self.stats["suppressed"] += 1
            else:
                cands.append((it, o))
        if not cands:
            return []
        res = await self.guard.admit(
            [
                (
                    it.rule.tenant,
                    it.rule.id,
                    akey(it.g, it.n, it.d),
                    it.sample.ts,
                    "fire" if o.fired else "clear",
                    it.rule.cooldown_ms if o.fired else 0,
                )
                for it, o in cands
            ]
        )
        docs = []
        now = time.time()
        for (it, o), r in zip(cands, res):
            if r == 1:
                docs.append(self.doc(it, o))
                self.stats["fired" if o.fired else "cleared"] += 1
                self.lag.append((now - it.t_recv) * 1000.0)
            elif r == 0:
                self.stats["duplicate"] += 1
            elif r == -1:
                self.stats["suppressed"] += 1
            else:
                self.stats["flood"] += 1
        if docs:
            await self.emit(docs)
        return docs

    def doc(self, it: Item, o: Outcome) -> dict[str, Any]:
        r = it.rule
        ti = self.index.get(r.tenant)
        facts = ti.facts if ti else AssetFacts()
        asset = facts.name(it.g, it.n, it.d)
        sig = it.sample.signal
        if r.cond.kind == "geofence":
            detail = f"{asset} {o.words}."
        elif r.cond.kind == "stale":
            detail = f"{asset} {o.words}."
        elif o.fired:
            detail = f"{sig} on {asset} {o.words}."
        else:
            detail = f"{sig} on {asset} is back to normal" + (
                f", it {o.words}." if o.words else "."
            )
        return {
            "type": "fired" if o.fired else "cleared",
            "id": str(uuid.uuid4()),
            "tenant": r.tenant,
            "rule_id": r.id,
            "rule": r.name,
            "severity": r.severity,
            "group": it.g,
            "node": it.n,
            "device": it.d,
            "asset": asset,
            "signal": sig or None,
            "value": o.value,
            "detail": detail,
            "ts": it.sample.ts,
            "at": int(time.time() * 1000),
            "connection_id": it.conn_id,
        }

    # stale rules

    def stale_targets(
        self, only: Callable[[str], bool] | None = None
    ) -> list[tuple[Compiled, list[tuple[str, str, str]]]]:
        """Rules and the keys they read. Asset scopes with any part read the asset as a whole."""
        out = []
        for t, ti in self.index.items():
            if only is not None and not only(t):
                continue
            for r in ti.stale:
                s = r.scope
                if s.get("kind") == "asset":
                    dev = s.get("device", "*")
                    keys = [(s["group"], s["node"], "" if dev == "*" else dev)]
                else:
                    keys = ti.facts.keys_where(
                        s.get("kind"),
                        s.get("type") or s.get("tag"),
                        s.get("group") or "",
                    )
                out.append((r, keys))
        return out

    async def sweep(
        self,
        read: Callable[[list[tuple[str, str, str, str, str]]], Awaitable[list[Any]]],
        only: Callable[[str], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """read takes (tenant, g, n, d, signal) and returns (age_ms, offline_at) or None per key."""
        targets = self.stale_targets(only)
        asks = []
        for r, keys in targets:
            for g, n, d in keys:
                asks.append((r, g, n, d))
        if not asks:
            return []
        ages = await read([(r.tenant, g, n, d, r.cond.signal) for r, g, n, d in asks])
        now_ms = int(time.time() * 1000)
        items = []
        for (r, g, n, d), got in zip(asks, ages):
            if not got:
                continue
            age_ms, offline_at = got
            extra = {"age_ms": age_ms}
            if offline_at:
                extra["offline_words"] = (
                    f", it went offline at {time.strftime('%H:%M:%S', time.gmtime(offline_at / 1000))} UTC"
                )
            items.append(
                Item(
                    r,
                    g,
                    n,
                    d,
                    Sample(None, now_ms, r.cond.signal, extra),
                    True,
                    "",
                    time.time(),
                )
            )
        return await self.process(items)

    def health(self) -> dict[str, Any]:
        lag = sorted(self.lag)
        return {
            **self.stats,
            "backlog": len(self.queue),
            "rules": sum(ti.count for ti in self.index.values()),
            "tenants": len(self.index),
            "memory_states": len(self.mem),
            "forwarded": self.forwarded,
            "lag_p50_ms": round(lag[len(lag) // 2], 2) if lag else None,
            "lag_p99_ms": (
                round(lag[min(len(lag) - 1, int(len(lag) * 0.99))], 2) if lag else None
            ),
        }


def _pct(v: list[float], p: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def parse_age(raw_metric: str | None, last_seen: str | None, now_ms: int) -> int | None:
    if raw_metric:
        try:
            ts = int(json.loads(raw_metric).get("ts") or 0)
        except (TypeError, ValueError):
            ts = 0
        return now_ms - ts if ts else None
    if last_seen:
        ts = K.as_int(last_seen)
        return now_ms - ts if ts else None
    return None


# shared by the ingest side and the rules pool


async def load_rows(session: Any) -> tuple[list[dict], list[dict], str, dict[str, str]]:
    """Enabled rules, the asset facts, the default mode and each workspace's override."""
    from sqlalchemy import select

    from app.core.platform_settings import get_setting
    from models.telemetry_rules import TelemetryAsset, TelemetryRule
    from models.tenant import Tenant

    async with session() as db:
        rules = (
            (
                await db.execute(
                    select(TelemetryRule).where(TelemetryRule.enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        assets = (
            (
                await db.execute(
                    select(
                        TelemetryAsset.tenant_id,
                        TelemetryAsset.grp,
                        TelemetryAsset.node,
                        TelemetryAsset.device,
                        TelemetryAsset.display_name,
                        TelemetryAsset.asset_type,
                        TelemetryAsset.tags,
                    )
                )
            )
            .mappings()
            .all()
        )
        tenants = {r.tenant_id for r in rules}
        overrides: dict[str, str] = {}
        if tenants:
            for tid, st in (
                await db.execute(
                    select(Tenant.id, Tenant.settings).where(Tenant.id.in_(tenants))
                )
            ).all():
                m = (st or {}).get(MODE_OVERRIDE)
                if m in MODES:
                    overrides[str(tid)] = m
    try:
        default = (await get_setting(MODE_SETTING, "inprocess")).strip().lower()
    except Exception:  # noqa: BLE001
        default = "inprocess"
    rows = [
        {
            "id": r.id,
            "tenant_id": r.tenant_id,
            "name": r.name,
            "severity": r.severity,
            "cooldown_s": r.cooldown_s,
            "scope": r.scope,
            "condition": r.condition,
            "actions": r.actions,
            "created_by": r.created_by,
            "team_id": r.team_id,
        }
        for r in rules
    ]
    mode = default if default in MODES else "inprocess"
    return rows, [dict(a) for a in assets], mode, overrides


async def pool_alive(r: Any) -> int:
    """Pool replicas that sent a heartbeat in the last few seconds."""
    now = int(time.time() * 1000)
    return int(await r.zcount(POOL_REPLICAS, now - POOL_ALIVE_MS, "+inf") or 0)


async def fill_coords(r: Any, items: list[Item]) -> None:
    """A geofence partner coordinate not seen with this sample is read from the latest values."""
    need = [
        it
        for it in items
        if it.rule.cond.kind == "geofence"
        and (it.sample.extra.get("x") is None or it.sample.extra.get("y") is None)
    ]
    if not need:
        return
    pipe = r.pipeline(transaction=False)
    for it in need:
        c = it.rule.cond
        pipe.hmget(
            K.device(it.rule.tenant, it.g, it.n, it.d),
            K.metric_field(c.x_signal),
            K.metric_field(c.y_signal),
        )
    for it, (xr, yr) in zip(need, await pipe.execute()):
        for k, raw in (("x", xr), ("y", yr)):
            if it.sample.extra.get(k) is None and raw:
                try:
                    it.sample.extra[k] = json.loads(raw).get("v")
                except (TypeError, ValueError):
                    pass


async def read_ages(r: Any, asks: list[tuple[str, str, str, str, str]]) -> list[Any]:
    """How long each asset or signal has been silent, from the last-seen times in Redis."""
    pipe = r.pipeline(transaction=False)
    for t, g, n, d, sig in asks:
        pipe.hmget(
            K.device(t, g, n, d),
            "_last_seen",
            "_online",
            "_offline_at",
            K.metric_field(sig) if sig else "_none",
        )
    rows = await pipe.execute()
    # a signal on an asset as a whole lives on one of its parts
    missing = [
        i
        for i, (ask, row) in enumerate(zip(asks, rows))
        if ask[4] and not ask[3] and not row[3]
    ]
    extra: dict[int, list[str | None]] = {}
    if missing:
        p2 = r.pipeline(transaction=False)
        for i in missing:
            t, g, n, _, _ = asks[i]
            p2.smembers(K.node_devices(t, g, n))
        devs = await p2.execute()
        p3 = r.pipeline(transaction=False)
        plan = []
        for i, ds in zip(missing, devs):
            t, g, n, _, sig = asks[i]
            for d in sorted(x for x in (ds or []) if x):
                p3.hget(K.device(t, g, n, d), K.metric_field(sig))
                plan.append(i)
        if plan:
            for i, raw in zip(plan, await p3.execute()):
                if raw:
                    extra.setdefault(i, []).append(raw)
    now_ms = int(time.time() * 1000)
    out = []
    for i, (ask, (seen, online, off_at, raw)) in enumerate(zip(asks, rows)):
        if ask[4]:
            cands = [raw] if raw else extra.get(i, [])
            ages = [
                a for a in (parse_age(c, None, now_ms) for c in cands) if a is not None
            ]
            age = min(ages) if ages else None
        else:
            age = parse_age(None, seen, now_ms)
        if age is None:
            out.append(None)
            continue
        out.append((age, K.as_int(off_at) if online == "0" and off_at else None))
    return out


async def publish_fired(
    r: Any, docs: list[dict[str, Any]]
) -> list[tuple[str, str, dict]]:
    """Firings onto the runner's stream. Returns the telemetry.rule_fired events to record."""
    pipe = r.pipeline(transaction=False)
    for d in docs:
        pipe.xadd(
            STREAM,
            {"doc": json.dumps(d, default=str)},
            maxlen=STREAM_MAX,
            approximate=True,
        )
    await pipe.execute()
    events = []
    for d in docs:
        if d["type"] != "fired":
            continue
        payload = {
            k: d[k]
            for k in (
                "rule_id",
                "rule",
                "severity",
                "group",
                "node",
                "device",
                "asset",
                "signal",
                "value",
                "detail",
                "at",
            )
        }
        payload["firing_id"] = d["id"]
        events.append((d["tenant"], "telemetry.rule_fired", payload))
    return events


class RuleEvaluator:
    """The ingest side: evaluates in process, or hands a pool workspace's samples to the pool."""

    name = "signal_rules"

    def __init__(self) -> None:
        self.engine: Engine | None = None
        self.host: Any = None
        self.tasks: list[asyncio.Task] = []
        self.wake = asyncio.Event()
        self.version: str | None = None
        self.loaded_at = 0.0
        self.obs_ns: deque[int] = deque(maxlen=20_000)
        self.obs_calls = 0
        # worker time per evaluated sample, off the hot path
        self.busy_ns = 0
        self.busy_samples = 0
        self.pool_replicas = 0

    async def start(self, host: Any) -> None:
        self.host = host
        self.wake = asyncio.Event()
        self.engine = Engine(RedisShared(host.r), RedisGuard(host.r), self._emit)
        try:
            await self.reload()
        except Exception as exc:  # noqa: BLE001
            logger.warning("rules did not load yet: %s", exc)
        for fn in (self._worker, self._loader, self._sweeper, self._health):
            self.tasks.append(asyncio.create_task(fn()))

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

    def observe(self, conn: Any, records: list[Any], t_recv: float) -> None:
        e = self.engine
        if e is None or conn.tenant not in e.index:
            return
        t0 = time.perf_counter_ns()
        try:
            n = e.observe(conn.tenant, conn.id, bool(conn.shared), records, t_recv)
        except Exception as exc:  # noqa: BLE001
            logger.debug("rule observe failed: %s", exc)
            return
        self.obs_ns.append(time.perf_counter_ns() - t0)
        self.obs_calls += 1
        if n:
            self.wake.set()

    async def reload(self) -> None:
        rows, assets, default, overrides = await load_rows(self.host.session)
        self.engine.load(rows, assets)
        self.engine.default_mode = default
        self.engine.modes = overrides
        self.loaded_at = time.monotonic()

    async def _loader(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                self.pool_replicas = await pool_alive(self.host.r)
                self.engine.pool_alive = self.pool_replicas > 0
                v = await self.host.r.get(VERSION_KEY)
                if v != self.version or time.monotonic() - self.loaded_at > 60:
                    await self.reload()
                    self.version = v
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("rule reload failed: %s", exc)
                await asyncio.sleep(5)

    async def _coords(self, items: list[Item]) -> None:
        await fill_coords(self.host.r, items)

    async def _forward(self, items: list[Item]) -> None:
        pipe = self.host.r.pipeline(transaction=False)
        for shard, entries in pack(items).items():
            for fields in entries:
                pipe.xadd(
                    in_stream(shard), fields, maxlen=IN_STREAM_MAX, approximate=True
                )
        await pipe.execute()

    async def _worker(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            try:
                t0 = time.perf_counter_ns()
                n = await self.engine.drain(self._coords, self._forward)
                if n:
                    self.busy_ns += time.perf_counter_ns() - t0
                    self.busy_samples += n
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("rule evaluation failed: %s", exc)
                await asyncio.sleep(0.5)

    async def _read_ages(self, asks: list[tuple[str, str, str, str, str]]) -> list[Any]:
        return await read_ages(self.host.r, asks)

    async def _sweeper(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            try:
                e = self.engine
                here = [
                    t for t, ti in e.index.items() if ti.stale and e.mode(t) != "pool"
                ]
                if not here:
                    continue
                if await self.host._hold("rules-stale", 3000):
                    await e.sweep(self._read_ages, only=lambda t: e.mode(t) != "pool")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("stale sweep failed: %s", exc)

    async def _emit(self, docs: list[dict[str, Any]]) -> None:
        for ev in await publish_fired(self.host.r, docs):
            try:
                self.host.events.append(ev)
            except Exception:  # noqa: BLE001
                pass

    def health(self) -> dict[str, Any]:
        doc = self.engine.health() if self.engine else {}
        obs = [x / 1000.0 for x in self.obs_ns]
        doc.update(
            {
                "kind": "ingest",
                "mode": self.engine.default_mode if self.engine else "inprocess",
                "pool_replicas": self.pool_replicas,
                "observe_calls": self.obs_calls,
                "observe_us_p50": round(_pct(obs, 50), 2) if obs else None,
                "observe_us_p99": round(_pct(obs, 99), 2) if obs else None,
                "observe_us_max": round(max(obs), 2) if obs else None,
                "evaluate_us_per_sample": (
                    round(self.busy_ns / self.busy_samples / 1000.0, 2)
                    if self.busy_samples
                    else None
                ),
                "at": int(time.time() * 1000),
            }
        )
        return doc

    async def _health(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            try:
                rep = getattr(self.host, "replica", "ingest")
                await self.host.r.hset(HEALTH_KEY, rep, json.dumps(self.health()))
                await self.host.r.expire(HEALTH_KEY, 60)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("rule health write failed: %s", exc)


__all__ = [
    "Engine",
    "Item",
    "MemoryGuard",
    "MemoryShared",
    "RedisGuard",
    "RedisShared",
    "RuleEvaluator",
    "SHARDS",
    "STREAM",
    "fill_coords",
    "in_stream",
    "load_rows",
    "pack",
    "pool_alive",
    "publish_fired",
    "read_ages",
    "shard_of",
    "unpack",
    "VERSION_KEY",
    "HEALTH_KEY",
    "fmt",
]
