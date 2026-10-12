"""Replay a rule over stored history: "this would have fired 3 times in the last hour".

The replay runs the same state machines as the live evaluator, over the samples
TimescaleDB kept (at most one a second per signal), so what it shows is what the
rule would have done.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.telemetry.rules.conditions import Sample, compile_condition, fmt, step

MAX_NODES = 25
MAX_ROWS = 200_000
SERIES_POINTS = 600
TRACK_POINTS = 800


def _thin(points: list[Any], n: int) -> list[Any]:
    if len(points) <= n:
        return points
    stride = len(points) / n
    out = [points[int(i * stride)] for i in range(n)]
    if out[-1] is not points[-1]:
        out[-1] = points[-1]
    return out


async def fetch(
    pool: Any,
    tenant: str,
    targets: list[tuple[str, str, str | None]],
    signals: list[str] | None,
    frm: datetime,
    to: datetime,
) -> tuple[list[Any], bool]:
    """Raw samples for the targets, a None device meaning every part. Second value says it was cut short."""
    rows: list[Any] = []
    cut = False
    async with pool.acquire() as c:
        for g, n, d in targets[:MAX_NODES]:
            args: list[Any] = [uuid.UUID(tenant), g, n, frm, to]
            where = (
                "tenant_id = $1 AND grp = $2 AND node = $3 AND time >= $4 AND time < $5"
            )
            if d is not None:
                args.append(d)
                where += f" AND device = ${len(args)}"
            if signals:
                args.append(signals)
                where += f" AND metric = ANY(${len(args)}::text[])"
            room = MAX_ROWS - len(rows)
            if room <= 0:
                cut = True
                break
            got = await c.fetch(
                f"SELECT time, grp, node, device, metric, num, txt FROM telemetry_samples "
                f"WHERE {where} ORDER BY time LIMIT {room + 1}",
                *args,
            )
            if len(got) > room:
                cut = True
                got = got[:room]
            rows.extend(got)
    return rows, cut or len(targets) > MAX_NODES


async def fetch_times(
    pool: Any,
    tenant: str,
    targets: list[tuple[str, str, str | None]],
    signal: str | None,
    frm: datetime,
    to: datetime,
) -> list[Any]:
    out: list[Any] = []
    async with pool.acquire() as c:
        for g, n, d in targets[:MAX_NODES]:
            args: list[Any] = [uuid.UUID(tenant), g, n, frm, to]
            where = (
                "tenant_id = $1 AND grp = $2 AND node = $3 AND time >= $4 AND time < $5"
            )
            if d is not None and d != "":
                args.append(d)
                where += f" AND device = ${len(args)}"
            if signal:
                args.append(signal)
                where += f" AND metric = ${len(args)}"
            got = await c.fetch(
                f"SELECT time_bucket(INTERVAL '1 second', time) AS t, max(device) AS device FROM telemetry_samples "
                f"WHERE {where} GROUP BY 1 ORDER BY 1 LIMIT 100000",
                *args,
            )
            for r in got:
                out.append((g, n, "" if d in (None, "") else d, r["t"]))
    return out


def _ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def replay(
    rule: dict[str, Any],
    rows: list[Any],
    keep: Any = None,
    names: dict[str, str] | None = None,
    since_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Firings per asset key from history rows (time, grp, node, device, metric, num, txt).

    Rows before since_ms only warm the state up, as a baseline needs."""
    cond = compile_condition(rule["condition"])
    cooldown_ms = int(rule.get("cooldown_s") or 0) * 1000
    names = names or {}
    per: dict[str, dict[str, Any]] = {}
    states: dict[str, dict[str, Any]] = {}
    coords: dict[str, dict[str, float]] = {}
    for r in rows:
        g, n, d = r["grp"], r["node"], r["device"] or ""
        if keep is not None and not keep(g, n, d):
            continue
        k = f"{g}/{n}/{d}"
        doc = per.get(k)
        if doc is None:
            doc = per[k] = {
                "key": k,
                "group": g,
                "node": n,
                "device": d,
                "name": names.get(k) or (f"{names.get(f'{g}/{n}/') or n} {d}".strip()),
                "firings": [],
                "clears": [],
                "series": {},
                "track": [],
                "samples": 0,
            }
        t = _ms(r["time"])
        v = r["num"] if r["num"] is not None else r["txt"]
        shown = since_ms is None or t >= since_ms
        if shown:
            doc["samples"] += 1
        if r["num"] is not None and shown:
            doc["series"].setdefault(r["metric"], []).append([t, r["num"]])
        st = states.setdefault(k, {})
        if cond.kind == "geofence":
            cc = coords.setdefault(k, {})
            if r["metric"] == cond.x_signal:
                cc["x"] = r["num"]
            elif r["metric"] == cond.y_signal:
                cc["y"] = r["num"]
            if cc.get("x") is None or cc.get("y") is None:
                continue
            doc["track"].append([cc["x"], cc["y"], t])
            s = Sample(None, t, r["metric"], {"x": cc["x"], "y": cc["y"]})
        else:
            s = Sample(v, t, r["metric"])
        o = step(cond, st, s, cooldown_ms)
        if not shown:
            continue
        if o.fired:
            doc["firings"].append({"t": t, "value": o.value, "words": o.words})
        elif o.cleared:
            doc["clears"].append(t)
    return _finish(per)


def replay_stale(
    rule: dict[str, Any],
    times: list[Any],
    to: datetime,
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Gaps longer than the rule's seconds, from sample times per key."""
    secs = float(rule["condition"]["seconds"])
    cooldown_ms = int(rule.get("cooldown_s") or 0) * 1000
    names = names or {}
    by: dict[str, list[int]] = {}
    meta: dict[str, tuple[str, str, str]] = {}
    for g, n, d, t in times:
        k = f"{g}/{n}/{d}"
        by.setdefault(k, []).append(_ms(t))
        meta[k] = (g, n, d)
    end = _ms(to)
    per = {}
    for k, ts in by.items():
        g, n, d = meta[k]
        ts.sort()
        doc = {
            "key": k,
            "group": g,
            "node": n,
            "device": d,
            "name": names.get(k) or n,
            "firings": [],
            "clears": [],
            "series": {"data": [[t, 1] for t in ts]},
            "track": [],
            "samples": len(ts),
        }
        last_fire = None
        edges = list(zip(ts, ts[1:])) + [(ts[-1], None)]
        for a, b in edges:
            gap = (b if b is not None else end) - a
            if gap / 1000.0 > secs:
                at = a + int(secs * 1000)
                if last_fire is None or at - last_fire >= cooldown_ms:
                    doc["firings"].append(
                        {
                            "t": at,
                            "value": round(gap / 1000.0, 1),
                            "words": f"sent nothing for {fmt(round(gap / 1000.0))} s",
                        }
                    )
                    last_fire = at
                if b is not None:
                    doc["clears"].append(b)
        per[k] = doc
    return _finish(per)


def _finish(per: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for doc in per.values():
        series = []
        stats = {}
        for sig, pts in doc["series"].items():
            vals = [p[1] for p in pts]
            stats[sig] = {
                "min": min(vals),
                "max": max(vals),
                "last": vals[-1],
                "n": len(vals),
            }
            series.append({"signal": sig, "points": _thin(pts, SERIES_POINTS)})
        doc["series"] = series
        doc["stats"] = stats
        doc["track"] = _thin(doc["track"], TRACK_POINTS)
        out.append(doc)
    out.sort(key=lambda d: (-len(d["firings"]), d["key"]))
    return out


def summary(rule: dict[str, Any], assets: list[dict[str, Any]], hours: float) -> str:
    span = "hour" if hours == 1 else f"{fmt(hours)} hours"
    total = sum(len(a["firings"]) for a in assets)
    if not assets:
        return f"No history for this in the last {span}, so there is nothing to replay yet. Check the signal and the asset, or wait for data."
    if total == 0:
        sig = (rule.get("condition") or {}).get("signal")
        best = None
        for a in assets:
            s = (a.get("stats") or {}).get(sig or "")
            if s and (best is None or s["max"] > best["max"]):
                best = s
        tail = (
            f" {sig} ranged from {fmt(best['min'])} to {fmt(best['max'])}."
            if best
            else ""
        )
        return f"This rule would not have fired in the last {span}.{tail}"
    hit = [a for a in assets if a["firings"]]
    where = ", ".join(f"{a['name']} ({len(a['firings'])})" for a in hit[:4])
    more = f" and {len(hit) - 4} more" if len(hit) > 4 else ""
    times = "once" if total == 1 else "twice" if total == 2 else f"{total} times"
    return f"This rule would have fired {times} in the last {span}, on {where}{more}."


def now() -> datetime:
    return datetime.now(timezone.utc)
