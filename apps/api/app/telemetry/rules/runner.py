"""Runs what rules do, on the API pods.

The ingest only decides that a rule fired and adds it to a Redis stream. Here a
consumer group takes each firing exactly once across API replicas, records it,
runs its steps one after another and writes down what happened to each. A pod
that dies mid-firing leaves it pending, and another pod claims it a minute later.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.telemetry.rules import actions as X
from app.telemetry.rules.evaluator import STREAM

logger = logging.getLogger("telemetry.rules.runner")

GROUP = "rule-actions"
# run steps wait on agents, so a pod works on many firings at once
CONCURRENCY = 32
CLAIM_IDLE_MS = 60_000
_task: asyncio.Task | None = None
_stop = asyncio.Event()


def _redis() -> Any:
    from app.routers.telemetry import redis

    return redis()


async def _asset(db: Any, doc: dict[str, Any]) -> dict[str, Any] | None:
    from models.telemetry_rules import TelemetryAsset

    rows = (
        (
            await db.execute(
                select(TelemetryAsset).where(
                    TelemetryAsset.tenant_id == uuid.UUID(str(doc["tenant"])),
                    TelemetryAsset.grp == doc["group"],
                    TelemetryAsset.node == doc["node"],
                    TelemetryAsset.device.in_(["", doc.get("device") or ""]),
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    rows.sort(key=lambda a: 0 if a.device else 1)
    out: dict[str, Any] = {"tags": [], "fields": {}}
    for a in reversed(rows):
        out["type"] = a.asset_type or out.get("type")
        out["tags"] = sorted(set(out["tags"]) | set(a.tags or []))
        out["fields"] = {**out["fields"], **(a.fields or {})}
        out["location"] = a.location or out.get("location")
    return out


async def handle(doc: dict[str, Any]) -> None:
    from app.core.deps import async_session
    from models.telemetry_rules import TelemetryRule, TelemetryRuleFiring

    r = _redis()
    tenant = uuid.UUID(str(doc["tenant"]))
    rid = uuid.UUID(str(doc["rule_id"]))
    async with async_session() as db:
        rule = (
            await db.execute(
                select(TelemetryRule).where(
                    TelemetryRule.id == rid, TelemetryRule.tenant_id == tenant
                )
            )
        ).scalar_one_or_none()
        if doc.get("type") == "cleared":
            await db.execute(
                update(TelemetryRuleFiring)
                .where(
                    TelemetryRuleFiring.rule_id == rid,
                    TelemetryRuleFiring.grp == doc["group"],
                    TelemetryRuleFiring.node == doc["node"],
                    TelemetryRuleFiring.device == (doc.get("device") or ""),
                    TelemetryRuleFiring.cleared_at.is_(None),
                    TelemetryRuleFiring.status == "firing",
                )
                .values(cleared_at=datetime.now(timezone.utc), status="cleared")
            )
            await db.commit()
            await X.resolve_alert(db, r, doc)
            await db.commit()
            return
        if rule is None:
            return
        fid = uuid.UUID(str(doc["id"]))
        if await db.get(TelemetryRuleFiring, fid) is not None:
            return
        asset = await _asset(db, doc)
        ctx = X.context(doc, asset)
        ctx["window_s"] = X.window_of(rule.condition)
        if any(a.get("kind") == "run" for a in rule.actions or []):
            try:
                await X.add_history(ctx, tenant)
            except Exception as exc:  # noqa: BLE001
                logger.debug("firing history skipped: %s", exc)
        fired_at = datetime.fromtimestamp(
            (doc.get("ts") or doc.get("at")) / 1000.0, tz=timezone.utc
        )
        firing = TelemetryRuleFiring(
            id=fid,
            tenant_id=tenant,
            rule_id=rid,
            rule_name=rule.name,
            fired_at=fired_at,
            grp=doc["group"],
            node=doc["node"],
            device=doc.get("device") or "",
            signal=doc.get("signal"),
            value=doc.get("value"),
            detail=doc.get("detail") or "",
            status="test" if doc.get("test") else "firing",
            actions=[
                {
                    "kind": a.get("kind"),
                    "status": "pending",
                    "message": "Waiting to run",
                    "ref": None,
                }
                for a in rule.actions or []
            ],
            context=ctx,
            connection_id=doc.get("connection_id") or None,
        )
        db.add(firing)
        if not doc.get("test"):
            rule.last_fired_at = datetime.now(timezone.utc)
            rule.fire_count = (rule.fire_count or 0) + 1
        await db.commit()
        results: list[dict[str, Any]] = []
        for i, act in enumerate(rule.actions or []):
            if doc.get("test") and act.get("kind") == "command":
                results.append(
                    X._skipped("command", "A test firing never sends commands.")
                )
                continue
            if act.get("kind") == "run":
                # shows as running while the agent works, its answer lands when it is done
                firing.actions = (
                    results
                    + [{**firing.actions[i], "status": "running", "message": "Running"}]
                    + firing.actions[i + 1 :]
                )
                await db.commit()

            async def started(ref: dict[str, Any], i: int = i) -> None:
                # the running entry links its run while the agent works
                firing.actions = (
                    firing.actions[:i]
                    + [{**firing.actions[i], "ref": ref}]
                    + firing.actions[i + 1 :]
                )
                await db.commit()

            results.append(
                await X.run_action(
                    db, r, rule, doc, act, {**ctx, "steps": results}, started
                )
            )
            firing.actions = results + firing.actions[len(results) :]
            await db.commit()
        firing.actions = results
        if not doc.get("test"):
            await _completed(db, tenant, rule, firing, results)
        await db.commit()


async def _completed(
    db: Any, tenant: Any, rule: Any, firing: Any, results: list[dict[str, Any]]
) -> None:
    """telemetry.firing_completed, so an app hears what the steps did and said."""
    from app.services.events import emit

    try:
        await emit(
            db,
            tenant,
            "telemetry.firing_completed",
            {
                "firing_id": str(firing.id),
                "rule_id": str(rule.id),
                "rule": rule.name,
                "group": firing.grp,
                "node": firing.node,
                "device": firing.device,
                "asset": (firing.context or {}).get("asset"),
                "signal": firing.signal,
                "value": firing.value,
                "steps": [
                    {
                        "kind": s.get("kind"),
                        "status": s.get("status"),
                        "message": s.get("message"),
                        "output": s.get("output"),
                        "execution_id": (s.get("ref") or {}).get("execution_id"),
                        "duration_ms": s.get("duration_ms"),
                    }
                    for s in results
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("firing_completed event skipped: %s", exc)


async def _consume(r: Any, consumer: str) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    last_claim = 0.0
    last_refresh = 0.0

    async def one(mid: str, raw: str) -> None:
        async with sem:
            try:
                await handle(json.loads(raw))
            except Exception as exc:  # noqa: BLE001
                logger.warning("rule firing %s failed: %s", mid, exc)
            finally:
                try:
                    await r.xack(STREAM, GROUP, mid)
                    # acked entries are deleted so the stream never grows
                    await r.xdel(STREAM, mid)
                except Exception:  # noqa: BLE001
                    pass

    pending: set[asyncio.Task] = set()
    while not _stop.is_set():
        batch: list[tuple[str, dict]] = []
        try:
            resp = await r.xreadgroup(
                GROUP, consumer, {STREAM: ">"}, count=CONCURRENCY * 2, block=2000
            )
            for _, msgs in resp or []:
                batch.extend(msgs)
            now = time.monotonic()
            if now - last_claim > 30:
                last_claim = now
                got = await r.xautoclaim(
                    STREAM, GROUP, consumer, CLAIM_IDLE_MS, "0-0", count=50
                )
                if got and len(got) > 1:
                    batch.extend(got[1] or [])
            if now - last_refresh > 60 and await r.set(
                "tel:rules:alerts:refresh", consumer, nx=True, ex=55
            ):
                last_refresh = now
                from app.core.deps import async_session

                async with async_session() as db:
                    await X.refresh_alerts(db, r)
                    await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if "NOGROUP" in str(exc):
                await _group(r)
            else:
                logger.debug("rule stream read failed: %s", exc)
                await asyncio.sleep(2)
            continue
        for mid, fields in batch:
            raw = (fields or {}).get("doc")
            if not raw:
                await r.xack(STREAM, GROUP, mid)
                await r.xdel(STREAM, mid)
                continue
            t = asyncio.create_task(one(mid, raw))
            pending.add(t)
            t.add_done_callback(pending.discard)


async def _group(r: Any) -> None:
    try:
        await r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001
        if "BUSYGROUP" not in str(exc):
            raise


async def run_forever() -> None:
    consumer = f"{socket.gethostname()}-{os.getpid()}"
    while not _stop.is_set():
        try:
            r = _redis()
            await _group(r)
            await _consume(r, consumer)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("rule runner restarting: %s", exc)
            await asyncio.sleep(5)


def start() -> None:
    """Called once from the API startup. TELEMETRY_RULE_RUNNER=0 turns it off on a pod."""
    global _task
    if os.environ.get("TELEMETRY_RULE_RUNNER", "1") == "0" or _task is not None:
        return
    _stop.clear()
    _task = asyncio.create_task(run_forever())


async def stop() -> None:
    global _task
    _stop.set()
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _task = None


async def test_fire(rule: Any, doc: dict[str, Any]) -> str:
    """Queue a firing marked as a test. Its steps run, commands never do."""
    doc = {**doc, "test": True, "id": str(uuid.uuid4())}
    await _redis().xadd(
        STREAM, {"doc": json.dumps(doc, default=str)}, maxlen=10_000, approximate=True
    )
    return doc["id"]
