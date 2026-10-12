"""The store stage: Records from any decoder into latest values, history, frames, events and alerts.

The store never talks to the network itself. It reads through an injected
lookup and writes into a Batch that the ingest flushes in one Redis pipeline.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.telemetry import keys as K
from app.telemetry.decoders.base import Metric, Record

# sources without births go offline after silence, by default ten of their own gaps
OFFLINE_FLOOR_S = 60
OFFLINE_CAP_S = 900
OFFLINE_GAPS = 9
# per source, the first few offline events in a minute go one by one, the rest as one
OFFLINE_EACH = 5
OFFLINE_WINDOW_S = 60

EVENT_RING = 500
SKEW_FLAG_MS = 5000
LATEST_CACHE_MAX = 500_000
_NUMERIC_TYPES = ("number", "bool")


@dataclass(frozen=True)
class ConnInfo:
    id: str
    tenant: str
    name: str = ""
    shared: bool = False
    team_id: str | None = None
    transport: str = "mqtt"
    offline_after_s: int = 0


@dataclass
class DevState:
    online: bool = False
    metric_count: int = 0
    conn: str = ""
    checked: float = 0.0


@dataclass
class Batch:
    hset: dict[str, dict[str, str]] = field(default_factory=lambda: defaultdict(dict))
    hdel: list[tuple[str, list[str]]] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    sadd: list[tuple[str, str]] = field(default_factory=list)
    index: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    frames: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    rings: dict[str, tuple[list[str], int]] = field(default_factory=dict)
    rate: dict[tuple[str, int], dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    stats: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int))
    )
    tenant_msgs: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    alerts: list[tuple[bool, dict[str, Any]]] = field(default_factory=list)
    publish: list[tuple[str, str]] = field(default_factory=list)
    latencies: list[tuple[str, float, int]] = field(default_factory=list)
    # (tenant, group, node, seq, connection id) from sources that number their batches
    seqs: list[tuple[str, str, str, int, str]] = field(default_factory=list)
    history: list[tuple[Any, ...]] = field(default_factory=list)
    messages: int = 0

    def ring(self, key: str, item: str, cap: int) -> None:
        items, _ = self.rings.get(key, ([], cap))
        items.append(item)
        self.rings[key] = (items, cap)


Lookup = Callable[..., Awaitable[Any]]


def _now_ms() -> int:
    return int(time.time() * 1000)


def num_txt(value: Any, kind: str) -> tuple[float | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, bool):
        return (1.0 if value else 0.0), None
    if isinstance(value, (int, float)) and kind in _NUMERIC_TYPES:
        f = float(value)
        return (f if f == f else None), None
    if isinstance(value, str):
        return None, value[:2000]
    return None, json.dumps(value, default=str)[:2000]


class Store:
    """One per ingest replica, or one for an API-side replay."""

    def __init__(self, lookup: Lookup, *, history_interval_ms: int = 1000) -> None:
        self.lookup = lookup
        self.history_interval_ms = history_interval_ms
        self.devices: dict[tuple[str, str, str, str], DevState] = {}
        self.names: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
        self.sse_dirty: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = (
            defaultdict(dict)
        )
        self.sse_conn: dict[tuple[str, str, str, str], str] = {}
        self.feed_dirty: dict[tuple[str, str, str, str, str], tuple[Any, int]] = {}
        self.seen_dirty: dict[tuple[str, str, str, str], tuple[int, str]] = {}
        self.hist_last: dict[tuple[str, str, str, str, str], int] = {}
        self.latest_ts: dict[tuple[str, str, str, str, str], int] = {}
        self.signals_seen: dict[tuple[str, str], dict[str, Any]] = {}
        self.signals_touched: dict[tuple[str, str], set[str]] = defaultdict(set)
        self.skew: dict[str, float] = {}
        self.last_data: dict[tuple[str, str, str, str], tuple[float, ConnInfo]] = {}
        self.throttled: dict[str, int] = {}
        self.device_cap: dict[str, int] = {}
        self.device_count: dict[str, int] = {}
        self.counted: set[tuple[str, str, str, str]] = set()
        self.prev_at: dict[tuple[str, str, str, str], float] = {}
        self.gaps: dict[tuple[str, str, str, str], deque] = {}
        self.default_offline_s = 0
        self.offline_burst: dict[tuple[str, str], dict[str, Any]] = {}

    # entry points

    def admit(self, conn: ConnInfo, t_recv: float, b: Batch) -> bool:
        """Counts the message, or refuses it when the workspace is over its rate this second."""
        t = conn.tenant
        if self.throttled.get(t) == int(t_recv):
            b.stats[t]["throttled"] += 1
            return False
        b.messages += 1
        b.tenant_msgs[t] += 1
        rk = b.rate[(t, int(t_recv))]
        rk["_total"] += 1
        rk[f"_conn/{conn.id}"] += 1
        return True

    async def apply(
        self, conn: ConnInfo, records: list[Record], t_recv: float, b: Batch
    ) -> None:
        t = conn.tenant
        sec = int(t_recv)
        nodes_counted: set[tuple[str, str]] = set()
        devs_counted: set[tuple[str, str, str]] = set()
        first_ts = None
        for rec in records:
            if rec.kind == "state":
                host = str(rec.meta.get("host") or "")
                b.hset[K.host_state(t, host)]["state"] = str(
                    rec.meta.get("state") or ""
                )
                continue
            g, n, d = rec.group, rec.node, rec.device or ""
            if not g or not n:
                b.stats[t]["bad_records"] += 1
                continue
            rk = b.rate[(t, sec)]
            if (g, n) not in nodes_counted:
                nodes_counted.add((g, n))
                rk[f"{g}/{n}"] += 1
            if d and (g, n, d) not in devs_counted:
                devs_counted.add((g, n, d))
                rk[K.index_field(g, n, d)] += 1
            if rec.metrics:
                rk[f"r:{g}/{n}"] += len(rec.metrics)
                if d:
                    rk[f"r:{K.index_field(g, n, d)}"] += len(rec.metrics)
            if rec.ts is not None and rec.kind != "death":
                first_ts = first_ts or rec.ts
                self._skew(conn, t_recv * 1000 - rec.ts)
            gap = rec.meta.get("seq_gap")
            if gap:
                self._seq_gap(conn, g, n, gap, b)
            kind = rec.kind
            if kind == "birth":
                await self._birth(conn, rec, b)
            elif kind == "data":
                if rec.metrics or not rec.meta:
                    await self._data(conn, rec, b)
                if rec.seq is not None and not rec.meta.get("session"):
                    b.seqs.append((t, g, n, int(rec.seq), conn.id))
            elif kind == "death":
                # an NDEATH is the will set at connect, its timestamp is the connect time
                when = int(t_recv * 1000) if t_recv else _now_ms()
                if rec.meta.get("cascade"):
                    await self._node_death(conn, g, n, when, b)
                else:
                    await self._death(conn, g, n, d, when, b)
            elif kind == "frame":
                self._frames(conn, g, n, rec, b)
            elif kind == "event":
                await self._event(conn, rec, b)
        b.latencies.append((t, t_recv, first_ts or int(t_recv * 1000)))

    # pieces

    def _skew(self, conn: ConnInfo, ms: float) -> None:
        cur = self.skew.get(conn.id)
        self.skew[conn.id] = ms if cur is None else cur * 0.95 + ms * 0.05

    def _seq_gap(
        self, conn: ConnInfo, g: str, n: str, gap: dict[str, Any], b: Batch
    ) -> None:
        t = conn.tenant
        b.stats[t]["seq_gaps"] += 1
        b.index.append((t, K.index_field(g, n, ""), {"inc": {"seq_gaps": 1}}))
        b.hset[K.device(t, g, n, "")]["_seq_gaps"] = str(gap.get("seq_gaps", 1))
        b.events.append(
            (
                t,
                "telemetry.seq_gap",
                {"group": g, "node": n, **gap, "connection_id": conn.id},
            )
        )

    async def _is_online(
        self, conn: ConnInfo, t: str, g: str, n: str, d: str, fresh: bool = False
    ) -> bool:
        ds = self.devices.get((t, g, n, d))
        now = time.monotonic()
        # a shared source is heard by several replicas, so another may have marked it offline
        recent = now - ds.checked < 2.0 if ds is not None else False
        if ds is not None and not fresh and (recent or (ds.online and not conn.shared)):
            return ds.online
        online = bool(await self.lookup("online", t, g, n, d))
        if ds is None:
            ds = self.devices[(t, g, n, d)] = DevState(conn=conn.id)
        ds.online = online
        ds.checked = now
        return online

    async def _under_cap(self, t: str, g: str, n: str, d: str) -> bool:
        cap = self.device_cap.get(t)
        if not cap or (t, g, n, d) in self.counted:
            return True
        if await self.lookup("known", t, g, n, d):
            return True
        return self.device_count.get(t, 0) < cap

    async def _come_online(
        self,
        conn: ConnInfo,
        t: str,
        g: str,
        n: str,
        d: str,
        ts: int,
        b: Batch,
        count: int | None,
    ) -> bool:
        """Mark a device online, its birth or first sight. False when the device limit refused it."""
        if not await self._under_cap(t, g, n, d):
            b.stats[t]["devices_refused"] += 1
            b.stats[t]["_cap_hit"] = 1
            return False
        was_online = await self._is_online(conn, t, g, n, d)
        if (t, g, n, d) not in self.counted:
            self.counted.add((t, g, n, d))
            if not await self.lookup("known", t, g, n, d):
                self.device_count[t] = self.device_count.get(t, 0) + 1
        h = b.hset[K.device(t, g, n, d)]
        h.update(
            {
                "_online": "1",
                "_birth_at": str(ts),
                "_last_seen": str(_now_ms()),
                "_offline_at": "",
                "_conn": conn.id,
                # sources without births flag each signal stale on its own age
                "_stale_ms": (
                    str(conn.offline_after_s * 1000)
                    if count is None and conn.offline_after_s
                    else ""
                ),
            }
        )
        b.sadd.append((K.node_devices(t, g, n), d))
        ds = self.devices.setdefault((t, g, n, d), DevState(conn=conn.id))
        ds.online, ds.conn, ds.checked = True, conn.id, time.monotonic()
        if count is not None:
            ds.metric_count = count
        summary = {
            "group": g,
            "node": n,
            "device": d,
            "online": True,
            "birth_at": ts,
            "offline_at": None,
            "connection_id": conn.id,
            "team_id": conn.team_id,
            "max": {"last_seen": _now_ms()},
        }
        if count is not None:
            summary["metric_count"] = count
        b.index.append((t, K.index_field(g, n, d), summary))
        b.publish.append((K.channel(t, g, n), _device_msg(summary)))
        if not was_online:
            b.events.append((t, "telemetry.device_online", _event(conn, g, n, d)))
            b.alerts.append((False, _alert(conn, g, n, d, ts)))
        return True

    async def _birth(self, conn: ConnInfo, rec: Record, b: Batch) -> None:
        t, g, n, d = conn.tenant, rec.group, rec.node, rec.device or ""
        ts = rec.ts or _now_ms()
        meta = rec.meta
        if not await self._come_online(conn, t, g, n, d, ts, b, len(rec.metrics)):
            return
        if meta.get("reset_aliases"):
            b.delete.append(K.aliases(t, g, n))
        for alias, spec in (meta.get("aliases") or {}).items():
            b.hset[K.aliases(t, g, n)][str(alias)] = json.dumps(spec)
        if meta.get("bdseq") is not None:
            b.hset[K.device(t, g, n, d)]["_bdseq"] = str(meta["bdseq"])
        if meta.get("replace_metrics"):
            # a birth declares the whole set, anything else is retired, its history stays
            stale = set(await self.lookup("metric_fields", t, g, n, d) or ())
            stale -= {K.metric_field(m.name) for m in rec.metrics}
            if stale:
                b.hdel.append((K.device(t, g, n, d), sorted(stale)))
                for field in sorted(stale):
                    name = field[2:]
                    b.hset[K.retired(t, conn.id)][f"{g}/{n}/{d}/{name}"] = str(ts)
                    for key in [
                        k
                        for k in self.latest_ts
                        if k[:4] == (t, g, n, d) and k[4] == name
                    ]:
                        self.latest_ts.pop(key, None)
        for alias in meta.get("drop_aliases") or ():
            b.hdel.append((K.aliases(t, g, n), [str(alias)]))
        self.names[(t, g, n, d)] = {m.name for m in rec.metrics}
        for m in rec.metrics:
            self._metric(conn, t, g, n, d, m, ts, b)

    async def _data(self, conn: ConnInfo, rec: Record, b: Batch) -> None:
        t, g, n, d = conn.tenant, rec.group, rec.node, rec.device or ""
        ts = rec.ts or _now_ms()
        if not rec.meta.get("session"):
            # sources without births are online while they send
            if d and not await self._is_online(conn, t, g, n, ""):
                await self._come_online(conn, t, g, n, "", ts, b, None)
            if not await self._is_online(conn, t, g, n, d):
                if not await self._come_online(conn, t, g, n, d, ts, b, None):
                    return
            now = time.time()
            self.last_data[(t, g, n, d)] = (now, conn)
            self._arrival((t, g, n, d), now)
            if d:
                self.last_data[(t, g, n, "")] = (now, conn)
                self._arrival((t, g, n, ""), now)
        names = self.names[(t, g, n, d)]
        before = len(names)
        for m in rec.metrics:
            names.add(m.name)
            self._metric(conn, t, g, n, d, m, ts, b)
        if len(names) != before and not rec.meta.get("session"):
            b.index.append((t, K.index_field(g, n, d), {"metric_count": len(names)}))
        self.seen_dirty[(t, g, n, d)] = (_now_ms(), conn.id)

    def _metric(
        self,
        conn: ConnInfo,
        t: str,
        g: str,
        n: str,
        d: str,
        m: Metric,
        ts: int,
        b: Batch,
    ) -> None:
        mts = int(m.ts or ts)
        tname = m.source_type or m.type
        hk = (t, g, n, d, m.name)
        latest = not m.historical
        last = self.latest_ts.get(hk)
        if latest and last is not None and mts < last:
            # late data goes to history but never moves the latest value back
            latest = False
            b.stats[t]["late"] += 1
        if latest:
            if len(self.latest_ts) > LATEST_CACHE_MAX:
                self.latest_ts.clear()
            self.latest_ts[hk] = mts
            b.hset[K.device(t, g, n, d)][K.metric_field(m.name)] = K.pack_metric(
                m.value, tname, mts, m.quality, m.unit
            )
            dk = (t, g, n, d)
            row = {
                "name": m.name,
                "value": m.value,
                "type": tname,
                "ts": mts,
                "quality": m.quality,
            }
            if m.unit:
                row["unit"] = m.unit
            self.sse_dirty[dk][m.name] = row
            self.sse_conn[dk] = conn.id
            self.feed_dirty[(t, g, n, d, m.name)] = (m.value, mts)
        sk = (t, conn.id)
        seen = self.signals_seen.get(sk)
        if seen is None:
            seen = self.signals_seen[sk] = {}
        if m.name not in seen:
            seen[m.name] = {"first_seen": _now_ms(), "type": m.type, "unit": m.unit}
            b.hset[K.signals(t, conn.id)][m.name] = json.dumps(
                {**seen[m.name], "last_seen": _now_ms(), "example": f"{g}/{n}/{d}"},
                default=str,
            )
        self.signals_touched[sk].add(m.name)
        last_h = self.hist_last.get(hk)
        if (
            m.historical
            or not latest
            or last_h is None
            or mts - last_h >= self.history_interval_ms
        ):
            if latest:
                self.hist_last[hk] = mts
            num, txt = num_txt(m.value, m.type)
            if num is not None or txt is not None:
                b.history.append((mts, t, g, n, d, m.name, num, txt))

    async def _death(
        self, conn: ConnInfo, g: str, n: str, d: str, ts: int, b: Batch
    ) -> None:
        t = conn.tenant
        if not await self._is_online(conn, t, g, n, d, fresh=conn.shared):
            return
        self._offline(conn, t, g, n, d, ts, b)
        b.events.append((t, "telemetry.device_offline", _event(conn, g, n, d)))
        b.alerts.append((True, _alert(conn, g, n, d, ts)))

    def _offline(
        self, conn: ConnInfo, t: str, g: str, n: str, d: str, ts: int, b: Batch
    ) -> None:
        ds = self.devices.setdefault((t, g, n, d), DevState(conn=conn.id))
        ds.online = False
        ds.checked = time.monotonic()
        self.last_data.pop((t, g, n, d), None)
        b.hset[K.device(t, g, n, d)].update(
            {"_online": "0", "_offline_at": str(ts), "_last_seen": str(_now_ms())}
        )
        summary = {
            "group": g,
            "node": n,
            "device": d,
            "online": False,
            "offline_at": ts,
            "connection_id": conn.id,
            "team_id": conn.team_id,
        }
        b.index.append((t, K.index_field(g, n, d), summary))
        b.publish.append((K.channel(t, g, n), _device_msg(summary)))

    async def _node_death(
        self, conn: ConnInfo, g: str, n: str, ts: int, b: Batch
    ) -> None:
        t = conn.tenant
        if not await self._is_online(conn, t, g, n, "", fresh=conn.shared):
            return
        devices = await self.lookup("node_devices", t, g, n) or []
        gone = []
        for d in sorted(set(devices) | {""}):
            if d and not await self._is_online(conn, t, g, n, d, fresh=conn.shared):
                continue
            self._offline(conn, t, g, n, d, ts, b)
            if d:
                gone.append(d)
        ev = _event(conn, g, n, "")
        ev["devices"] = gone
        b.events.append((t, "telemetry.device_offline", ev))
        b.alerts.append((True, _alert(conn, g, n, "", ts, gone)))

    def _frames(self, conn: ConnInfo, g: str, n: str, rec: Record, b: Batch) -> None:
        t = conn.tenant
        out = b.frames[K.frames(t, g, n)]
        for f in rec.frames:
            out.append(json.dumps(f, separators=(",", ":")))
        b.stats[t]["frames"] += len(rec.frames)

    async def _event(self, conn: ConnInfo, rec: Record, b: Batch) -> None:
        t, g, n, d = conn.tenant, rec.group, rec.node, rec.device or ""
        ts = rec.ts or _now_ms()
        if not await self._is_online(conn, t, g, n, d):
            if not await self._come_online(conn, t, g, n, d, ts, b, None):
                return
        doc = {
            "ts": ts,
            "group": g,
            "node": n,
            "device": d,
            "name": rec.event_name,
            "event": rec.event,
            "connection_id": conn.id,
        }
        raw = json.dumps(doc, default=str, separators=(",", ":"))
        b.ring(K.events(t, g, n), raw, EVENT_RING)
        b.publish.append(
            (K.channel(t, g, n), json.dumps({"type": "event", **doc}, default=str))
        )
        b.stats[t]["events"] += 1
        self.seen_dirty[(t, g, n, d)] = (_now_ms(), conn.id)

    # periodic flushes, called by the ingest service

    def forget(self, t: str, items: list[tuple[str, str, str]]) -> None:
        """Drops what this replica remembers of forgotten devices, so they come back as new."""
        gone = {(t, g, n, d) for g, n, d in items}
        for key in gone:
            self.devices.pop(key, None)
            self.names.pop(key, None)
            self.last_data.pop(key, None)
            self.sse_conn.pop(key, None)
            self.seen_dirty.pop(key, None)
            self.counted.discard(key)
            self.prev_at.pop(key, None)
            self.gaps.pop(key, None)
        for cache in (self.latest_ts, self.hist_last, self.feed_dirty):
            for key in [k for k in cache if k[:4] in gone]:
                cache.pop(key, None)
        counted = sum(1 for k in gone if k[0] == t)
        if counted and t in self.device_count:
            self.device_count[t] = max(0, self.device_count[t] - counted)

    def _arrival(self, key: tuple[str, str, str, str], now: float) -> None:
        prev = self.prev_at.get(key)
        self.prev_at[key] = now
        if prev is None or now - prev < 0.05:
            return
        gaps = self.gaps.get(key)
        if gaps is None:
            gaps = self.gaps[key] = deque(maxlen=OFFLINE_GAPS)
        gaps.append(now - prev)

    def interval_s(self, key: tuple[str, str, str, str]) -> float | None:
        """The device's usual gap between messages, once there are a few."""
        gaps = self.gaps.get(key)
        if not gaps or len(gaps) < 3:
            return None
        return statistics.median(gaps)

    def offline_after(self, conn: ConnInfo, interval: float | None) -> float:
        if conn.offline_after_s:
            return float(conn.offline_after_s)
        if self.default_offline_s:
            return float(self.default_offline_s)
        if interval is None:
            return float(OFFLINE_CAP_S)
        return min(float(OFFLINE_CAP_S), max(float(OFFLINE_FLOOR_S), 10 * interval))

    def drop_connection(self, cid: str) -> None:
        for key in [k for k, (_, c) in self.last_data.items() if c.id == cid]:
            self.last_data.pop(key, None)
        for key in [k for k in self.offline_burst if k[1] == cid]:
            self.offline_burst.pop(key, None)

    def due(
        self, now: float
    ) -> list[tuple[tuple[str, str, str, str], ConnInfo, float, float]]:
        """Devices this replica has not heard from for longer than their limit."""
        out = []
        for key, (at, conn) in list(self.last_data.items()):
            limit = self.offline_after(conn, self.interval_s(key))
            if now - at > limit:
                out.append((key, conn, at, limit))
        return out

    def take_offline(
        self,
        items: list[tuple[tuple[str, str, str, str], ConnInfo, float, float]],
        now: float,
        b: Batch,
    ) -> None:
        gone: dict[tuple[str, str], list[tuple[ConnInfo, str, str, str, int]]] = (
            defaultdict(list)
        )
        for (t, g, n, d), conn, at, limit in items:
            # it went quiet at its last message plus the limit, not when this sweep noticed
            ts = int((at + limit) * 1000)
            self._offline(conn, t, g, n, d, ts, b)
            gone[(t, conn.id)].append((conn, g, n, d, ts))
        for found in gone.values():
            self.announce_offline(found, now, b)
        self.flush_offline(now, b)

    def sweep(self, now: float, b: Batch) -> None:
        """Sources without deaths go offline after a silence, set or learnt from their own pace."""
        self.take_offline(self.due(now), now, b)

    def announce_offline(
        self, items: list[tuple[ConnInfo, str, str, str, int]], now: float, b: Batch
    ) -> None:
        """One event and alert per device for the first few, then one grouped per source a minute."""
        for conn, g, n, d, ts in items:
            st = self.offline_burst.setdefault(
                (conn.tenant, conn.id),
                {"start": now, "sent": 0, "held": [], "conn": conn},
            )
            if st["sent"] < OFFLINE_EACH:
                st["sent"] += 1
                ev = _event(conn, g, n, d)
                ev["offline_at"] = ts
                b.events.append((conn.tenant, "telemetry.device_offline", ev))
                b.alerts.append((True, _alert(conn, g, n, d, ts)))
            else:
                st["held"].append(f"{g}/{n}/{d}" if d else f"{g}/{n}")
                st["first_at"] = min(st.get("first_at") or ts, ts)

    def flush_offline(self, now: float, b: Batch) -> None:
        for key, st in list(self.offline_burst.items()):
            if now - st["start"] < OFFLINE_WINDOW_S:
                continue
            held, conn = st["held"], st["conn"]
            if held:
                ev = _event(conn, "", "", "")
                first = st.get("first_at") or int(now * 1000)
                ev.update(
                    {
                        "count": len(held),
                        "devices": held[:50],
                        "grouped": True,
                        "offline_at": first,
                    }
                )
                b.events.append((conn.tenant, "telemetry.device_offline", ev))
                b.alerts.append((True, _group_alert(conn, held, first)))
                self.offline_burst[key] = {
                    "start": now,
                    "sent": OFFLINE_EACH,
                    "held": [],
                    "conn": conn,
                }
            else:
                self.offline_burst.pop(key, None)

    def take_sse(self) -> list[tuple[str, str]]:
        out = []
        for (t, g, n, d), rows in self.sse_dirty.items():
            if not rows:
                continue
            out.append(
                (
                    K.channel(t, g, n),
                    json.dumps(
                        {
                            "type": "metrics",
                            "group": g,
                            "node": n,
                            "device": d,
                            "connection_id": self.sse_conn.get((t, g, n, d)),
                            "metrics": sorted(rows.values(), key=lambda r: r["name"]),
                        },
                        default=str,
                    ),
                )
            )
        self.sse_dirty.clear()
        return out

    def take_feeds(self, now: float) -> dict[str, str]:
        out = {}
        for (t, g, n, d, name), (value, ts) in self.feed_dirty.items():
            out[K.feed(t, g, n, d, name)] = json.dumps(
                {"value": value, "fetched_at": ts / 1000.0, "ts": ts}, default=str
            )
        self.feed_dirty.clear()
        return out

    def take_seen(self) -> list[tuple[str, str, str, str, int, str]]:
        out = [(t, g, n, d, at, c) for (t, g, n, d), (at, c) in self.seen_dirty.items()]
        self.seen_dirty.clear()
        return out

    def take_signals(self) -> dict[tuple[str, str], set[str]]:
        out = dict(self.signals_touched)
        self.signals_touched = defaultdict(set)
        return out


def _device_msg(summary: dict[str, Any]) -> str:
    doc = {k: v for k, v in summary.items() if k not in ("max", "inc")}
    doc["type"] = "device"
    if "max" in summary:
        doc.update(summary["max"])
    return json.dumps(doc, default=str)


def _event(conn: ConnInfo, g: str, n: str, d: str) -> dict[str, Any]:
    return {
        "group": g,
        "node": n,
        "device": d,
        "connection_id": conn.id,
        "connection": conn.name,
        "at": _now_ms(),
    }


def _group_alert(conn: ConnInfo, held: list[str], ts: int) -> dict[str, Any]:
    name = conn.name or conn.id
    return {
        "labels": {
            "alertname": "TelemetryDevicesOffline",
            "severity": "warning",
            "tenant_id": conn.tenant,
            "group": "*",
            "node": "*",
            "device": conn.id,
            "connection": name,
        },
        "annotations": {
            "summary": f"{len(held)} devices on {name} went offline",
            "description": (
                f"{len(held)} devices on {name} stopped reporting within a minute, for example "
                + ", ".join(held[:5])
                + ". Each comes back when it reports again."
            ),
        },
        "at": ts,
        # posted once, it is not kept firing
        "once": True,
    }


def _alert(
    conn: ConnInfo,
    g: str,
    n: str,
    d: str,
    ts: int,
    devices: list[str] | None = None,
) -> dict[str, Any]:
    what = f"{n}/{d}" if d else n
    if d:
        summary = f"Part {d} of {n} went offline"
    else:
        summary = f"{n} went offline" + (
            f" with {len(devices)} parts" if devices else ""
        )
    return {
        "labels": {
            "alertname": "TelemetryDeviceOffline",
            "severity": "warning",
            "tenant_id": conn.tenant,
            "group": g,
            "node": n,
            "device": d or "-",
            "connection": conn.name or conn.id,
        },
        "annotations": {
            "summary": summary,
            "description": (
                f"{what} in group {g} stopped reporting on {conn.name or conn.id}. "
                "It comes back when it reports again."
            ),
        },
        "at": ts,
    }
