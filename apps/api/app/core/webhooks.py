"""Webhook delivery engine — POST execution results to tenant-configured URLs.

Supports HMAC-SHA256 signing, 3x retry with exponential backoff, and delivery logging.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def deliver_webhook(
    url: str,
    signing_secret: str,
    event: str,
    data: dict[str, Any],
    *,
    max_retries: int = 3,
    backoff_schedule: tuple[int, ...] = (5, 30, 300),
) -> dict[str, Any]:
    """Deliver a webhook event to the configured URL.

    Returns delivery result with status, attempts, and any error.
    """
    payload = {
        "id": str(uuid.uuid4()),
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }

    body = json.dumps(payload, default=str)
    signature = hmac.new(
        signing_secret.encode(), body.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Abenix-Webhook/1.0",
        "X-Abenix-Event": event,
        "X-Abenix-Signature": f"sha256={signature}",
        "X-Abenix-Delivery": payload["id"],
    }

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, content=body, headers=headers)

            if resp.status_code < 300:
                logger.info(
                    "Webhook delivered: event=%s url=%s status=%d attempt=%d",
                    event, url, resp.status_code, attempt + 1,
                )
                return {
                    "delivered": True,
                    "status_code": resp.status_code,
                    "attempts": attempt + 1,
                    "delivery_id": payload["id"],
                }

            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning(
                "Webhook delivery failed: event=%s url=%s status=%d attempt=%d",
                event, url, resp.status_code, attempt + 1,
            )

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Webhook delivery error: event=%s url=%s error=%s attempt=%d",
                event, url, last_error, attempt + 1,
            )

        if attempt < max_retries and attempt < len(backoff_schedule):
            import asyncio
            await asyncio.sleep(backoff_schedule[attempt])

    logger.error(
        "Webhook delivery exhausted: event=%s url=%s error=%s",
        event, url, last_error,
    )
    return {
        "delivered": False,
        "error": last_error,
        "attempts": max_retries + 1,
        "delivery_id": payload["id"],
    }


async def deliver_execution_webhook(
    db_session: Any,
    tenant_id: str,
    event: str,
    data: dict[str, Any],
) -> None:
    """Look up tenant webhooks and deliver to all matching URLs."""
    try:
        from sqlalchemy import select
        from models.webhook import Webhook

        result = await db_session.execute(
            select(Webhook).where(
                Webhook.tenant_id == uuid.UUID(tenant_id),
                Webhook.is_active.is_(True),
            )
        )
        webhooks = result.scalars().all()

        for wh in webhooks:
            events = wh.events or []
            if event in events or "*" in events:
                delivery = await deliver_webhook(
                    url=wh.url,
                    signing_secret=wh.signing_secret or "",
                    event=event,
                    data=data,
                )
                # Track delivery status
                wh.last_delivery_at = datetime.now(timezone.utc)
                if not delivery.get("delivered"):
                    wh.failure_count = (wh.failure_count or 0) + 1
                    if wh.failure_count >= 10:
                        wh.is_active = False
                        logger.warning("Webhook %s auto-disabled after %d failures", wh.url, wh.failure_count)
                else:
                    wh.failure_count = 0

                # Log delivery attempt
                try:
                    from models.webhook_delivery import WebhookDelivery
                    log = WebhookDelivery(
                        tenant_id=uuid.UUID(tenant_id),
                        webhook_id=wh.id,
                        event=event,
                        request_payload=data,
                        response_status_code=delivery.get("status_code"),
                        response_body=str(delivery.get("response_body", ""))[:500],
                        delivered=delivery.get("delivered", False),
                        attempts=delivery.get("attempts", 1),
                        delivery_id=delivery.get("delivery_id", ""),
                        error_message=delivery.get("error"),
                    )
                    db_session.add(log)
                except Exception as log_err:
                    logger.warning("Failed to log webhook delivery: %s", log_err)

                await db_session.commit()
    except Exception as e:
        logger.error("Webhook delivery lookup failed: %s", e)
