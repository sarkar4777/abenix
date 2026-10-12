"""signal_history: how a telemetry signal moved over a time range, read from TimescaleDB.

The telemetry ingest keeps history in telemetry_samples with 1 minute and 1 hour
continuous aggregates. This tool picks the raw table or an aggregate from the
range and step, the same way the telemetry history API does.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from engine import credentials, governance
from engine.tools import _telemetry_api as api
from engine.tools.base import READ_ONLY, BaseTool, ConfigField, ToolResult

STEPS = (1, 5, 10, 30, 60, 300, 600, 1800, 3600, 21600, 86400)


def _tenant() -> str:
    run = governance.current()
    if run is not None and run.tenant_id:
        return str(run.tenant_id)
    return credentials.current_tenant() or os.environ.get("TENANT_ID", "").strip()


def _int(v: Any, default: int) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def parse_span(v: str) -> int:
    s = v.strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if s and s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(float(s))


def parse_time(v: Any, default: datetime, now: datetime) -> datetime:
    if v in (None, ""):
        return default
    if isinstance(v, (int, float)):
        f = float(v)
        return datetime.fromtimestamp(f / 1000.0 if f > 1e11 else f, tz=timezone.utc)
    s = str(v).strip()
    if s.lower() == "now":
        return now
    if s.startswith("-") or s.lower().startswith("now-"):
        return now - timedelta(
            seconds=parse_span(s.lower().replace("now", "").lstrip("-"))
        )
    if s.lstrip("-").isdigit():
        return parse_time(int(s), default, now)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def pick_step(span_s: float, max_points: int, asked: int | None) -> int:
    want = max(1.0, span_s / max(1, max_points))
    if asked and asked >= want:
        return asked
    for s in STEPS:
        if s >= want:
            return s
    return STEPS[-1]


def pick_source(step_s: int, span_s: float) -> str:
    if step_s >= 3600 or span_s > 14 * 86400:
        return "telemetry_samples_1h"
    if step_s >= 60 or span_s > 6 * 3600:
        return "telemetry_samples_1m"
    return "telemetry_samples"


def summarise(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    nums = [p for p in points if p.get("avg") is not None]
    if not nums:
        return None
    total_n = sum(p["n"] for p in nums) or 1
    return {
        "first": nums[0]["avg"],
        "last": nums[-1]["avg"],
        "min": min(p["min"] for p in nums),
        "max": max(p["max"] for p in nums),
        "mean": sum(p["avg"] * p["n"] for p in nums) / total_n,
        "samples": sum(p["n"] for p in nums),
        "max_at": max(nums, key=lambda p: p["max"])["t"],
        "min_at": min(nums, key=lambda p: p["min"])["t"],
    }


class SignalHistoryTool(BaseTool):
    name = "signal_history"
    risk_tier = "low"
    effect = READ_ONLY
    description = (
        "Read how a telemetry signal moved over a time range: bucketed average, minimum, "
        "maximum and sample count per step, plus a summary (first, last, min, max, mean, when "
        "the peak was). Name the asset by key or display name from asset_search (asset, or assets "
        "for several, or where for every asset of a type or tag), or by group and node, the part "
        "(device) when the signal is on one, and the signal names, for example "
        "'Hydraulics/Pump1Pressure_bar'. Ranges are "
        "ISO times, epoch milliseconds or relative like '-1h' to 'now'. Use device_state for the "
        "latest values and this tool for what happened before."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            **api.ASSET_PROPS,
            "group": {
                "type": "string",
                "description": "Group of the asset, for example groundwork.",
            },
            "node": {
                "type": "string",
                "description": "The asset, for example ipc-ex1.",
            },
            "device": {
                "type": "string",
                "description": "The part the signal is on, for example hydraulics. Leave empty for the asset's own signals.",
            },
            "signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Signal names, up to 10, for example ['Hydraulics/Pump1Pressure_bar'].",
            },
            "from": {
                "type": "string",
                "description": "Start, like -1h, -15m or an ISO time. Default one hour ago.",
            },
            "to": {
                "type": "string",
                "description": "End, like now or an ISO time. Default now.",
            },
            "step": {
                "type": "string",
                "description": "Bucket size like 10s, 1m or 1h. Picked from the range when left out.",
            },
        },
        "required": ["signals"],
    }
    output_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "series": {"type": "array"},
            "step_seconds": {"type": "integer"},
            "source": {"type": "string"},
        },
    }
    config_fields = (
        ConfigField(
            key="TELEMETRY_HISTORY_MAX_POINTS",
            label="Most points per signal",
            kind="int",
            required=False,
            group="Telemetry",
            description="Longer ranges are bucketed so each signal returns at most this many points.",
            default="300",
        ),
        ConfigField(
            key="TELEMETRY_HISTORY_MAX_DAYS",
            label="Longest range (days)",
            kind="int",
            required=False,
            group="Telemetry",
            description="Requests for a longer range are refused, to keep answers quick.",
            default="30",
        ),
    )

    def __init__(self, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id or ""

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        group = str(arguments.get("group") or "").strip()
        node = str(arguments.get("node") or "").strip()
        device = str(arguments.get("device") or "").strip()
        sigs = arguments.get("signals") or arguments.get("signal") or []
        if isinstance(sigs, str):
            sigs = [s.strip() for s in sigs.split(",") if s.strip()]
        sigs = [str(s) for s in sigs][:10]
        named = api.wants_assets(arguments)
        if not sigs or (not named and (not group or not node)):
            return ToolResult(
                content="Name the asset (asset or assets from asset_search, or group and node) and at least one signal.",
                is_error=True,
            )
        tenant = self.tenant_id or _tenant()
        if not tenant:
            return ToolResult(
                content="No workspace for this run, so there is nothing to read",
                is_error=True,
            )
        now = datetime.now(timezone.utc)
        try:
            to = parse_time(arguments.get("to"), now, now)
            frm = parse_time(arguments.get("from"), to - timedelta(hours=1), now)
            asked = (
                parse_span(str(arguments["step"])) if arguments.get("step") else None
            )
        except (TypeError, ValueError):
            return ToolResult(
                content="from and to must be ISO times, epoch milliseconds or relative like -1h, and step like 10s or 1m",
                is_error=True,
            )
        if frm >= to:
            return ToolResult(content="from must be before to", is_error=True)
        span = (to - frm).total_seconds()
        max_days = max(1, _int(self.cfg("TELEMETRY_HISTORY_MAX_DAYS"), 30))
        if span > max_days * 86400:
            return ToolResult(
                content=f"Ask for at most {max_days} days at a time", is_error=True
            )
        max_points = max(
            10, min(5000, _int(self.cfg("TELEMETRY_HISTORY_MAX_POINTS"), 300))
        )
        step = pick_step(span, max_points, asked)
        source = pick_source(step, span)
        url = (os.environ.get("TSDB_URL") or "").replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        if not url:
            return ToolResult(
                content="Telemetry history is not set up on this platform (TSDB_URL is empty)",
                is_error=True,
            )
        extra: dict[str, Any] = {}
        if named:
            found, problem, extra = await api.resolve(arguments)
            if problem:
                return ToolResult(content=problem, is_error=True)
            targets = [
                (
                    x["group"],
                    x["node"],
                    x.get("device") or device,
                    x.get("name"),
                    x.get("key"),
                )
                for x in found
            ]
        else:
            targets = [(group, node, device, None, None)]
        if source == "telemetry_samples":
            sql = """SELECT metric, time_bucket(make_interval(secs => $7), time) AS b,
                         avg(num) AS avg, min(num) AS min, max(num) AS max, count(*) AS n, last(txt, time) AS txt
                     FROM telemetry_samples
                     WHERE tenant_id = $1 AND grp = $2 AND node = $3 AND device = $4
                       AND metric = ANY($5::text[]) AND time >= $6 AND time < $8
                     GROUP BY metric, b ORDER BY metric, b"""
        else:
            sql = f"""SELECT metric, time_bucket(make_interval(secs => $7), bucket) AS b,
                          sum(avg * n) / NULLIF(sum(n) FILTER (WHERE avg IS NOT NULL), 0) AS avg,
                          min(min) AS min, max(max) AS max, sum(n)::bigint AS n, NULL::text AS txt
                      FROM {source}
                      WHERE tenant_id = $1 AND grp = $2 AND node = $3 AND device = $4
                        AND metric = ANY($5::text[]) AND bucket >= $6 AND bucket < $8
                      GROUP BY metric, b ORDER BY metric, b"""
        fetched: list[list[Any]] = []
        try:
            import asyncpg

            conn = await asyncpg.connect(url, timeout=10)
            try:
                for g, n, d, _, _ in targets:
                    api.note_read(g, n, d, sigs)
                    fetched.append(
                        await conn.fetch(
                            sql,
                            uuid.UUID(tenant),
                            g,
                            n,
                            d or "",
                            sigs,
                            frm,
                            float(step),
                            to,
                            timeout=20,
                        )
                    )
            finally:
                await conn.close()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                content=f"telemetry history read failed: {exc}", is_error=True
            )
        label = {
            "telemetry_samples": "raw",
            "telemetry_samples_1m": "1 minute",
            "telemetry_samples_1h": "1 hour",
        }[source]
        docs = []
        points = 0
        for (g, n, d, name, key), rows in zip(targets, fetched):
            doc = shape_rows(rows, sigs)
            points += sum(len(x["points"]) for x in doc)
            one: dict[str, Any] = {"group": g, "node": n, "device": d or ""}
            if name:
                one["name"] = name
            if key:
                one["key"] = key
            one["series"] = doc
            docs.append(one)
        common = {
            "from": frm.isoformat(),
            "to": to.isoformat(),
            "step_seconds": step,
            "source": label,
        }
        meta = {"points": points, "step_seconds": step}
        if len(docs) == 1 and not (arguments.get("assets") or arguments.get("where")):
            out = {**{k: v for k, v in docs[0].items() if k != "series"}, **common}
            out["series"] = docs[0]["series"]
            return ToolResult(content=json.dumps(out, default=str), metadata=meta)
        multi: dict[str, Any] = {**common, "assets": docs, "count": len(docs)}
        for k in ("unknown", "ambiguous", "truncated"):
            if extra.get(k):
                multi[k] = extra[k]
        return ToolResult(content=json.dumps(multi, default=str), metadata=meta)


def shape_rows(rows: list[Any], sigs: list[str]) -> list[dict[str, Any]]:
    series: dict[str, list[dict[str, Any]]] = {s: [] for s in sigs}
    for r in rows:
        p = {
            "t": r["b"].isoformat(),
            "avg": r["avg"],
            "min": r["min"],
            "max": r["max"],
            "n": int(r["n"] or 0),
        }
        if r["txt"] is not None:
            p["text"] = r["txt"]
        series.setdefault(r["metric"], []).append(p)
    return [
        {
            "signal": s,
            "summary": summarise(pts),
            "points": pts,
            **(
                {}
                if pts
                else {
                    "note": "No history for this signal in the range. Check the name, the part, or widen the range."
                }
            ),
        }
        for s, pts in series.items()
    ]
