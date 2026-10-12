"""Forgetting devices: their live state goes, their history stays, and they come back if they report."""

from __future__ import annotations

import fnmatch
import json
import time
from typing import Any

from app.telemetry import keys as K
from app.telemetry import reads

BULK_MAX = 2000
SAMPLE = 20


def _offline_since(row: dict[str, Any]) -> int:
    # silence counts from the last message, a source without births is marked offline later
    marks = [int(v) for v in (row.get("last_seen"), row.get("offline_at")) if v]
    return min(marks) if marks else 0


def candidates(
    rows: list[dict[str, Any]],
    scope: Any,
    *,
    offline_for_s: int,
    group: str = "",
    node_glob: str = "",
    connection_id: str = "",
    now_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Offline rows past the cut-off that this person can see, oldest first."""
    cut = (now_ms or int(time.time() * 1000)) - offline_for_s * 1000
    out = []
    for r in rows:
        if r["online"] or not scope.sees(r.get("connection_id")):
            continue
        if group and r["group"] != group:
            continue
        if node_glob and not fnmatch.fnmatchcase(r["node"], node_glob):
            continue
        if connection_id and r.get("connection_id") != connection_id:
            continue
        since = _offline_since(r)
        if since and since > cut:
            continue
        out.append(r)
    out.sort(key=lambda r: (_offline_since(r), r["group"], r["node"], r["device"]))
    return out


async def forget(
    r: Any, tenant: Any, items: list[tuple[str, str, str]]
) -> list[dict[str, str]]:
    """Removes each device's live state. A device "" takes the whole asset with its parts."""
    t = str(tenant)
    targets: list[tuple[str, str, str]] = []
    whole: set[tuple[str, str]] = set()
    for g, n, d in items:
        if d:
            targets.append((g, n, d))
            continue
        whole.add((g, n))
        parts = sorted(await r.smembers(K.node_devices(t, g, n)) or [])
        targets.extend((g, n, p) for p in ["", *[p for p in parts if p]])
    seen: set[tuple[str, str, str]] = set()
    targets = [x for x in targets if not (x in seen or seen.add(x))]
    if not targets:
        return []
    pipe = r.pipeline(transaction=False)
    for g, n, d in targets:
        pipe.hget(K.device(t, g, n, d), "_conn")
        pipe.hexists(K.index(t), K.index_field(g, n, d))
    got = await pipe.execute()
    conns = {x: got[i * 2] for i, x in enumerate(targets)}
    known = {x for i, x in enumerate(targets) if got[i * 2 + 1]}
    aliases: dict[tuple[str, str], dict[str, str]] = {}
    for g, n in {(g, n) for g, n, _ in targets if (g, n) not in whole}:
        aliases[(g, n)] = await r.hgetall(K.aliases(t, g, n)) or {}
    retired: dict[str, list[str]] = {}
    for cid in {c for c in conns.values() if c}:
        retired[cid] = list(await r.hkeys(K.retired(t, cid)) or [])
    pipe = r.pipeline(transaction=False)
    for g, n, d in targets:
        pipe.delete(K.device(t, g, n, d))
        pipe.hdel(K.index(t), K.index_field(g, n, d))
        if d:
            pipe.srem(K.node_devices(t, g, n), d)
        cid = conns.get((g, n, d))
        prefix = f"{g}/{n}/{d}/"
        gone = [f for f in retired.get(cid or "", []) if f.startswith(prefix)]
        if gone:
            pipe.hdel(K.retired(t, cid), *gone)
        if (g, n) not in whole and d:
            drop = []
            for a, raw in aliases.get((g, n), {}).items():
                try:
                    if json.loads(raw)[0] == d:
                        drop.append(a)
                except (ValueError, IndexError, TypeError):
                    continue
            if drop:
                pipe.hdel(K.aliases(t, g, n), *drop)
    for g, n in whole:
        for key in (
            K.aliases(t, g, n),
            K.node_devices(t, g, n),
            K.frames(t, g, n),
            K.events(t, g, n),
            K.seq_state(t, g, n),
        ):
            pipe.delete(key)
    pipe.publish(K.FORGOTTEN, json.dumps({"t": t, "items": [list(x) for x in targets]}))
    await pipe.execute()
    return [
        {"group": g, "node": n, "device": d}
        for g, n, d in targets
        if (g, n, d) in known
    ]


async def forget_matching(
    r: Any,
    tenant: Any,
    scope: Any,
    *,
    offline_for_s: int,
    group: str = "",
    node_glob: str = "",
    connection_id: str = "",
    limit: int = BULK_MAX,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = await reads.all_devices(r, tenant)
    found = candidates(
        rows,
        scope,
        offline_for_s=offline_for_s,
        group=group,
        node_glob=node_glob,
        connection_id=connection_id,
    )
    sample = [
        {
            k: x.get(k)
            for k in (
                "group",
                "node",
                "device",
                "offline_at",
                "last_seen",
                "connection_id",
            )
        }
        for x in found[:SAMPLE]
    ]
    out: dict[str, Any] = {
        "dry_run": dry_run,
        "matched": len(found),
        "forgotten": 0,
        "remaining": len(found),
        "sample": sample,
        "history_kept": True,
    }
    if dry_run or not found:
        return out
    batch = found[: max(1, min(limit, BULK_MAX))]
    # a whole asset goes only when the asset itself matched, its parts go one by one
    picked = {(x["group"], x["node"], x["device"]) for x in batch}
    items = [k for k in picked if not k[2] or (k[0], k[1], "") not in picked]
    done = await forget(r, tenant, items)
    left = len(
        candidates(
            await reads.all_devices(r, tenant),
            scope,
            offline_for_s=offline_for_s,
            group=group,
            node_glob=node_glob,
            connection_id=connection_id,
        )
    )
    out.update({"forgotten": len(done), "remaining": left})
    return out
