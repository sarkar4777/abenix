"""Telemetry load test, run in-cluster by scripts/telemetry-loadtest.sh.

  python -m app.telemetry.loadtest t2   4 nodes x 400 msg/s on the admin workspace's Site broker
  python -m app.telemetry.loadtest t7   50 nodes x 200 msg/s over 3 workspaces, 200 live viewers,
                                        and a replica killed half way through by the calling script

Publishes real Sparkplug B through the in-cluster broker, reads back through the
public API as a person would, and prints one JSON report on the last line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import random
import sys
import time
from typing import Any

from app.telemetry import keys as K

API = os.environ.get("LOADTEST_API", "http://abenix-api:8000").rstrip("/")
MQTT = os.environ.get("MQTT_URL", "mqtt://abenix-mosquitto:1883")
ADMIN_EMAIL = os.environ.get("LOADTEST_EMAIL", "admin@abenix.dev")
ADMIN_PASSWORD = os.environ.get("LOADTEST_PASSWORD", "Admin123456")
TENANT_PASSWORD = "LoadTest-2026-telemetry"


def log(msg: str) -> None:
    print(f"[loadtest {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 2)


# publishers, one process per slice of nodes


def publisher(
    group_nodes: list[tuple[str, str]],
    rate: float,
    seconds: float,
    start_at: float,
    out: Any,
) -> None:
    import paho.mqtt.client as mqtt

    from app.telemetry import brokers
    from app.telemetry import sparkplug as sp
    from app.telemetry.sparkplug import sparkplug_b_pb2 as pb

    b = brokers.parse_url(MQTT)
    clients = {}
    seqs = {}
    for g, n in group_nodes:
        c = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"lt-{g}-{n}-{os.getpid()}",
            protocol=mqtt.MQTTv311,
        )
        c.max_queued_messages_set(0)
        c.max_inflight_messages_set(1000)
        will = pb.Payload()
        will.timestamp = int(time.time() * 1000)
        m = will.metrics.add()
        m.name, m.datatype, m.long_value = "bdSeq", pb.Int64, 1
        c.will_set(f"spBv1.0/{g}/NDEATH/{n}", will.SerializeToString(), qos=0)
        c.connect(b.host, b.port, keepalive=30)
        c.loop_start()
        clients[(g, n)] = c
        seqs[(g, n)] = 0
    time.sleep(1.0)
    names = [
        "Engine/Speed_rpm",
        "Engine/Load_pct",
        "Engine/CoolantTemp_C",
        "Hydraulics/BoomPressure_bar",
        "Kinematics/Swing_rad",
        "Kinematics/Boom_rad",
        "GNSS/X_m",
        "GNSS/Y_m",
        "GNSS/Heading_rad",
        "Task/State",
        "Safety/Hold",
        "Seq/Counter",
    ]

    def nxt(key: tuple[str, str]) -> int:
        s = seqs[key]
        seqs[key] = (s + 1) % 256
        return s

    for (g, n), c in clients.items():
        c.publish(
            f"spBv1.0/{g}/NBIRTH/{n}",
            sp.encode(
                [
                    {"name": "bdSeq", "value": 1, "datatype": "Int64"},
                    {
                        "name": "Node Control/Rebirth",
                        "value": False,
                        "datatype": "Boolean",
                    },
                ],
                seq=nxt((g, n)),
            ),
        )
        metrics = []
        for i, name in enumerate(names):
            dtype = (
                "String"
                if name == "Task/State"
                else "Boolean" if name == "Safety/Hold" else "Double"
            )
            val = "idle" if dtype == "String" else False if dtype == "Boolean" else 0.0
            metrics.append(
                {"name": name, "alias": i + 1, "value": val, "datatype": dtype}
            )
        c.publish(f"spBv1.0/{g}/DBIRTH/{n}/engine", sp.encode(metrics, seq=nxt((g, n))))
    while time.time() < start_at:
        time.sleep(0.01)
    sent = 0
    interval = 1.0 / rate
    t0 = time.time()
    deadline = t0 + seconds
    k = 0
    order = list(clients.items())
    while True:
        now = time.time()
        if now >= deadline:
            break
        due = t0 + k * interval
        if due > now:
            time.sleep(min(due - now, 0.002))
            continue
        k += 1
        ts = int(time.time() * 1000)
        for (g, n), c in order:
            p = pb.Payload()
            p.timestamp = ts
            p.seq = nxt((g, n))
            for alias, v in (
                (1, 800 + (k % 900)),
                (2, (k % 100) / 100.0),
                (12, float(k)),
            ):
                m = p.metrics.add()
                m.alias, m.timestamp, m.double_value = alias, ts, v
            c.publish(f"spBv1.0/{g}/DDATA/{n}/engine", p.SerializeToString(), qos=0)
            sent += 1
    for (g, n), c in clients.items():
        c.publish(
            f"spBv1.0/{g}/NDEATH/{n}",
            sp.encode([{"name": "bdSeq", "value": 1, "datatype": "Int64"}]),
        )
    time.sleep(1.0)
    for c in clients.values():
        c.disconnect()
        c.loop_stop()
    out.put({"pid": os.getpid(), "sent": sent, "seconds": time.time() - t0})


def run_publishers(
    nodes: list[tuple[str, str]],
    rate: float,
    seconds: float,
    procs: int,
    lead: float = 4.0,
):
    q: Any = mp.Queue()
    start_at = time.time() + lead
    chunks = [nodes[i::procs] for i in range(procs)]
    ps = [
        mp.Process(target=publisher, args=(c, rate, seconds, start_at, q), daemon=True)
        for c in chunks
        if c
    ]
    for p in ps:
        p.start()
    return ps, q, start_at


# API helpers, the real path a person or app uses


class Api:
    def __init__(self, token: str) -> None:
        import httpx

        self.http = httpx.AsyncClient(
            base_url=API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            limits=httpx.Limits(max_connections=400, max_keepalive_connections=100),
        )

    async def get(self, path: str, **kw: Any) -> Any:
        r = await self.http.get(path, **kw)
        r.raise_for_status()
        return r.json().get("data")

    async def send(self, method: str, path: str, body: Any = None) -> Any:
        r = await self.http.request(method, path, json=body)
        doc = r.json() if r.content else {}
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {doc}")
        return doc.get("data")


async def login(email: str, password: str, name: str | None = None) -> str:
    import httpx

    async with httpx.AsyncClient(base_url=API, timeout=30.0) as c:
        r = await c.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code == 401 and name:
            reg = await c.post(
                "/api/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "full_name": name,
                    "tenant_name": name,
                },
            )
            if reg.status_code >= 400:
                raise RuntimeError(f"register {email}: {reg.text}")
            r = await c.post(
                "/api/auth/login", json={"email": email, "password": password}
            )
        r.raise_for_status()
        return r.json()["data"]["access_token"]


async def read_loop(
    api: Api, paths: list[str], stop: asyncio.Event, out: list[float], errors: list[str]
) -> None:
    while not stop.is_set():
        path = random.choice(paths)
        t0 = time.perf_counter()
        try:
            await api.get(path)
            out.append((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc)[:200])
        await asyncio.sleep(0.02)


async def redis_read_loop(
    r: Any,
    tenant: str,
    nodes: list[tuple[str, str]],
    stop: asyncio.Event,
    out: list[float],
) -> None:
    from app.telemetry import reads

    while not stop.is_set():
        g, n = random.choice(nodes)
        t0 = time.perf_counter()
        await reads.node_detail(r, tenant, g, n)
        out.append((time.perf_counter() - t0) * 1000)
        await asyncio.sleep(0.01)


async def sample_latency(
    r: Any, tenants: list[str], stop: asyncio.Event, out: dict[str, list[dict]]
) -> None:
    while not stop.is_set():
        await asyncio.sleep(1.0)
        for t in tenants:
            for raw in (await r.hgetall(K.latency(t))).values():
                try:
                    out.setdefault(t, []).append(json.loads(raw))
                except ValueError:
                    pass


class RateTally:
    """Adds up the per-second rate buckets while they exist, they expire after ten seconds."""

    def __init__(self, r: Any, tenants: list[str], start: float) -> None:
        self.r, self.tenants = r, tenants
        self.next = int(start) + 1
        self.counts: dict[str, dict[str, int]] = {t: {} for t in tenants}

    async def read_until(self, last: int) -> None:
        while self.next <= last:
            for t in self.tenants:
                h = await self.r.hgetall(K.rate(t, self.next))
                c = self.counts[t]
                for f, v in (h or {}).items():
                    c[f] = c.get(f, 0) + int(v or 0)
            self.next += 1

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self.read_until(int(time.time()) - 2)
            try:
                await asyncio.wait_for(stop.wait(), 1.0)
            except asyncio.TimeoutError:
                pass

    def total(self, tenant: str, field: str = "_total") -> int:
        return self.counts.get(tenant, {}).get(field, 0)


async def cleanup(r: Any, tenant: str, groups: set[str]) -> None:
    idx = await r.hgetall(K.index(tenant))
    nodes = set()
    for field, raw in idx.items():
        doc = json.loads(raw)
        if doc.get("group") in groups:
            await r.hdel(K.index(tenant), field)
            await r.delete(
                K.device(tenant, doc["group"], doc["node"], doc.get("device", ""))
            )
            nodes.add((doc["group"], doc["node"]))
    for g, n in nodes:
        for key in (
            K.node_devices(tenant, g, n),
            K.aliases(tenant, g, n),
            K.frames(tenant, g, n),
        ):
            await r.delete(key)
    for key in await r.keys(f"tenant:{tenant}:feed:*"):
        if key.split(":feed:", 1)[1].split("/", 1)[0] in groups:
            await r.delete(key)
    try:
        from app.telemetry import history

        pool = await history.create_pool()
        async with pool.acquire() as c:
            await c.execute(
                "DELETE FROM telemetry_samples WHERE tenant_id = $1 AND grp = ANY($2::text[])",
                __import__("uuid").UUID(tenant),
                list(groups),
            )
        await pool.close()
    except Exception as exc:  # noqa: BLE001
        log(f"history cleanup skipped: {exc}")


async def watch_cpu_wait(
    r: Any, stop: asyncio.Event, seen: dict[str, list[float]]
) -> None:
    """Samples each replica's cpu_wait_pct, so a report shows how much of the tail was the node."""
    while not stop.is_set():
        now = int(time.time() * 1000)
        for rid in await r.zrangebyscore(K.REPLICAS, now - K.ALIVE_MS, "+inf"):
            v = await r.hget(K.replica(rid), "cpu_wait_pct")
            if v is not None:
                seen.setdefault(rid, []).append(float(v))
        try:
            await asyncio.wait_for(stop.wait(), 2.0)
        except asyncio.TimeoutError:
            pass


async def replica_stats(
    r: Any, cpu_wait: dict[str, list[float]] | None = None
) -> list[dict[str, Any]]:
    out = []
    now = int(time.time() * 1000)
    for rid in await r.zrangebyscore(K.REPLICAS, now - K.ALIVE_MS, "+inf"):
        h = await r.hgetall(K.replica(rid))
        waits = (cpu_wait or {}).get(rid) or []
        gc_doc = json.loads(h["gc"]) if h.get("gc") else {}
        out.append(
            {
                "replica": rid[-12:],
                "pool": h.get("pool") or "default",
                "messages_per_second": h.get("messages_per_second"),
                "loop_lag_ms_p99": h.get("loop_lag_ms_p99"),
                "loop_lag_ms_max": h.get("loop_lag_ms_max"),
                "flush_ms_p99": h.get("flush_ms_p99"),
                "stalls": h.get("stalls"),
                "cpu_wait_pct_mean": (
                    round(sum(waits) / len(waits), 1) if waits else None
                ),
                "cpu_wait_pct_max": max(waits) if waits else None,
                "gc_max_ms": gc_doc.get("gc_max_ms"),
                "gc_cpu_max_ms": gc_doc.get("gc_cpu_max_ms"),
            }
        )
    return out


def summarize_lat(samples: list[dict], start: float, end: float) -> dict[str, Any]:
    win = [
        s
        for s in samples
        if start * 1000 <= (s.get("at") or 0) <= end * 1000 and s.get("n")
    ]
    if not win:
        return {}
    return {
        "ingest_to_redis_p50_ms": round(
            sum(s["p50"] * s["n"] for s in win) / sum(s["n"] for s in win), 2
        ),
        "ingest_to_redis_p99_ms": max(s["p99"] for s in win),
        "ingest_to_redis_p99_ms_median_window": pct([s["p99"] for s in win], 50),
        "publish_to_redis_p50_ms": pct([s.get("e2e_p50") or 0 for s in win], 50),
        "publish_to_redis_p99_ms": max((s.get("e2e_p99") or 0) for s in win),
        "windows": len(win),
    }


# T2: 4 nodes x 400 msg/s


async def t2(seconds: int, keep: bool) -> dict[str, Any]:
    import redis.asyncio as aioredis

    from app.core.config import settings

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    token = await login(ADMIN_EMAIL, ADMIN_PASSWORD)
    api = Api(token)
    me = await api.get("/api/me/permissions")
    tenant = me["tenant_id"]
    conns = await api.get("/api/telemetry/connections")
    site = [
        c
        for c in conns
        if c["enabled"]
        and any(t in ("spBv1.0/#", "spBv1.0/loadtest/#") for t in c["topics"])
    ]
    if not site:
        raise RuntimeError(
            "no enabled connection reads spBv1.0/#, run seed_telemetry or add the Site broker"
        )
    group = "loadtest"
    nodes = [(group, f"lt-{i}") for i in range(4)]
    await cleanup(r, tenant, {group})
    ps, q, start_at = run_publishers(nodes, 400, seconds + 5, procs=4)
    await asyncio.sleep(max(0, start_at - time.time()) + 5)
    log("warm, measuring")
    stop = asyncio.Event()
    lat_samples: dict[str, list[dict]] = {}
    api_reads: list[float] = []
    redis_reads: list[float] = []
    errors: list[str] = []
    m0 = time.time()
    tally = RateTally(r, [tenant], m0)
    tally_stop = asyncio.Event()
    tally_task = asyncio.create_task(tally.run(tally_stop))
    cpu_wait: dict[str, list[float]] = {}
    cpu_task = asyncio.create_task(watch_cpu_wait(r, tally_stop, cpu_wait))
    paths = [f"/api/telemetry/devices/{g}/{n}" for g, n in nodes]
    tasks = [asyncio.create_task(sample_latency(r, [tenant], stop, lat_samples))]
    tasks += [
        asyncio.create_task(read_loop(api, paths, stop, api_reads, errors))
        for _ in range(4)
    ]
    tasks += [
        asyncio.create_task(redis_read_loop(r, tenant, nodes, stop, redis_reads))
        for _ in range(2)
    ]
    await asyncio.sleep(seconds - 2)
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    m1 = time.time()
    sent = [q.get(timeout=60) for _ in ps]
    for p in ps:
        p.join(timeout=10)
    await asyncio.sleep(2)
    tally_stop.set()
    await tally_task
    await cpu_task
    await tally.read_until(int(m1) - 1)
    ingested = sum(tally.total(tenant, f"{g}/{n}") for g, n in nodes)
    stats = await r.hgetall(K.stats(tenant))
    health = await api.get("/api/telemetry/health")
    report = {
        "scenario": "T2: 4 nodes x 400 msg/s, one tenant, one connection",
        "measured_seconds": round(m1 - m0, 1),
        "published_total": sum(s["sent"] for s in sent),
        "published_per_second": round(sum(s["sent"] / s["seconds"] for s in sent), 1),
        "ingested_per_second": round(ingested / max(1, int(m1) - int(m0) - 1), 1),
        # published over the whole run, ingested over the measured window, so near 1.0 is keeping up
        "ingested_vs_published": round(
            (ingested / max(1, int(m1) - int(m0) - 1))
            / max(1.0, sum(s["sent"] / s["seconds"] for s in sent)),
            3,
        ),
        **summarize_lat(lat_samples.get(tenant, []), m0, m1),
        "read_node_api_p50_ms": pct(api_reads, 50),
        "read_node_api_p99_ms": pct(api_reads, 99),
        "read_node_redis_p50_ms": pct(redis_reads, 50),
        "read_node_redis_p99_ms": pct(redis_reads, 99),
        "reads": len(api_reads),
        "read_errors": len(errors),
        "seq_gaps": int(stats.get("seq_gaps") or 0),
        "throttled": int(stats.get("throttled") or 0),
        "dropped": health.get("dropped"),
        "replicas": health.get("replicas"),
        "ingest_replicas": await replica_stats(r, cpu_wait),
    }
    if not keep:
        await cleanup(r, tenant, {group})
    await api.http.aclose()
    await r.aclose()
    return report


# T7: 50 nodes x 200 msg/s, 3 tenants, 200 viewers, a replica killed


T7_LAYOUT = {
    "a": {"groups": {"ltA1": 9, "ltA2": 8}, "shared": False},
    "b": {"groups": {"ltB1": 9, "ltB2": 8}, "shared": False},
    "c": {"groups": {"ltC": 16}, "shared": True},
}


async def viewer(
    api: Any, nodes: list[str], stop: asyncio.Event, stats: dict[str, Any]
) -> None:
    try:
        async with api.http.stream(
            "GET",
            "/api/telemetry/stream",
            params={"nodes": ",".join(nodes)},
            timeout=None,
        ) as res:
            if res.status_code != 200:
                stats["refused"] += 1
                stats["errors"].append(f"{res.status_code}")
                return
            stats["open"] += 1
            event = None
            async for line in res.aiter_lines():
                if stop.is_set():
                    break
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event == "metrics":
                    doc = json.loads(line[5:])
                    now = time.time() * 1000
                    for m in doc.get("metrics") or []:
                        if m.get("name") == "Seq/Counter" and m.get("ts"):
                            stats["lat"].append(now - m["ts"])
                    stats["events"] += 1
                elif line.startswith("data:") and event == "health":
                    stats["health"] += 1
    except Exception as exc:  # noqa: BLE001
        if not stop.is_set():
            stats["errors"].append(str(exc)[:120])


async def watch_failover(
    r: Any,
    tenants: dict[str, str],
    nodes_by_tenant: dict[str, list[tuple[str, str]]],
    stop: asyncio.Event,
    out: dict[str, Any],
) -> None:
    seen: dict[str, float] = {}
    while not stop.is_set():
        await asyncio.sleep(0.25)
        now = time.time()
        live = await r.zrangebyscore(K.REPLICAS, int(now * 1000) - K.ALIVE_MS, "+inf")
        for rid in live:
            h = await r.hgetall(K.replica(rid))
            if h.get("at"):
                seen[rid] = int(h["at"]) / 1000.0
        if "killed" not in out:
            for rid, at in seen.items():
                if now - at > 2.5 and rid in out.get("replicas_before", []):
                    out["killed"] = rid
                    out["last_heartbeat_at"] = at
                    out["detected_at"] = now
                    log(f"replica {rid} stopped beating")
        elif "all_fresh_at" not in out:
            k = out["last_heartbeat_at"]
            fresh = True
            for t, nodes in nodes_by_tenant.items():
                pipe = r.pipeline(transaction=False)
                for g, n in nodes:
                    pipe.hget(K.device(tenants[t], g, n, "engine"), "m:Seq/Counter")
                for raw in await pipe.execute():
                    ts = json.loads(raw)["ts"] / 1000.0 if raw else 0
                    if ts < k + 1.0 or now - ts > 2.0:
                        fresh = False
                        break
                if not fresh:
                    break
            if fresh:
                out["all_fresh_at"] = now
                log("every node is reporting again")


async def t7(
    seconds: int, keep: bool, viewers: int, kill_after: int, rate: int = 200
) -> dict[str, Any]:
    import redis.asyncio as aioredis

    from app.core.config import settings

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    admin = Api(await login(ADMIN_EMAIL, ADMIN_PASSWORD))
    reps = await r.zrangebyscore(
        K.REPLICAS, int(time.time() * 1000) - K.ALIVE_MS, "+inf"
    )
    log(f"ingest replicas: {reps}")
    old_cap = None
    for cat in (
        (await admin.get("/api/admin/settings")).get("categories") or {}
    ).values():
        for it in cat:
            if it["key"] == "telemetry.sse.max_per_user":
                old_cap = it["value"]
    await admin.send(
        "PATCH", "/api/admin/settings/telemetry.sse.max_per_user", {"value": "100"}
    )
    # a broker reading spBv1.0/# would take the load groups too, narrow it to the real machines meanwhile
    narrowed: list[tuple[str, list[str]]] = []
    for c in await admin.get("/api/telemetry/connections"):
        if c["enabled"] and "spBv1.0/#" in (c.get("topics") or []):
            keep = [t for t in c["topics"] if t != "spBv1.0/#"]
            await admin.send(
                "PATCH",
                f"/api/telemetry/connections/{c['id']}",
                {"topics": keep + ["spBv1.0/groundwork/#", "spBv1.0/STATE/#"]},
            )
            narrowed.append((c["id"], c["topics"]))
    apis: dict[str, Api] = {}
    tenants: dict[str, str] = {}
    conn_ids: dict[str, list[str]] = {}
    nodes_by_tenant: dict[str, list[tuple[str, str]]] = {}
    groups_by_tenant: dict[str, set[str]] = {}
    for key, spec in T7_LAYOUT.items():
        email = f"loadtest-{key}@abenix.dev"
        api = Api(await login(email, TENANT_PASSWORD, name=f"Load test {key.upper()}"))
        apis[key] = api
        tenants[key] = (await api.get("/api/me/permissions"))["tenant_id"]
        have = {c["name"]: c for c in await api.get("/api/telemetry/connections")}
        conn_ids[key] = []
        nodes_by_tenant[key] = []
        groups_by_tenant[key] = set(spec["groups"])
        await cleanup(r, tenants[key], groups_by_tenant[key])
        for g, count in spec["groups"].items():
            name = f"Load test {g}"
            body = {
                "name": name,
                "broker_url": MQTT,
                "topics": [f"spBv1.0/{g}/#"],
                "shared_subscription": spec["shared"],
                "enabled": True,
            }
            if name in have:
                c = await api.send(
                    "PATCH", f"/api/telemetry/connections/{have[name]['id']}", body
                )
            else:
                c = await api.send("POST", "/api/telemetry/connections", body)
            conn_ids[key].append(c["id"])
            nodes_by_tenant[key] += [(g, f"{g.lower()}-{i}") for i in range(count)]
    all_nodes = [n for v in nodes_by_tenant.values() for n in v]
    log(
        f"{len(all_nodes)} nodes over {len(tenants)} workspaces, waiting for connections"
    )
    for _ in range(60):
        await asyncio.sleep(1)
        ok = True
        for key, api in apis.items():
            for c in await api.get("/api/telemetry/connections"):
                if c["id"] in conn_ids[key] and c["status"] != "connected":
                    ok = False
        if ok:
            break
    placement = {}
    for key in apis:
        for cid in conn_ids[key]:
            raw = await r.hgetall(K.conn_status(cid))
            placement[cid] = sorted(raw)
    ps, q, start_at = run_publishers(
        all_nodes, rate, seconds + 5, procs=min(10, len(all_nodes))
    )
    await asyncio.sleep(max(0, start_at - time.time()) + 6)
    log("warm, opening viewers")
    stop = asyncio.Event()
    vstats = {
        "open": 0,
        "refused": 0,
        "events": 0,
        "health": 0,
        "lat": [],
        "errors": [],
    }
    vtasks = []
    keys_cycle = list(apis)
    for i in range(viewers):
        key = keys_cycle[i % len(keys_cycle)]
        g, n = random.choice(nodes_by_tenant[key])
        vtasks.append(
            asyncio.create_task(viewer(apis[key], [f"{g}/{n}"], stop, vstats))
        )
    await asyncio.sleep(3)
    log(f"{vstats['open']} viewers open, measuring")
    m0 = time.time()
    stored0 = {
        t: int((await r.hget(K.stats(t), "messages")) or 0) for t in tenants.values()
    }
    tally = RateTally(r, list(tenants.values()), m0)
    tally_stop = asyncio.Event()
    tally_task = asyncio.create_task(tally.run(tally_stop))
    cpu_wait: dict[str, list[float]] = {}
    cpu_task = asyncio.create_task(watch_cpu_wait(r, tally_stop, cpu_wait))
    lat_samples: dict[str, list[dict]] = {}
    api_reads: list[float] = []
    errors: list[str] = []
    fo: dict[str, Any] = {"replicas_before": reps}
    tasks = [
        asyncio.create_task(
            sample_latency(r, list(tenants.values()), stop, lat_samples)
        )
    ]
    for key, api in apis.items():
        paths = [f"/api/telemetry/devices/{g}/{n}" for g, n in nodes_by_tenant[key]]
        tasks += [
            asyncio.create_task(read_loop(api, paths, stop, api_reads, errors))
            for _ in range(2)
        ]
    tasks.append(
        asyncio.create_task(watch_failover(r, tenants, nodes_by_tenant, stop, fo))
    )
    await asyncio.sleep(kill_after)
    pre_vlat = list(vstats["lat"])
    pre_reads = list(api_reads)
    log("READY_FOR_KILL")
    await asyncio.sleep(max(5, seconds - kill_after - 10))
    stop.set()
    for t in vtasks + tasks:
        t.cancel()
    await asyncio.gather(*vtasks, *tasks, return_exceptions=True)
    m1 = time.time()
    sent = [q.get(timeout=90) for _ in ps]
    for p in ps:
        p.join(timeout=10)
    await asyncio.sleep(2)
    tally_stop.set()
    await tally_task
    await cpu_task
    await tally.read_until(int(m1) - 1)
    per_tenant = {}
    total_ingested = 0
    for key, t in tenants.items():
        # the durable counter, the rate buckets expire if this loop falls behind
        stored = int((await r.hget(K.stats(t), "messages")) or 0) - stored0[t]
        ing = max(stored, tally.total(t))
        total_ingested += ing
        st = await r.hgetall(K.stats(t))
        per_tenant[key] = {
            "nodes": len(nodes_by_tenant[key]),
            "ingested_per_second": round(ing / max(1, int(m1) - int(m0) - 1), 1),
            **summarize_lat(lat_samples.get(t, []), m0, m0 + kill_after),
            "seq_gaps": int(st.get("seq_gaps") or 0),
            "throttled": int(st.get("throttled") or 0),
        }
    published = sum(s["sent"] for s in sent)
    report = {
        "scenario": f"T7: 50 nodes x {rate} msg/s, 3 workspaces, 5 connections (one shared), 2 replicas",
        "measured_seconds": round(m1 - m0, 1),
        "replicas_before": reps,
        "connection_placement": placement,
        "published_total": published,
        "published_per_second": round(sum(s["sent"] / s["seconds"] for s in sent), 1),
        "ingested_per_second": round(total_ingested / max(1, int(m1) - int(m0) - 1), 1),
        "per_workspace": per_tenant,
        "viewers_open": vstats["open"],
        "viewers_refused": vstats["refused"],
        "viewer_events": vstats["events"],
        "viewer_health_events": vstats["health"],
        "viewer_latency_p50_ms_before_kill": pct(pre_vlat, 50),
        "viewer_latency_p99_ms_before_kill": pct(pre_vlat, 99),
        "read_node_api_p50_ms_before_kill": pct(pre_reads, 50),
        "read_node_api_p99_ms_before_kill": pct(pre_reads, 99),
        "read_node_api_p99_ms_whole_run": pct(api_reads, 99),
        "read_errors": len(errors),
        "failover": {
            "killed": fo.get("killed"),
            "seconds_to_detect": (
                round(fo["detected_at"] - fo["last_heartbeat_at"], 1)
                if "detected_at" in fo
                else None
            ),
            "seconds_until_every_node_reports": (
                round(fo["all_fresh_at"] - fo["last_heartbeat_at"], 1)
                if "all_fresh_at" in fo
                else None
            ),
        },
        "viewer_errors": vstats["errors"][:5],
        "ingest_replicas": await replica_stats(r, cpu_wait),
    }
    if not keep:
        for key, api in apis.items():
            for cid in conn_ids[key]:
                await api.send("DELETE", f"/api/telemetry/connections/{cid}")
            await cleanup(r, tenants[key], groups_by_tenant[key])
    for cid, topics in narrowed:
        await admin.send(
            "PATCH", f"/api/telemetry/connections/{cid}", {"topics": topics}
        )
    if old_cap:
        await admin.send(
            "PATCH",
            "/api/admin/settings/telemetry.sse.max_per_user",
            {"value": str(old_cap)},
        )
    for api in [admin, *apis.values()]:
        await api.http.aclose()
    await r.aclose()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=("t2", "t7"))
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--viewers", type=int, default=200)
    ap.add_argument("--kill-after", type=int, default=30)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument(
        "--rate", type=int, default=200, help="t7 messages a second per node"
    )
    a = ap.parse_args()
    if a.scenario == "t2":
        report = asyncio.run(t2(a.seconds, a.keep))
    else:
        report = asyncio.run(t7(a.seconds, a.keep, a.viewers, a.kill_after, a.rate))
    print("REPORT " + json.dumps(report), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    mp.set_start_method("fork", force=True) if hasattr(os, "fork") else None
    main()
