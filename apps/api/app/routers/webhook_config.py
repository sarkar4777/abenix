"""Event subscriptions: webhooks, or runs of an agent or pipeline, for platform events."""

from __future__ import annotations

import fnmatch
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.agent import Agent
from models.user import User
from models.webhook import Webhook
from models.webhook_delivery import WebhookDelivery

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# kept so subscriptions created before the catalogue still validate
LEGACY_EVENTS = {"execution.started", "agent.published", "agent.updated"}
TARGET_TYPES = ("webhook", "agent", "pipeline")


def _validate_url(url: str) -> str | None:
    """Validate webhook URL. Returns error message or None if valid."""
    import ipaddress

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "URL must use http or https"
        if not parsed.netloc:
            return "URL must have a valid hostname"
        hostname = (parsed.hostname or "").lower()
        if hostname in (
            "localhost",
            "host.docker.internal",
            "host.minikube.internal",
            "metadata.google.internal",
            "metadata",
            "kubernetes.default.svc",
            "kubernetes",
        ):
            return f"Internal hostname not allowed ({hostname})"
        if (
            hostname.endswith(".svc.cluster.local")
            or hostname.endswith(".cluster.local")
            or hostname.endswith(".internal")
            or hostname.endswith(".local")
        ):
            return "Cluster-internal DNS not allowed"
        try:
            ip = ipaddress.ip_address(hostname)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return f"Private/loopback IP not allowed ({hostname})"
        except ValueError:
            pass
        try:
            as_int = int(hostname)
            packed = ipaddress.ip_address(as_int)
            if packed.is_private or packed.is_loopback or packed.is_link_local:
                return f"IP-literal encoding not allowed ({hostname})"
        except (ValueError, ipaddress.AddressValueError):
            pass
        return None
    except Exception:
        return "Invalid URL format"


def _bad_events(events: list[Any]) -> list[str]:
    from app.services.events import CATALOG

    out = []
    for e in events:
        if not isinstance(e, str) or not e:
            out.append(str(e))
        elif e == "*" or e in LEGACY_EVENTS:
            continue
        elif not any(fnmatch.fnmatchcase(t, e) for t in CATALOG):
            out.append(e)
    return out


def _check_filter(flt: Any) -> str | None:
    if flt in (None, {}):
        return None
    if not isinstance(flt, dict):
        return "filter must map payload fields to the value they must have"
    for k, v in flt.items():
        if not isinstance(k, str) or not k:
            return "filter keys are payload field paths, such as decision_key"
        if isinstance(v, dict):
            return f"filter value for {k} must be a value or a list of values"
    return None


async def _check_target(
    db: AsyncSession, user: User, target_type: str, url: str, target: dict[str, Any]
) -> str | None:
    if target_type not in TARGET_TYPES:
        return f"target_type must be one of {', '.join(TARGET_TYPES)}"
    if target_type == "webhook":
        return _validate_url(url) if url else "A webhook needs a URL"
    try:
        agent_id = uuid.UUID(str(target.get("agent_id")))
    except (TypeError, ValueError):
        return f"Pick the {target_type} to start"
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        return f"That {target_type} was not found in this tenant"
    is_pipeline = (agent.model_config_ or {}).get("mode") == "pipeline"
    if target_type == "pipeline" and not is_pipeline:
        return "That is an agent, not a pipeline. Choose agent as the target."
    if target_type == "agent" and is_pipeline:
        return "That is a pipeline. Choose pipeline as the target."
    return None


def _target_of(target_type: str, target: dict[str, Any]) -> dict[str, Any] | None:
    if target_type == "webhook":
        return None
    return {k: v for k, v in target.items() if k in ("agent_id", "message", "context")}


def _sub_json(wh: Webhook) -> dict[str, Any]:
    return {
        "id": str(wh.id),
        "name": wh.name or "",
        "url": wh.url,
        "events": wh.events or [],
        "filter": wh.filter or {},
        "target_type": wh.target_type or "webhook",
        "target": wh.target or {},
        "is_active": wh.is_active,
        "failure_count": wh.failure_count,
        "consecutive_failures": wh.consecutive_failures or 0,
        "disabled_reason": wh.disabled_reason,
        "last_delivery_at": (
            wh.last_delivery_at.isoformat() if wh.last_delivery_at else None
        ),
        "created_at": wh.created_at.isoformat() if wh.created_at else None,
    }


def _forget(tenant_id: Any) -> None:
    from app.services.events import forget_subscriptions

    forget_subscriptions(tenant_id)


async def _own(db: AsyncSession, user: User, webhook_id: uuid.UUID) -> Webhook | None:
    return (
        await db.execute(
            select(Webhook).where(
                Webhook.id == webhook_id, Webhook.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


@router.get("/catalog")
async def event_catalog(user: User = Depends(get_current_user)) -> Any:
    from app.services.events import CATALOG

    return success([{"type": k, **v} for k, v in CATALOG.items()])


@router.get("")
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = (
        (
            await db.execute(
                select(Webhook)
                .where(Webhook.tenant_id == user.tenant_id)
                .order_by(Webhook.created_at)
            )
        )
        .scalars()
        .all()
    )
    return success([_sub_json(wh) for wh in rows])


@router.post("")
async def create_webhook(
    body: dict[str, Any],
    user: User = Depends(require_capability("events.manage")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    target_type = (body.get("target_type") or "webhook").strip()
    url = (body.get("url") or "").strip()
    target = body.get("target") or {}
    problem = await _check_target(db, user, target_type, url, target)
    if problem:
        return error(problem, 400)
    events = body.get("events", ["execution.completed", "execution.failed"])
    if not isinstance(events, list) or len(events) == 0:
        return error("Pick at least one event", 400)
    bad = _bad_events(events)
    if bad:
        return error(
            f"Unknown events: {', '.join(bad)}. GET /api/webhooks/catalog lists them.",
            400,
        )
    problem = _check_filter(body.get("filter"))
    if problem:
        return error(problem, 400)
    signing_secret = secrets.token_urlsafe(32) if target_type == "webhook" else None
    wh = Webhook(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        name=(body.get("name") or "").strip()[:255],
        url=url or None,
        signing_secret=signing_secret,
        events=events,
        filter=body.get("filter") or None,
        target_type=target_type,
        target=_target_of(target_type, target),
        is_active=True,
        created_by=user.id,
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)
    _forget(user.tenant_id)
    out = _sub_json(wh)
    if signing_secret:
        # shown once, like an API key
        out["signing_secret"] = signing_secret
    return success(out, status_code=201)


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(require_capability("events.manage")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    wh = await _own(db, user, webhook_id)
    if not wh:
        return error("Subscription not found", 404)
    await db.delete(wh)
    await db.commit()
    _forget(user.tenant_id)
    return success({"deleted": True})


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(require_capability("events.manage")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    wh = await _own(db, user, webhook_id)
    if not wh:
        return error("Subscription not found", 404)
    new_secret = None
    if any(k in body for k in ("target_type", "url", "target")):
        target_type = body.get("target_type", wh.target_type or "webhook")
        url = (body.get("url", wh.url) or "").strip()
        target = body.get("target", wh.target or {}) or {}
        problem = await _check_target(db, user, target_type, url, target)
        if problem:
            return error(problem, 400)
        wh.target_type, wh.url, wh.target = (
            target_type,
            url or None,
            _target_of(target_type, target),
        )
        if target_type == "webhook" and not wh.signing_secret:
            wh.signing_secret = new_secret = secrets.token_urlsafe(32)
    if "events" in body:
        events = body.get("events") or []
        bad = _bad_events(events)
        if bad or not events:
            return error(
                (
                    f"Unknown events: {', '.join(bad)}"
                    if bad
                    else "Pick at least one event"
                ),
                400,
            )
        wh.events = events
    if "filter" in body:
        problem = _check_filter(body["filter"])
        if problem:
            return error(problem, 400)
        wh.filter = body["filter"] or None
    if "name" in body:
        wh.name = (body.get("name") or "").strip()[:255]
    if "is_active" in body:
        wh.is_active = bool(body["is_active"])
        if wh.is_active:
            wh.failure_count = 0
            wh.consecutive_failures = 0
            wh.disabled_reason = None
    await db.commit()
    await db.refresh(wh)
    _forget(user.tenant_id)
    out = _sub_json(wh)
    if new_secret:
        # shown once, like on create
        out["signing_secret"] = new_secret
    return success(out)


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(require_capability("events.manage")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Queue a sample event for this subscription only. The dispatcher sends it within seconds."""
    from app.services.events import CATALOG

    wh = await _own(db, user, webhook_id)
    if not wh:
        return error("Subscription not found", 404)
    pats = wh.events or []
    event_type = next(
        (
            t
            for t in CATALOG
            if any(p == "*" or fnmatch.fnmatchcase(t, p) for p in pats)
        ),
        "execution.completed",
    )
    delivery_ref = f"evt_test_{uuid.uuid4().hex[:12]}"
    envelope = {
        "id": delivery_ref,
        "type": event_type,
        "tenant_id": str(user.tenant_id),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "data": {**CATALOG[event_type]["sample"], "test": True},
    }
    did = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO webhook_deliveries (id, tenant_id, webhook_id, event, request_payload, delivered, attempts, "
            "delivery_id, status, next_attempt_at, created_at, updated_at) VALUES (:id, :t, :w, :e, CAST(:p AS jsonb), "
            "false, 0, :d, 'pending', now(), now(), now())"
        ),
        {
            "id": did,
            "t": user.tenant_id,
            "w": wh.id,
            "e": event_type,
            "p": json.dumps(envelope),
            "d": delivery_ref,
        },
    )
    await db.commit()
    return success({"delivery_id": str(did), "event": event_type})


@router.post("/deliveries/{delivery_id}/redeliver")
async def redeliver(
    delivery_id: uuid.UUID,
    user: User = Depends(require_capability("events.manage")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    d = (
        await db.execute(
            select(WebhookDelivery).where(
                WebhookDelivery.id == delivery_id,
                WebhookDelivery.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if not d:
        return error("Delivery not found", 404)
    d.status = "pending"
    d.delivered = False
    # a replay gets the full retry budget again, not the one try left after dying
    d.attempts = 0
    d.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()
    return success({"id": str(d.id), "status": d.status})


@router.get("/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = None,
) -> Any:
    """Delivery history for a subscription, newest first."""
    q = select(WebhookDelivery).where(
        WebhookDelivery.webhook_id == webhook_id,
        WebhookDelivery.tenant_id == user.tenant_id,
    )
    if status:
        q = q.where(WebhookDelivery.status == status)
    rows = (
        (
            await db.execute(
                q.order_by(desc(WebhookDelivery.created_at)).offset(offset).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return success(
        [
            {
                "id": str(d.id),
                "event": d.event,
                "status": d.status,
                "delivered": d.delivered,
                "response_status_code": d.response_status_code,
                "attempts": d.attempts,
                "error_message": d.error_message,
                "delivery_id": d.delivery_id,
                "execution_id": str(d.execution_id) if d.execution_id else None,
                "next_attempt_at": (
                    d.next_attempt_at.isoformat() if d.next_attempt_at else None
                ),
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ]
    )
