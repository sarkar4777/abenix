"""device_state: the latest telemetry a machine reported, read from the store the ingest keeps.

The telemetry ingest writes each Sparkplug B device into the Redis hash
tel:{tenant}:{group}:{node}:{device}. This tool only reads it, so it costs a
round trip to Redis and never touches the broker.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from engine import credentials, governance
from engine.tools import _telemetry_api as api
from engine.tools.base import READ_ONLY, BaseTool, ConfigField, ToolResult


def _tenant() -> str:
    run = governance.current()
    if run is not None and run.tenant_id:
        return str(run.tenant_id)
    return credentials.current_tenant() or os.environ.get("TENANT_ID", "").strip()


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _wanted(name: str, filters: list[str]) -> bool:
    if not filters:
        return True
    low = name.lower()
    for f in filters:
        fl = f.lower()
        if fl.endswith("*"):
            if low.startswith(fl[:-1]):
                return True
        elif low == fl or low.startswith(fl.rstrip("/") + "/"):
            return True
    return False


def shape(
    h: dict[str, str],
    device: str,
    filters: list[str],
    now_ms: int,
    stale_s: int,
    limit: int,
    node_online: bool = True,
) -> dict[str, Any]:
    online = h.get("_online") == "1" and node_online
    metrics = []
    for k, raw in sorted(h.items()):
        if not k.startswith("m:") or not _wanted(k[2:], filters):
            continue
        try:
            m = json.loads(raw)
        except (TypeError, ValueError):
            continue
        ts = _int(m.get("ts")) or None
        age = round((now_ms - ts) / 1000.0, 1) if ts else None
        q = m.get("q") or "good"
        if not online or (age is not None and age > stale_s):
            q = "stale"
        metrics.append(
            {
                "name": k[2:],
                "value": m.get("v"),
                "type": m.get("t"),
                "ts": ts,
                "age_seconds": age,
                "quality": q,
            }
        )
        if len(metrics) >= limit:
            break
    return {
        "device": device,
        "online": online,
        "last_seen": _int(h.get("_last_seen")) or None,
        "birth_at": _int(h.get("_birth_at")) or None,
        "offline_at": _int(h.get("_offline_at")) or None,
        "seq_gaps": _int(h.get("_seq_gaps")),
        "msgs_per_sec": _int(h.get("_mps")),
        "metrics": metrics,
    }


class DeviceStateTool(BaseTool):
    name = "device_state"
    risk_tier = "low"
    effect = READ_ONLY
    description = (
        "Read the latest readings of one or more assets: whether each is online, when it "
        "was last seen, and each signal's value, type, time and quality. Name assets by key "
        "or display name from asset_search (asset, or assets for several), or every asset "
        "of a type or tag with where, or by group and node. Optionally one device (a part, "
        "like an ECU on its bus) and a metrics filter such as ['Engine/', 'Safety/Hold']. "
        "Without a device you get the asset and all its parts."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            **api.ASSET_PROPS,
            "group": {
                "type": "string",
                "description": "Group of the asset, for example groundwork. Not needed with asset.",
            },
            "node": {
                "type": "string",
                "description": "The asset id, for example ipc-ex1. Not needed with asset.",
            },
            "device": {
                "type": "string",
                "description": "Device id on the node, for example engine. Leave out for all devices.",
            },
            "metrics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Metric names or prefixes to keep, for example ['Engine/', 'GNSS/X_m']. A trailing * also works.",
            },
        },
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "group": {"type": "string"},
            "node": {"type": "string"},
            "online": {"type": "boolean"},
            "devices": {"type": "array"},
        },
    }
    config_fields = (
        ConfigField(
            key="TELEMETRY_STALE_SECONDS",
            label="Stale after (seconds)",
            kind="int",
            required=False,
            group="Telemetry",
            description="A reading older than this is reported with quality stale.",
            default="30",
        ),
        ConfigField(
            key="TELEMETRY_MAX_METRICS",
            label="Most metrics per device",
            kind="int",
            required=False,
            group="Telemetry",
            description="Cap on the metrics returned for one device, to keep answers short.",
            default="200",
        ),
    )

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id or ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        device = arguments.get("device")
        device = str(device).strip() if device is not None else None
        filters = arguments.get("metrics") or []
        if isinstance(filters, str):
            filters = [f.strip() for f in filters.split(",") if f.strip()]
        filters = [str(f) for f in filters][:50]
        tenant = self.tenant_id or _tenant()
        if not tenant:
            return ToolResult(
                content="No workspace for this run, so there is nothing to read",
                is_error=True,
            )
        extra: dict[str, Any] = {}
        if api.wants_assets(arguments):
            found, problem, extra = await api.resolve(arguments)
            if problem:
                return ToolResult(content=problem, is_error=True)
            targets = [
                (
                    a["group"],
                    a["node"],
                    a.get("device") or device,
                    a.get("name"),
                    a.get("key"),
                )
                for a in found
            ]
        else:
            group = str(arguments.get("group") or "").strip()
            node = str(arguments.get("node") or "").strip()
            if not group or not node:
                return ToolResult(
                    content="Name the asset: asset or assets (keys or names from asset_search), or group and node.",
                    is_error=True,
                )
            targets = [(group, node, device, None, None)]
        stale_s = _int(self.cfg("TELEMETRY_STALE_SECONDS"), 30) or 30
        limit = max(1, min(2000, _int(self.cfg("TELEMETRY_MAX_METRICS"), 200)))

        try:
            import redis.asyncio as aioredis
        except ImportError:
            return ToolResult(content="redis client not installed", is_error=True)
        r = aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        docs = []
        try:
            for g, n, d, name, key in targets:
                api.note_read(g, n, d, filters)
                doc = await read_one(r, tenant, g, n, d, filters, stale_s, limit)
                if name:
                    doc["name"] = name
                if key:
                    doc["key"] = key
                docs.append(doc)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                content=f"telemetry store read failed: {exc}", is_error=True
            )
        finally:
            try:
                await r.aclose()
            except Exception:  # noqa: BLE001
                pass
        if len(docs) == 1 and not (arguments.get("assets") or arguments.get("where")):
            out = docs[0]
            return ToolResult(
                content=json.dumps(out, default=str),
                metadata={
                    "found": out.get("found"),
                    "online": out.get("online"),
                    "devices": len(out.get("devices") or []),
                },
            )
        multi: dict[str, Any] = {"assets": docs, "count": len(docs)}
        for k in ("unknown", "ambiguous", "truncated"):
            if extra.get(k):
                multi[k] = extra[k]
        return ToolResult(
            content=json.dumps(multi, default=str),
            metadata={
                "assets": len(docs),
                "online": sum(1 for x in docs if x.get("online")),
            },
        )


async def read_one(
    r: Any,
    tenant: str,
    group: str,
    node: str,
    device: str | None,
    filters: list[str],
    stale_s: int,
    limit: int,
) -> dict[str, Any]:
    """One asset and its parts from the latest-value store."""
    base = f"tel:{tenant}:{group}:{node}:"
    members = await r.smembers(f"tel:{tenant}:nodedevs:{group}:{node}")
    devs = sorted(d for d in (members or []) if d)
    if device is not None:
        devs = [device] if device else []
    pipe = r.pipeline(transaction=False)
    pipe.hgetall(base)
    for d in devs:
        pipe.hgetall(base + d)
    res = await pipe.execute()
    node_h, dev_hs = res[0] or {}, res[1:]
    if not node_h and not any(dev_hs):
        return {
            "group": group,
            "node": node,
            "found": False,
            "message": f"No machine called {node} in group {group}. Machines appear when they send their birth message.",
        }
    now_ms = int(time.time() * 1000)
    node_doc = shape(node_h, "", filters, now_ms, stale_s, limit)
    out: dict[str, Any] = {
        "group": group,
        "node": node,
        "found": True,
        "online": node_doc["online"],
        "last_seen": node_doc["last_seen"],
        "birth_at": node_doc["birth_at"],
        "offline_at": node_doc["offline_at"],
        "seq_gaps": node_doc["seq_gaps"],
        "metrics": node_doc["metrics"],
        "devices": [],
    }
    for d, h in zip(devs, dev_hs):
        if not h:
            if device:
                out["devices"].append({"device": d, "found": False})
            continue
        out["devices"].append(
            shape(h, d, filters, now_ms, stale_s, limit, node_doc["online"])
        )
    return out
