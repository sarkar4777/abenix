"""Outbound platform events: catalogue, transactional emit, fan-out to subscriptions, and delivery."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CATALOG: dict[str, dict[str, Any]] = {
    "execution.completed": {
        "description": "An agent or pipeline run finished",
        "sample": {
            "execution_id": "…",
            "agent_id": "…",
            "status": "completed",
            "duration_ms": 1200,
            "cost": 0.01,
            "risk_tier": "low",
        },
    },
    "execution.failed": {
        "description": "An agent or pipeline run failed",
        "sample": {
            "execution_id": "…",
            "agent_id": "…",
            "status": "failed",
            "failure_code": "TOOL_ERROR",
        },
    },
    "approval.requested": {
        "description": "Something is waiting for sign-off",
        "sample": {
            "approval_id": "…",
            "title": "Publish remote surcharge version 4",
            "gate_kind": "decision_publish",
            "required_signoffs": 1,
        },
    },
    "approval.resolved": {
        "description": "A sign-off was approved, denied or expired",
        "sample": {
            "approval_id": "…",
            "status": "approved",
            "gate_kind": "decision_publish",
        },
    },
    "decision.proposed": {
        "description": "A new decision version was proposed",
        "sample": {
            "decision_key": "freight.remote.surcharge",
            "version": 4,
            "approvals_needed": 1,
        },
    },
    "decision.published": {
        "description": "A decision version came into force",
        "sample": {
            "decision_key": "freight.remote.surcharge",
            "version": 4,
            "valid_from": "2026-01-01",
            "superseded": [3],
            "closed": [],
        },
    },
    "decision.retired": {
        "description": "A decision version stopped applying",
        "sample": {"decision_key": "freight.remote.surcharge", "version": 3},
    },
    "kill_switch.set": {
        "description": "Something was stopped by a kill switch",
        "sample": {"scope": "tool", "target": "web_search", "reason": "vendor outage"},
    },
    "kill_switch.cleared": {
        "description": "A kill switch was resumed",
        "sample": {"scope": "tool", "target": "web_search"},
    },
    "source.changed": {
        "description": "A watched source changed",
        "sample": {
            "source_id": "…",
            "name": "Carrier tariff page",
            "snapshot_id": "…",
            "change_summary": "…",
        },
    },
    "eval.completed": {
        "description": "An evaluation suite run finished",
        "sample": {"suite_id": "…", "passed": 18, "failed": 2},
    },
    "action.proposed": {
        "description": "An agent declared an action and the autonomy gate decided what happens",
        "sample": {
            "action_id": "…",
            "agent_id": "…",
            "action_key": "sample_plant.set_setpoint",
            "level": 2,
            "decision": "wait",
        },
    },
    "action.executed": {
        "description": "A governed action ran",
        "sample": {
            "action_id": "…",
            "action_key": "sample_plant.set_setpoint",
            "ok": True,
            "mode": "auto",
        },
    },
    "action.outcome_recorded": {
        "description": "What actually happened after an action was recorded and scored",
        "sample": {
            "action_id": "…",
            "metric": "pressure_bar",
            "value": 4.35,
            "within_band": True,
            "source": "tool",
        },
    },
    "moderation.held": {
        "description": "A moderation policy held a message or reply for a person to review",
        "sample": {
            "review_id": "…",
            "source": "pre_llm",
            "priority": 2,
            "categories": ["custom:0"],
            "expires_at": "2026-01-01T10:00:00+00:00",
        },
    },
    "moderation.decided": {
        "description": "Held content was released, redacted, rejected or timed out",
        "sample": {
            "review_id": "…",
            "status": "redacted",
            "source": "pre_llm",
            "execution_id": "…",
            "automatic": False,
        },
    },
    "autonomy.recommended": {
        "description": "An agent met the bar for the next autonomy level",
        "sample": {"grant_id": "…", "from_level": 1, "to_level": 2},
    },
    "autonomy.promoted": {
        "description": "A person approved an agent moving up a level",
        "sample": {
            "grant_id": "…",
            "from_level": 2,
            "to_level": 3,
            "approved_by": "…",
        },
    },
    "autonomy.demoted": {
        "description": "An agent moved down a level, by a person or automatically",
        "sample": {
            "grant_id": "…",
            "from_level": 3,
            "to_level": 2,
            "reason": "Harm was flagged on one of its actions",
            "actor": "system",
        },
    },
}

MAX_ATTEMPTS = 8
LEASE_SECONDS = 60
DISABLE_AFTER = 25
_subs_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_SUBS_TTL = 10.0


async def emit(
    db: AsyncSession, tenant_id: Any, event_type: str, payload: dict[str, Any]
) -> None:
    """Record an event in the caller's transaction, so it exists exactly when the change does."""
    await db.execute(
        text(
            "INSERT INTO event_outbox (tenant_id, event_type, payload) VALUES (:t, :e, CAST(:p AS jsonb))"
        ),
        {"t": str(tenant_id), "e": event_type, "p": json.dumps(payload, default=str)},
    )


def _get(obj: Any, path: str) -> Any:
    for p in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(p)
    return obj


def matches(sub: dict[str, Any], event_type: str, payload: dict[str, Any]) -> bool:
    patterns = sub.get("events") or []
    if not any(p == "*" or fnmatch.fnmatchcase(event_type, p) for p in patterns):
        return False
    for path, want in (sub.get("filter") or {}).items():
        got = _get(payload, path)
        if isinstance(want, list):
            if got not in want:
                return False
        elif got != want:
            return False
    return True


async def _subscriptions(db: AsyncSession, tenant_id: str) -> list[dict[str, Any]]:
    hit = _subs_cache.get(tenant_id)
    if hit and time.monotonic() - hit[0] < _SUBS_TTL:
        return hit[1]
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, url, events, filter, target_type, target, signing_secret, created_by "
                    "FROM webhooks WHERE tenant_id = :t AND is_active"
                ),
                {"t": tenant_id},
            )
        )
        .mappings()
        .all()
    )
    subs = [dict(r) for r in rows]
    _subs_cache[tenant_id] = (time.monotonic(), subs)
    return subs


def forget_subscriptions(tenant_id: Any = None) -> None:
    if tenant_id is None:
        _subs_cache.clear()
    else:
        _subs_cache.pop(str(tenant_id), None)


async def fan_out(db: AsyncSession, limit: int = 500) -> int:
    """Turn new outbox events into one pending delivery per matching subscription."""
    rows = (
        (
            await db.execute(
                text(
                    "SELECT id, tenant_id, event_type, payload, occurred_at FROM event_outbox "
                    "WHERE dispatched_at IS NULL ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED"
                ),
                {"n": limit},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return 0
    now = datetime.now(timezone.utc)
    for ev in rows:
        tid = str(ev["tenant_id"])
        for sub in await _subscriptions(db, tid):
            if not matches(sub, ev["event_type"], ev["payload"] or {}):
                continue
            envelope = {
                "id": f"evt_{ev['id']}",
                "type": ev["event_type"],
                "tenant_id": tid,
                "occurred_at": (
                    ev["occurred_at"].isoformat()
                    if ev["occurred_at"]
                    else now.isoformat()
                ),
                "data": ev["payload"] or {},
            }
            await db.execute(
                text(
                    "INSERT INTO webhook_deliveries (id, tenant_id, webhook_id, event, request_payload, delivered, "
                    "attempts, delivery_id, status, next_attempt_at, event_id, created_at, updated_at) "
                    "VALUES (:id, :t, :w, :e, CAST(:p AS jsonb), false, 0, :d, 'pending', :n, :ev, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tid,
                    "w": sub["id"],
                    "e": ev["event_type"],
                    "p": json.dumps(envelope, default=str),
                    "d": envelope["id"],
                    "n": now,
                    "ev": ev["id"],
                },
            )
    await db.execute(
        text("UPDATE event_outbox SET dispatched_at = now() WHERE id = ANY(:ids)"),
        {"ids": [r["id"] for r in rows]},
    )
    await db.commit()
    await _publish_nats(rows)
    return len(rows)


_bus: dict[int, Any] = {}


async def _bus_conn() -> Any:
    import asyncio
    import os

    url = os.environ.get("NATS_URL", "")
    if not url:
        return None
    key = id(asyncio.get_running_loop())
    nc = _bus.get(key)
    if nc is not None and nc.is_connected:
        return nc
    import nats

    async def _quiet(exc: Exception) -> None:
        logger.debug("event bus: %s", exc)

    nc = await nats.connect(
        url,
        user=os.environ.get("NATS_USER") or None,
        password=os.environ.get("NATS_PASSWORD") or None,
        name="abenix-events",
        connect_timeout=2,
        allow_reconnect=True,
        max_reconnect_attempts=-1,
        error_cb=_quiet,
    )
    _bus[key] = nc
    return nc


async def _publish_nats(rows: list[Any]) -> None:
    """Best effort, for internal consumers that prefer a bus to a webhook."""
    try:
        nc = await _bus_conn()
        if nc is None:
            return
        for r in rows:
            await nc.publish(
                f"abenix.events.{r['tenant_id']}.{r['event_type']}",
                json.dumps(
                    {"id": r["id"], "type": r["event_type"], "data": r["payload"]},
                    default=str,
                ).encode(),
            )
        await nc.flush(timeout=2)
    except Exception as exc:  # noqa: BLE001
        logger.warning("event bus publish skipped: %s", exc)


def sign(secret: str, body: str) -> str:
    return hmac.new((secret or "").encode(), body.encode(), hashlib.sha256).hexdigest()


def backoff(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 10 * (2 ** max(0, attempt - 1))))


_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def render(template: str, envelope: dict[str, Any]) -> str:
    def sub(m: re.Match) -> str:
        v = _get(envelope, m.group(1))
        return (
            json.dumps(v, default=str)
            if isinstance(v, (dict, list))
            else ("" if v is None else str(v))
        )

    return _PLACEHOLDER.sub(sub, template or "")


async def unsafe_target(url: str) -> str | None:
    """Why a webhook URL must not be called, judged on the address it resolves to now."""
    import ipaddress
    import os
    from urllib.parse import urlparse

    if os.environ.get("EVENTS_ALLOW_PRIVATE_TARGETS", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        return None
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "The URL is not http or https"
    # exact names only, a suffix match would let a lookalike host through
    allowed = {
        h.strip().lower()
        for h in os.environ.get("EVENTS_ALLOWED_INTERNAL_HOSTS", "").split(",")
        if h.strip()
    }
    if u.hostname.lower() in allowed:
        return None
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            u.hostname, u.port or (443 if u.scheme == "https" else 80)
        )
    except OSError as e:
        return f"The host does not resolve: {e}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return f"The host resolves to a private address ({ip}), which webhooks may not reach"
    return None


async def _deliver_webhook(
    sub: dict[str, Any], envelope: dict[str, Any]
) -> tuple[bool, int | None, str]:
    import httpx

    blocked = await unsafe_target(sub.get("url") or "")
    if blocked:
        return False, None, blocked

    body = json.dumps(envelope, default=str)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Abenix-Events/1.0",
        "X-Abenix-Event": envelope["type"],
        "X-Abenix-Delivery": envelope["id"],
        "X-Abenix-Signature": f"sha256={sign(sub.get('signing_secret') or '', body)}",
    }
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(sub["url"], content=body, headers=headers)
        if r.status_code < 300:
            return True, r.status_code, ""
        return False, r.status_code, f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {str(e)[:300]}"


async def _deliver_run(
    sub: dict[str, Any], envelope: dict[str, Any]
) -> tuple[bool, int | None, str, str | None]:
    """Start the subscribed agent or pipeline with the event as its context."""
    from sqlalchemy import select

    from app.core.deps import async_session
    from app.routers.triggers import dispatch_execution
    from models.agent import Agent
    from models.user import User

    target = sub.get("target") or {}
    try:
        agent_id = uuid.UUID(str(target.get("agent_id")))
    except (TypeError, ValueError):
        return (
            False,
            None,
            "The subscription has no valid agent or pipeline to start.",
            None,
        )
    async with async_session() as db:
        agent = (
            await db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        owner = (
            (
                await db.execute(select(User).where(User.id == sub.get("created_by")))
            ).scalar_one_or_none()
            if sub.get("created_by")
            else None
        )
        if agent is None:
            return False, None, "The agent or pipeline to start no longer exists.", None
        if owner is None or not owner.is_active:
            return (
                False,
                None,
                "The person who created this subscription is no longer active, so nothing can run as them.",
                None,
            )
        message = render(target.get("message") or "Event {{type}}: {{data}}", envelope)
        context = {
            "event": envelope,
            **{
                k: render(str(v), envelope)
                for k, v in (target.get("context") or {}).items()
            },
        }
        from app.core.run_origin import event_origin

        kind, name = event_origin(sub, envelope)
        execution, dispatched = await dispatch_execution(
            db,
            agent=agent,
            user=owner,
            message=message,
            context=context,
            trigger_kind=kind,
            trigger_name=name,
        )
        if not dispatched:
            return (
                False,
                None,
                getattr(execution, "error_message", None)
                or "The run could not be started.",
                str(execution.id),
            )
        return True, None, "", str(execution.id)


async def deliver_due(limit: int = 100) -> int:
    """Claim due deliveries, send them outside any transaction, then record the outcome."""
    from app.core.deps import async_session

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT d.id, d.webhook_id, d.request_payload, d.attempts, w.url, w.target_type, w.target, "
                        "w.signing_secret, w.created_by, w.is_active, w.name FROM webhook_deliveries d JOIN webhooks w ON w.id = d.webhook_id "
                        "WHERE d.status IN ('pending', 'retrying') AND d.next_attempt_at <= now() "
                        "ORDER BY d.next_attempt_at LIMIT :n FOR UPDATE OF d SKIP LOCKED"
                    ),
                    {"n": limit},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return 0
        # a lease, so a crash mid-send retries instead of losing the delivery
        await db.execute(
            text(
                "UPDATE webhook_deliveries SET next_attempt_at = :l WHERE id = ANY(:ids)"
            ),
            {
                "l": now + timedelta(seconds=LEASE_SECONDS),
                "ids": [r["id"] for r in rows],
            },
        )
        await db.commit()

    async def one(r: Any) -> tuple[Any, bool, int | None, str, str | None]:
        if not r["is_active"]:
            return r, False, None, "The subscription is paused.", None
        env = r["request_payload"] or {}
        if (r["target_type"] or "webhook") == "webhook":
            ok, code, err = await _deliver_webhook(dict(r), env)
            return r, ok, code, err, None
        ok, code, err, exid = await _deliver_run(dict(r), env)
        return r, ok, code, err, exid

    results = await asyncio.gather(*(one(r) for r in rows))
    async with async_session() as db:
        for r, ok, code, err, exid in results:
            attempts = int(r["attempts"] or 0) + 1
            if ok:
                await db.execute(
                    text(
                        "UPDATE webhook_deliveries SET status='delivered', delivered=true, attempts=:a, "
                        "response_status_code=:c, error_message=NULL, next_attempt_at=NULL, execution_id=:x, updated_at=now() WHERE id=:id"
                    ),
                    {"a": attempts, "c": code, "x": exid, "id": r["id"]},
                )
                await db.execute(
                    text(
                        "UPDATE webhooks SET consecutive_failures=0, failure_count=0, last_delivery_at=now() WHERE id=:w"
                    ),
                    {"w": r["webhook_id"]},
                )
                continue
            dead = attempts >= MAX_ATTEMPTS
            await db.execute(
                text(
                    "UPDATE webhook_deliveries SET status=:s, attempts=:a, response_status_code=:c, error_message=:e, "
                    "next_attempt_at=:n, execution_id=COALESCE(:x, execution_id), updated_at=now() WHERE id=:id"
                ),
                {
                    "s": "dead" if dead else "retrying",
                    "a": attempts,
                    "c": code,
                    "e": err[:2000],
                    "x": exid,
                    "n": None if dead else now + backoff(attempts),
                    "id": r["id"],
                },
            )
            fails = (
                await db.execute(
                    text(
                        "UPDATE webhooks SET consecutive_failures = consecutive_failures + 1, failure_count = failure_count + 1 "
                        "WHERE id=:w RETURNING consecutive_failures"
                    ),
                    {"w": r["webhook_id"]},
                )
            ).scalar() or 0
            if fails >= DISABLE_AFTER:
                await db.execute(
                    text(
                        "UPDATE webhooks SET is_active=false, disabled_reason=:r WHERE id=:w AND is_active"
                    ),
                    {
                        "w": r["webhook_id"],
                        "r": f"Paused after {fails} failed deliveries in a row. Last error: {err[:300]}",
                    },
                )
                forget_subscriptions()
        await db.commit()
    return len(rows)


async def dispatch_once() -> None:
    from app.core.deps import async_session

    try:
        async with async_session() as db:
            await fan_out(db)
        await deliver_due()
    except Exception:
        logger.exception("event dispatch failed")


async def prune(days_delivered: int = 30, days_outbox: int = 7) -> None:
    from app.core.deps import async_session

    async with async_session() as db:
        await db.execute(
            text(
                "DELETE FROM webhook_deliveries WHERE status='delivered' AND created_at < now() - make_interval(days => :d)"
            ),
            {"d": days_delivered},
        )
        await db.execute(
            text(
                "DELETE FROM event_outbox WHERE dispatched_at IS NOT NULL AND dispatched_at < now() - make_interval(days => :d)"
            ),
            {"d": days_outbox},
        )
        await db.commit()
