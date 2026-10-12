"""Reads over the Redis latest-value store, shared by the API and the device_state tool."""

from __future__ import annotations

import json
import time
from typing import Any

from app.telemetry import keys as K

DEVICE_FIELDS = (
    "group",
    "node",
    "device",
    "online",
    "last_seen",
    "birth_at",
    "offline_at",
    "msgs_per_sec",
    "seq_gaps",
    "metric_count",
    "connection_id",
)


RATE_WINDOW_S = 5


def queue_rates(pipe: Any, tenant: Any) -> None:
    now = int(time.time())
    for sec in range(now - RATE_WINDOW_S, now):
        pipe.hgetall(K.rate(tenant, sec))


def merge_rates(buckets: list[dict[str, str]]) -> dict[str, float]:
    """Per second rates over the last few seconds, so batched sources do not read as zero."""
    out: dict[str, float] = {}
    for h in buckets:
        for f, v in (h or {}).items():
            out[f] = out.get(f, 0.0) + K.as_int(v)
    return {f: round(v / RATE_WINDOW_S, 1) for f, v in out.items()}


def _rate_fields(field: str, mps: dict[str, Any]) -> dict[str, float]:
    return {
        "msgs_per_sec": float(mps.get(field) or 0),
        "readings_per_sec": float(mps.get(f"r:{field}") or 0),
    }


def _row(doc: dict[str, Any], mps: dict[str, str]) -> dict[str, Any]:
    g, n, d = doc.get("group", ""), doc.get("node", ""), doc.get("device", "")
    field = f"{g}/{n}" if not d else K.index_field(g, n, d)
    return {
        "group": g,
        "node": n,
        "device": d,
        "online": bool(doc.get("online")),
        "last_seen": doc.get("last_seen"),
        "birth_at": doc.get("birth_at"),
        "offline_at": doc.get("offline_at"),
        **_rate_fields(field, mps),
        "seq_gaps": K.as_int(doc.get("seq_gaps")),
        "metric_count": K.as_int(doc.get("metric_count")),
        "connection_id": doc.get("connection_id"),
        "team_id": doc.get("team_id"),
    }


async def all_devices(r: Any, tenant: Any) -> list[dict[str, Any]]:
    pipe = r.pipeline(transaction=False)
    pipe.hgetall(K.index(tenant))
    queue_rates(pipe, tenant)
    res = await pipe.execute()
    idx, mps = res[0], merge_rates(res[1:])
    out = []
    for raw in (idx or {}).values():
        try:
            doc = json.loads(raw)
        except (TypeError, ValueError):
            continue
        out.append(_row(doc, mps or {}))
    out.sort(key=lambda x: (x["group"], x["node"], x["device"]))
    return out


def filter_devices(
    rows: list[dict[str, Any]],
    scope: Any,
    *,
    q: str = "",
    group: str = "",
    node: str = "",
    status: str = "",
    team: str = "",
    teams: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    ql = (q or "").strip().lower()
    st = (status or "").strip().lower()
    out = []
    for r in rows:
        if not scope.sees(r.get("connection_id")):
            continue
        if group and r["group"] != group:
            continue
        if node and r["node"] != node:
            continue
        if st == "online" and not r["online"]:
            continue
        if st == "offline" and r["online"]:
            continue
        tid = r.get("team_id")
        if team:
            if team in ("none", "workspace"):
                if tid:
                    continue
            elif tid != team and (teams or {}).get(tid or "") != team:
                continue
        if ql and ql not in f"{r['group']}/{r['node']}/{r['device']}".lower():
            continue
        r = dict(r)
        r["team_name"] = (teams or {}).get(tid) if tid else None
        out.append(r)
    return out


async def node_detail(
    r: Any, tenant: Any, g: str, n: str, device: str | None = None
) -> dict[str, Any] | None:
    devs = sorted(await r.smembers(K.node_devices(tenant, g, n)) or [])
    if "" not in devs:
        devs.insert(0, "")
    if device is not None:
        devs = [""] + ([device] if device and device in devs else [])
    pipe = r.pipeline(transaction=False)
    for d in devs:
        pipe.hgetall(K.device(tenant, g, n, d))
    queue_rates(pipe, tenant)
    res = await pipe.execute()
    mps = merge_rates(res[len(devs) :])
    hashes = dict(zip(devs, res[: len(devs)]))
    node_h = hashes.get("") or {}
    if not node_h and not any(hashes.values()):
        return None

    def meta(h: dict[str, str], d: str) -> dict[str, Any]:
        online = h.get("_online") == "1"
        field = f"{g}/{n}" if not d else K.index_field(g, n, d)
        return {
            "online": online,
            "last_seen": K.as_int(h.get("_last_seen")) or None,
            "birth_at": K.as_int(h.get("_birth_at")) or None,
            "offline_at": K.as_int(h.get("_offline_at")) or None,
            **_rate_fields(field, mps),
            "seq_gaps": K.as_int(h.get("_seq_gaps")),
            "connection_id": h.get("_conn") or None,
        }

    node_meta = meta(node_h, "")
    node_online = node_meta["online"]
    out: dict[str, Any] = {
        "group": g,
        "node": n,
        **node_meta,
        "bd_seq": K.as_int(node_h.get("_bdseq")) if node_h.get("_bdseq") else None,
        "metrics": K.unpack_metrics(node_h, node_online),
        "devices": [],
    }
    for d in devs:
        if not d:
            continue
        h = hashes.get(d) or {}
        if not h:
            continue
        m = meta(h, d)
        if not out["connection_id"]:
            out["connection_id"] = m["connection_id"]
        rows = K.unpack_metrics(h, m["online"] and node_online)
        out["devices"].append(
            {"device": d, **m, "metric_count": len(rows), "metrics": rows}
        )
    out["metric_count"] = len(out["metrics"])
    return out


async def frames(
    r: Any, tenant: Any, g: str, n: str, limit: int = 200, since: int | None = None
) -> list[dict[str, Any]]:
    raw = await r.lrange(
        K.frames(tenant, g, n), 0, max(0, min(limit, K.FRAME_RING) - 1)
    )
    out = []
    for s in raw or []:
        try:
            f = json.loads(s)
        except (TypeError, ValueError):
            continue
        if since is not None and K.as_int(f.get("t")) <= since:
            break
        out.append(f)
    return out


async def live_replicas(r: Any) -> list[dict[str, Any]]:
    now = int(time.time() * 1000)
    ids = await r.zrangebyscore(K.REPLICAS, now - K.ALIVE_MS, "+inf")
    if not ids:
        return []
    pipe = r.pipeline(transaction=False)
    for rid in ids:
        pipe.hgetall(K.replica(rid))
    out = []
    for rid, h in zip(ids, await pipe.execute()):
        if not h:
            continue
        try:
            conns = json.loads(h.get("connections") or "[]")
        except ValueError:
            conns = []
        out.append(
            {
                "replica": rid,
                "connections": conns,
                "messages_per_second": float(h.get("messages_per_second") or 0),
                "queued": K.as_int(h.get("queued")),
                "dropped": K.as_int(h.get("dropped")),
                "latency_p50": float(h.get("latency_p50") or 0),
                "latency_p99": float(h.get("latency_p99") or 0),
                "loop_lag_ms_p99": float(h.get("loop_lag_ms_p99") or 0),
                "stalls": K.as_int(h.get("stalls")),
                "cpu_wait_pct": float(h.get("cpu_wait_pct") or 0),
                "pool": h.get("pool") or "default",
                "transports": (
                    json.loads(h["transports"]) if h.get("transports") else []
                ),
                "transports_exclude": (
                    json.loads(h["transports_exclude"])
                    if h.get("transports_exclude")
                    else []
                ),
                "heartbeat_at": K.as_int(h.get("at")),
            }
        )
    return out


def _takes(rep: dict[str, Any], transport: str) -> bool:
    only, but = rep.get("transports") or [], rep.get("transports_exclude") or []
    return (not only or transport in only) and transport not in but


def pools(replicas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rep in replicas:
        p = out.setdefault(
            rep["pool"],
            {
                "name": rep["pool"],
                "transports": rep.get("transports") or [],
                "replicas": 0,
                "messages_per_second": 0.0,
                "latency_p99": 0.0,
                "loop_lag_ms_p99": 0.0,
                "stalls": 0,
            },
        )
        p["replicas"] += 1
        p["messages_per_second"] = round(
            p["messages_per_second"] + rep["messages_per_second"], 1
        )
        p["latency_p99"] = max(p["latency_p99"], rep["latency_p99"])
        p["loop_lag_ms_p99"] = max(
            p["loop_lag_ms_p99"], rep.get("loop_lag_ms_p99") or 0
        )
        p["stalls"] += rep.get("stalls") or 0
        p["cpu_wait_pct"] = max(
            p.get("cpu_wait_pct", 0.0), rep.get("cpu_wait_pct") or 0
        )
    return sorted(out.values(), key=lambda x: x["name"])


def _transport_label(transport: str) -> str:
    try:
        from app.telemetry import registry

        cls = registry.connectors().get(transport)
        return (cls.label if cls else "") or transport
    except Exception:  # noqa: BLE001
        return transport


def _sum_counts(parts: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in parts:
        for k, v in p.items():
            out[k] = out.get(k, 0) + K.as_int(v)
    return out


def _latest_reasons(parts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for p in parts:
        for k, v in p.items():
            if not isinstance(v, dict):
                continue
            if k not in out or (v.get("at") or 0) > (out[k].get("at") or 0):
                out[k] = v
    return out


async def connection_status(
    r: Any, conns: list[Any], replicas: list[dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Live status per connection id: connected, connecting, error or disabled."""
    if replicas is None:
        replicas = await live_replicas(r)
    ingest_up = bool(replicas)
    pipe = r.pipeline(transaction=False)
    for c in conns:
        pipe.hgetall(K.conn_status(c.id))
    res = await pipe.execute() if conns else []
    now = int(time.time() * 1000)
    out: dict[str, dict[str, Any]] = {}
    for c, h in zip(conns, res):
        cid = str(c.id)
        if not c.enabled:
            out[cid] = {
                "status": "disabled",
                "last_error": None,
                "messages_per_second": 0,
                "last_message_at": None,
                "dropped": 0,
            }
            continue
        parts = []
        for raw in (h or {}).values():
            try:
                doc = json.loads(raw)
            except ValueError:
                continue
            if now - K.as_int(doc.get("at")) <= 15000:
                parts.append(doc)
        transport = getattr(c, "transport", None) or "mqtt"
        if (
            not parts
            and ingest_up
            and not any(_takes(rep, transport) for rep in replicas)
        ):
            out[cid] = {
                "status": "error",
                "last_error": f"No ingest pool takes {_transport_label(transport)}. Add one in the chart values under telemetryIngest.pools.",
                "messages_per_second": 0,
                "last_message_at": None,
                "dropped": 0,
                "pool": None,
            }
            continue
        if not parts:
            out[cid] = {
                "status": "connecting" if ingest_up else "error",
                "last_error": (
                    None
                    if ingest_up
                    else "The telemetry ingest service is not running, so nothing is read from this broker."
                ),
                "messages_per_second": 0,
                "last_message_at": None,
                "dropped": 0,
            }
            continue
        statuses = [p.get("status") for p in parts]
        status = (
            "connected"
            if "connected" in statuses
            else "error" if "error" in statuses else "connecting"
        )
        errors = [p.get("last_error") for p in parts if p.get("last_error")]
        lasts = [p.get("last_message_at") for p in parts if p.get("last_message_at")]
        out[cid] = {
            "status": status,
            "last_error": errors[0] if errors and status != "connected" else None,
            "messages_per_second": round(
                sum(float(p.get("messages_per_second") or 0) for p in parts), 1
            ),
            "last_message_at": max(lasts) if lasts else None,
            "dropped": sum(K.as_int(p.get("dropped")) for p in parts),
            "decode_errors": sum(K.as_int(p.get("decode_errors")) for p in parts),
            "pipeline": _sum_counts([p.get("pipeline") or {} for p in parts]),
            "last_reasons": _latest_reasons(
                [p.get("last_reasons") or {} for p in parts]
            ),
            "clock_skew_ms": next(
                (
                    p.get("clock_skew_ms")
                    for p in parts
                    if p.get("clock_skew_ms") is not None
                ),
                None,
            ),
            "replicas": [p.get("replica") for p in parts],
            "pool": next(
                (
                    rep["pool"]
                    for rep in replicas
                    if rep["replica"] in {p.get("replica") for p in parts}
                ),
                None,
            ),
        }
    return out


async def health(
    r: Any,
    tenant: Any,
    scope: Any,
    quota: dict[str, int],
) -> dict[str, Any]:
    replicas = await live_replicas(r)
    conns = [c for c in scope.connections if scope.sees(str(c.id))]
    statuses = await connection_status(r, conns, replicas)
    pipe = r.pipeline(transaction=False)
    pipe.hgetall(K.rate(tenant, int(time.time()) - 1))
    pipe.hgetall(K.latency(tenant))
    pipe.hgetall(K.stats(tenant))
    pipe.hgetall(K.throttle(tenant))
    pipe.hgetall(K.index(tenant))
    rate, lat, stats, thr, idx = await pipe.execute()
    now = int(time.time() * 1000)
    p50s, p99s, e50, e99, ns = [], [], [], [], []
    for raw in (lat or {}).values():
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if now - K.as_int(doc.get("at")) > 15000:
            continue
        n = K.as_int(doc.get("n"))
        ns.append(n)
        p50s.append((doc.get("p50"), n))
        p99s.append(doc.get("p99"))
        e50.append(doc.get("e2e_p50"))
        e99.append(doc.get("e2e_p99"))
    total_n = sum(ns) or 1
    p50 = round(sum((v or 0) * n for v, n in p50s) / total_n, 2) if p50s else None
    p99 = round(max(v or 0 for v in p99s), 2) if p99s else None
    nodes_total = nodes_online = devices_total = 0
    node_conn: dict[tuple[str, str], Any] = {}
    for raw in (idx or {}).values():
        devices_total += 1
        try:
            doc = json.loads(raw)
        except ValueError:
            continue
        if doc.get("device"):
            continue
        node_conn[(doc.get("group"), doc.get("node"))] = doc.get("connection_id")
        if not scope.sees(doc.get("connection_id")):
            continue
        nodes_total += 1
        nodes_online += 1 if doc.get("online") else 0
    by_node = []
    for f, v in (rate or {}).items():
        if f.count("/") != 1 or f.startswith(("r:", "_")):
            continue
        g, n = f.split("/")
        if not scope.everything and not scope.sees(node_conn.get((g, n))):
            continue
        by_node.append({"group": g, "node": n, "messages_per_second": K.as_int(v)})
    by_node.sort(key=lambda x: (x["group"], x["node"]))
    mps = (
        K.as_int((rate or {}).get("_total"))
        if scope.everything
        else sum(x["messages_per_second"] for x in by_node)
    )
    throttled = bool(thr)
    tenant_conns = len(scope.connections)
    return {
        "ingest_up": bool(replicas),
        "replicas": len(replicas),
        "pools": pools(replicas),
        "messages_per_second": mps,
        "messages_per_second_by_node": by_node,
        "ingest_latency_ms": {"p50": p50, "p99": p99},
        "ingest_latency_ms_p50": p50,
        "ingest_latency_ms_p99": p99,
        "publish_to_store_ms_p50": round(max(e50), 2) if e50 and any(e50) else None,
        "publish_to_store_ms_p99": round(max(e99), 2) if e99 and any(e99) else None,
        "publish_to_store_ms": {
            "p50": round(max(e50), 2) if e50 and any(e50) else None,
            "p99": round(max(e99), 2) if e99 and any(e99) else None,
        },
        "seq_gaps": K.as_int((stats or {}).get("seq_gaps")),
        "dropped": sum(K.as_int(s.get("dropped")) for s in statuses.values()),
        "throttled_messages": K.as_int((stats or {}).get("throttled")),
        "throttled": throttled,
        "throttle_reason": (thr or {}).get("reason") if throttled else None,
        "nodes_online": nodes_online,
        "nodes_total": nodes_total,
        "connections": [
            {"id": str(c.id), "name": c.name, **statuses.get(str(c.id), {})}
            for c in conns
        ],
        "quota": {
            "max_connections": quota.get("max_connections"),
            "max_devices": quota.get("max_devices"),
            "max_msgs_per_sec": quota.get("max_msgs_per_sec"),
            "retention_days": quota.get("retention_days"),
            "used": {
                "connections": tenant_conns,
                "devices": devices_total,
                "msgs_per_sec": mps,
            },
        },
        "at": now,
    }


def diagnose(
    enabled: bool, status: dict[str, Any] | None, subjects: list[str]
) -> dict[str, Any]:
    """Why a connection's data is or is not showing, as a state, a plain message and the fix."""
    st = status or {}
    counts = st.get("pipeline") or {}
    reasons = st.get("last_reasons") or {}
    received = K.as_int(counts.get("received"))
    stored = K.as_int(counts.get("stored"))

    def out(state: str, message: str, fix: str | None = None) -> dict[str, Any]:
        return {"state": state, "message": message, "fix": fix, "counters": counts}

    def why(kind: str) -> str:
        return (reasons.get(kind) or {}).get("reason") or ""

    if not enabled:
        return out(
            "disabled",
            "This connection is turned off, so nothing is read.",
            "Turn it on under Monitor, Telemetry, Connections.",
        )
    if st.get("status") == "error":
        if "not running" in (st.get("last_error") or ""):
            return out(
                "not_running",
                st.get("last_error") or "",
                "An admin can apply the chart with bash scripts/deploy.sh chart.",
            )
        return out(
            "error",
            st.get("last_error") or "The connection failed.",
            "Fix the settings named above, then press Test.",
        )
    if st.get("status") == "connecting":
        return out(
            "connecting", st.get("last_error") or "Connecting to the source.", None
        )
    if received == 0:
        where = ", ".join(subjects[:5]) if subjects else "its subjects"
        return out(
            "no_messages",
            f"Connected, but nothing has arrived on {where}.",
            "Check that the source is sending to these subjects, and press Test to see what arrives.",
        )
    if K.as_int(counts.get("throttled")) and not stored:
        return out(
            "throttled",
            why("throttled"),
            "An admin can raise the limit under Admin, Settings, Telemetry.",
        )
    if K.as_int(counts.get("dlq")) and not stored:
        kind = (
            "mapping_failed"
            if K.as_int(counts.get("mapping_failed"))
            else "decode_failed"
        )
        return out(
            kind,
            why(kind) or why("dlq"),
            "Open the dead letters to see the messages, fix the decoder or mapping, then replay them.",
        )
    if K.as_int(counts.get("skipped")) and not stored:
        return out(
            "filtered",
            why("skipped"),
            "Every message so far was left out by the mapping's filter. Loosen the filter in the mapping editor.",
        )
    if K.as_int(counts.get("empty")) and not stored:
        return out(
            "mapping_empty",
            why("empty"),
            "Preview a live message in the mapping editor to see what it gives.",
        )
    if K.as_int(counts.get("dropped")):
        return out(
            "dropping", why("dropped"), "Add ingest replicas or mark the source shared."
        )
    return out("ok", f"{stored} messages stored.", None)
