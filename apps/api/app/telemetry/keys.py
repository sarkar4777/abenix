"""Redis key layout shared by the ingest service, the API and the device_state tool."""

from __future__ import annotations

import json
import time
from typing import Any

FRAME_RING = 2000
REPLICAS = "tel:ingest:replicas"
CHANGED = "tel:connections:changed"
FORGOTTEN = "tel:devices:forgotten"
ALIVE_MS = 6000
LEASE_MS = 6000
META_FIELDS = (
    "_online",
    "_last_seen",
    "_birth_at",
    "_offline_at",
    "_seq_gaps",
    "_mps",
    "_conn",
    "_bdseq",
)


def device(t: Any, g: str, n: str, d: str = "") -> str:
    return f"tel:{t}:{g}:{n}:{d}"


def index(t: Any) -> str:
    return f"tel:{t}:devices"


def index_field(g: str, n: str, d: str = "") -> str:
    return f"{g}/{n}/{d}"


def node_devices(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:nodedevs:{g}:{n}"


def aliases(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:alias:{g}:{n}"


def frames(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:frames:{g}:{n}"


def feed(t: Any, g: str, n: str, d: str, metric: str) -> str:
    return f"tenant:{t}:feed:{feed_id(g, n, d, metric)}"


def feed_id(g: str, n: str, d: str, metric: str) -> str:
    return f"{g}/{n}/{d}/{metric}"


def rate(t: Any, sec: int) -> str:
    return f"tel:{t}:mps:{sec}"


def stats(t: Any) -> str:
    return f"tel:{t}:stats"


def throttle(t: Any) -> str:
    return f"tel:{t}:throttle"


def latency(t: Any) -> str:
    return f"tel:{t}:lat"


def signals(t: Any, conn_id: Any) -> str:
    return f"tel:{t}:signals:{conn_id}"


def retired(t: Any, conn_id: Any) -> str:
    return f"tel:{t}:retired:{conn_id}"


def events(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:events:{g}:{n}"


def inspector(t: Any, conn_id: Any) -> str:
    return f"tel:{t}:insp:{conn_id}"


def dlq(t: Any, conn_id: Any) -> str:
    return f"tel:{t}:dlq:{conn_id}"


def dedupe(conn_id: Any) -> str:
    return f"tel:dd:{conn_id}"


def seq_state(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:seq:{g}:{n}"


def push_stream(conn_id: Any) -> str:
    return f"tel:push:{conn_id}"


def channel(t: Any, g: str, n: str) -> str:
    return f"tel:{t}:pub:{g}:{n}"


def tenant_channels(t: Any) -> str:
    return f"tel:{t}:pub:*"


def host_state(t: Any, host: str) -> str:
    return f"tel:{t}:state:{host}"


def replica(rid: str) -> str:
    return f"tel:ingest:replica:{rid}"


def lease(conn_id: Any) -> str:
    return f"tel:lease:{conn_id}"


def conn_status(conn_id: Any) -> str:
    return f"tel:conn:{conn_id}:status"


def command_rate(t: Any, g: str, n: str, sec: int) -> str:
    return f"tel:{t}:cmdrl:{g}:{n}:{sec}"


def quota_count(t: Any, sec: int) -> str:
    return f"tel:{t}:q:{sec}"


def sse_viewers(user_id: Any) -> str:
    return f"tel:sse:{user_id}"


def metric_field(name: str) -> str:
    return f"m:{name}"


def pack_metric(
    value: Any, dtype: str, ts: int, q: str, unit: str | None = None
) -> str:
    doc = {"v": value, "t": dtype, "ts": ts, "q": q}
    if unit:
        doc["u"] = unit
    return json.dumps(doc, default=str)


def unpack_metrics(h: dict[str, str], online: bool = True) -> list[dict[str, Any]]:
    """Metric rows from a device hash, sorted by name. Offline readings are stale."""
    out = []
    stale_ms = as_int(h.get("_stale_ms"))
    now = int(time.time() * 1000)
    for k, raw in h.items():
        if not k.startswith("m:"):
            continue
        try:
            m = json.loads(raw)
        except (TypeError, ValueError):
            continue
        q = m.get("q") or "good"
        if stale_ms and now - as_int(m.get("ts"), now) > stale_ms:
            q = "stale"
        row = {
            "name": k[2:],
            "value": m.get("v"),
            "type": m.get("t"),
            "ts": m.get("ts"),
            "quality": q if online else "stale",
        }
        if m.get("u"):
            row["unit"] = m["u"]
        out.append(row)
    out.sort(key=lambda r: r["name"])
    return out


def as_int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default
