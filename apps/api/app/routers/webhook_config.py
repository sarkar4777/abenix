"""Webhook configuration CRUD — manage webhook URLs for event delivery."""

from __future__ import annotations

import secrets
import uuid
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User
from models.webhook import Webhook
from models.webhook_delivery import WebhookDelivery

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

VALID_EVENTS = {
    "execution.completed",
    "execution.failed",
    "execution.started",
    "agent.published",
    "agent.updated",
    "*",
}


def _validate_url(url: str) -> str | None:
    """Validate webhook URL. Returns error message or None if valid."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return "URL must use http or https"
        if not parsed.netloc:
            return "URL must have a valid hostname"
        # Block common internal addresses
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return "Localhost URLs are not allowed for webhooks"
        return None
    except Exception:
        return "Invalid URL format"


@router.get("")
async def list_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Webhook).where(Webhook.tenant_id == user.tenant_id)
    )
    webhooks = result.scalars().all()
    return success(
        [
            {
                "id": str(wh.id),
                "url": wh.url,
                "events": wh.events or [],
                "is_active": wh.is_active,
                "failure_count": wh.failure_count,
                "last_delivery_at": (
                    wh.last_delivery_at.isoformat() if wh.last_delivery_at else None
                ),
                "created_at": wh.created_at.isoformat() if wh.created_at else None,
            }
            for wh in webhooks
        ]
    )


@router.post("")
async def create_webhook(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    url = body.get("url", "").strip()
    url_err = _validate_url(url) if url else "URL is required"
    if url_err:
        return error(url_err, 400)

    events = body.get("events", ["execution.completed", "execution.failed"])
    invalid_events = [e for e in events if e not in VALID_EVENTS]
    if invalid_events:
        return error(f"Invalid event types: {', '.join(invalid_events)}", 400)
    signing_secret = secrets.token_urlsafe(32)

    wh = Webhook(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        url=url,
        signing_secret=signing_secret,
        events=events,
        is_active=True,
    )
    db.add(wh)
    await db.commit()
    await db.refresh(wh)

    return success(
        {
            "id": str(wh.id),
            "url": wh.url,
            "signing_secret": signing_secret,  # Shown once, like API keys
            "events": wh.events,
            "is_active": wh.is_active,
        },
        status_code=201,
    )


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.tenant_id == user.tenant_id,
        )
    )
    wh = result.scalar_one_or_none()
    if not wh:
        return error("Webhook not found", 404)

    await db.delete(wh)
    await db.commit()
    return success({"deleted": True})


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: uuid.UUID,
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Update webhook URL, events, or active status."""
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.tenant_id == user.tenant_id,
        )
    )
    wh = result.scalar_one_or_none()
    if not wh:
        return error("Webhook not found", 404)

    if "url" in body:
        url = body["url"].strip()
        url_err = _validate_url(url)
        if url_err:
            return error(url_err, 400)
        wh.url = url

    if "events" in body:
        events = body["events"]
        invalid = [e for e in events if e not in VALID_EVENTS]
        if invalid:
            return error(f"Invalid event types: {', '.join(invalid)}", 400)
        wh.events = events

    if "is_active" in body:
        wh.is_active = bool(body["is_active"])
        if wh.is_active:
            wh.failure_count = 0  # Reset failures when reactivating

    await db.commit()
    await db.refresh(wh)

    return success(
        {
            "id": str(wh.id),
            "url": wh.url,
            "events": wh.events or [],
            "is_active": wh.is_active,
            "failure_count": wh.failure_count,
        }
    )


@router.get("/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    """List delivery history for a webhook endpoint."""
    from sqlalchemy import desc

    result = await db.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.webhook_id == webhook_id,
            WebhookDelivery.tenant_id == user.tenant_id,
        )
        .order_by(desc(WebhookDelivery.created_at))
        .offset(offset)
        .limit(limit)
    )
    deliveries = result.scalars().all()
    return success(
        [
            {
                "id": str(d.id),
                "event": d.event,
                "delivered": d.delivered,
                "response_status_code": d.response_status_code,
                "attempts": d.attempts,
                "error_message": d.error_message,
                "delivery_id": d.delivery_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in deliveries
        ]
    )
