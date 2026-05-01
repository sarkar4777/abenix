"""Notification creation + multi-channel delivery."""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.notification import Notification

from app.core.ws_manager import ws_manager

logger = logging.getLogger(__name__)


def _settings_allows(prefs: dict | None, type_key: str, channel_key: str) -> bool:
    """Check user's notification_settings against (type, channel)."""
    if not prefs:
        return True
    # Type-level opt-out
    if type_key in prefs and prefs[type_key] is False:
        return False
    # Channel-level opt-out (only enforced for outbound channels)
    if channel_key:
        ch = (prefs.get("channels") or {}).get(channel_key)
        if ch is False:
            return False
    return True


async def _post_slack(
    webhook_url: str, *, title: str, message: str, link: str | None
) -> bool:
    """Best-effort Slack post via incoming webhook. Returns True on"""
    if not webhook_url:
        return False
    payload: dict[str, Any] = {
        "text": f"*{title}*\n{message}",
    }
    if link:
        payload["attachments"] = [
            {
                "color": "warning",
                "actions": [{"type": "button", "text": "View in Abenix", "url": link}],
            }
        ]
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(webhook_url, json=payload)
            return 200 <= r.status_code < 300
    except Exception as e:
        logger.debug("Slack post failed: %s", e)
        return False


async def _send_email(*, to: str, subject: str, body: str) -> bool:
    """Best-effort SMTP send. Uses the SMTP_* env vars already wired"""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host or not to:
        return False
    try:
        import aiosmtplib  # type: ignore
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = os.environ.get("SMTP_FROM", "no-reply@abenix.dev")
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ.get("SMTP_USER") or None,
            password=os.environ.get("SMTP_PASS") or None,
            start_tls=True,
            timeout=10,
        )
        return True
    except ImportError:
        logger.debug("aiosmtplib not installed; email channel disabled")
        return False
    except Exception as e:
        logger.debug("email send failed: %s", e)
        return False


def _emit_notif_metric(channel: str, severity: str) -> None:
    try:
        from app.core.telemetry import notifications_sent_total

        notifications_sent_total.labels(channel=channel, severity=severity).inc()
    except Exception:
        pass


def _severity_for(notif_type: str) -> str:
    """Map notification type → coarse severity for Prometheus + UI tinting."""
    t = (notif_type or "").lower()
    if "failed" in t or "error" in t or "alert" in t or "abandoned" in t:
        return "error"
    if "warning" in t or "budget" in t:
        return "warning"
    return "info"


async def create_notification(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    type: str,
    title: str,
    message: str,
    link: str | None = None,
    metadata: dict | None = None,
    push: bool = True,
) -> Notification:
    """Persist a notification, push it via WS, and fan out to Slack /"""
    notification = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
        metadata_=metadata,
    )
    db.add(notification)
    await db.flush()
    await db.refresh(notification)
    severity = _severity_for(type)
    _emit_notif_metric("in_app", severity)

    if not push:
        return notification

    # Load the user + tenant config so we know who to notify and where.
    # Done in this function (not deferred) so the side effects happen on
    # the same async tick — predictable in tests.
    prefs: dict | None = None
    user_email: str = ""
    slack_webhook: str = ""
    try:
        from sqlalchemy import select
        from models.user import User
        from models.tenant import Tenant

        u_res = await db.execute(select(User).where(User.id == user_id))
        user = u_res.scalar_one_or_none()
        if user:
            prefs = getattr(user, "notification_settings", None) or None
            user_email = (user.email or "").strip()
        t_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = t_res.scalar_one_or_none()
        slack_webhook = (
            (getattr(tenant, "slack_webhook_url", None) or "").strip() if tenant else ""
        )
        if not slack_webhook:
            slack_webhook = (os.environ.get("ABENIX_SLACK_WEBHOOK_URL") or "").strip()
    except Exception as e:
        logger.debug("notification context load failed: %s", e)

    # WS push — always (real-time bell). Subject to type opt-out only.
    if _settings_allows(prefs, type_key=type, channel_key=""):
        try:
            await ws_manager.send_to_user(
                user_id,
                "notification",
                _serialize_notification(notification),
            )
            _emit_notif_metric("ws", severity)
        except Exception as e:
            logger.debug("ws push failed: %s", e)

    # Slack — outbound, gated on tenant having a webhook + user opt-in.
    if slack_webhook and _settings_allows(prefs, type_key=type, channel_key="slack"):
        ok = await _post_slack(
            slack_webhook,
            title=f"Abenix — {title}",
            message=message,
            link=(os.environ.get("FRONTEND_URL", "") + (link or "")) if link else None,
        )
        if ok:
            _emit_notif_metric("slack", severity)

    # Email — only fires for error-severity by default, to avoid inbox
    # noise. Operators can override per-user via prefs.email_for_info=true
    # if they really want everything.
    email_eligible = severity == "error" or (
        prefs and prefs.get("email_for_info") is True
    )
    if email_eligible and _settings_allows(prefs, type_key=type, channel_key="email"):
        ok = await _send_email(
            to=user_email,
            subject=f"Abenix: {title}",
            body=f"{message}\n\nDetails: {os.environ.get('FRONTEND_URL', '') + (link or '') if link else '(no link)'}",
        )
        if ok:
            _emit_notif_metric("email", severity)

    return notification


def _serialize_notification(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "type": n.type,
        "title": n.title,
        "message": n.message,
        "is_read": n.is_read,
        "link": n.link,
        "metadata": n.metadata_,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
