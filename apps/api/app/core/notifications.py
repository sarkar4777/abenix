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


# Types not listed (approvals, system alerts) always deliver
PREF_FOR_TYPE: dict[str, str] = {
    "execution_complete": "execution_complete",
    "execution_failed": "execution_failed",
    "usage_warning": "billing_alerts",
    "agent_shared": "team_updates",
    "share_revoked": "team_updates",
    "agent_comment": "team_updates",
    "agent_modified": "team_updates",
    "new_subscriber": "team_updates",
    "listing_reviewed": "team_updates",
    "autonomy_recommended": "autonomy_updates",
    "autonomy_demoted": "autonomy_updates",
    "action_pending_review": "autonomy_updates",
    "action_reported": "autonomy_updates",
    "moderation_review_requested": "moderation_reviews",
    "improvement_ready": "improvement_updates",
    "improvement_kept": "improvement_updates",
    "improvement_rolled_back": "improvement_updates",
}


def pref_key_for(notif_type: Any) -> str | None:
    return PREF_FOR_TYPE.get(str(getattr(notif_type, "value", notif_type) or ""))


def _settings_allows(prefs: dict | None, type_key: Any, channel_key: str) -> bool:
    """Check user's notification_settings against (type, channel)."""
    if not prefs:
        return True
    pref = pref_key_for(type_key)
    if pref and prefs.get(pref) is False:
        return False
    # Channel-level opt-out (only enforced for outbound channels)
    if channel_key:
        ch = (prefs.get("channels") or {}).get(channel_key)
        if ch is False:
            return False
    return True


async def user_wants_notification(
    db: AsyncSession, user_id: uuid.UUID, notif_type: Any
) -> bool:
    """For producers that write Notification rows or WS events directly."""
    if not pref_key_for(notif_type):
        return True
    try:
        from sqlalchemy import select
        from models.user import User

        res = await db.execute(
            select(User.notification_settings).where(User.id == user_id)
        )
        prefs = res.scalar_one_or_none()
    except Exception as e:
        logger.debug("notification prefs load failed: %s", e)
        return True
    return _settings_allows(prefs if isinstance(prefs, dict) else None, notif_type, "")


# Need someone to act, so they are emailed like failures
EMAIL_ALWAYS = {"approval_pending", "autonomy_demoted", "moderation_review_requested"}


def email_channel_available() -> bool:
    from app.core import mailer

    return mailer.available()


def tenant_slack_webhook(tenant: Any) -> str:
    """Decrypted per-tenant Slack webhook, or empty when none is configured."""
    if tenant is None:
        return ""
    raw = (getattr(tenant, "slack_webhook_url", None) or "").strip()
    if not raw:
        return ""
    from app.core import crypto

    return crypto.decrypt(tenant.id, raw).strip()


def mask_webhook(url: str) -> str:
    """Show the host and the tail so an admin can recognise the hook without seeing it."""
    if not url:
        return ""
    from urllib.parse import urlparse

    u = urlparse(url)
    tail = url[-6:] if len(url) > 6 else url
    return f"{u.scheme or 'https'}://{u.netloc or 'hooks.slack.com'}/…{tail}"


async def slack_url_problem(url: str) -> str | None:
    """Why a Slack webhook cannot be used, or None. Private targets need a named allow-list entry."""
    from urllib.parse import urlparse

    from app.services.events import unsafe_target

    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.hostname:
        return "Paste the full webhook link. It starts with https://"
    allowed = {
        h.strip().lower()
        for h in os.environ.get("EVENTS_ALLOWED_INTERNAL_HOSTS", "").split(",")
        if h.strip()
    }
    if u.scheme != "https" and u.hostname.lower() not in allowed:
        return "The webhook link must use https://"
    return await unsafe_target(url)


def platform_slack_webhook() -> str:
    """Operator channel for platform-level alerts only."""
    return (os.environ.get("ABENIX_SLACK_WEBHOOK_URL") or "").strip()


async def _post_slack(
    webhook_url: str, *, title: str, message: str, link: str | None
) -> bool:
    """Best-effort Slack post via incoming webhook. Returns True on"""
    if not webhook_url:
        return False
    blocked = await slack_url_problem(webhook_url)
    if blocked:
        logger.warning("Slack post skipped: %s", blocked)
        return False
    text = f"*{title}*\n{message}"
    if link:
        text += f"\n<{link}|Open in Abenix>"
    payload: dict[str, Any] = {"text": text}
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
    from app.core import mailer

    return await mailer.send(to=to, subject=subject, text=body)


def _email_body(title: str, message: str, link: str | None) -> str:
    from app.core import mailer

    lines = [title, "", message, ""]
    if link:
        lines += [f"Open it in Abenix: {mailer.frontend_url(link)}", ""]
    lines += [
        "You get this email because email copies are on for you.",
        f"Change that under Settings, Notifications: {mailer.frontend_url('/settings/notifications')}",
    ]
    return "\n".join(lines)


def _full_link(link: str | None) -> str | None:
    if not link:
        return None
    if link.startswith("http://") or link.startswith("https://"):
        return link
    from app.core import mailer

    return mailer.frontend_url(link)


async def post_once_to_tenant_slack(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    title: str,
    message: str,
    link: str | None,
) -> bool:
    """One post to the workspace channel for an event several members were told about."""
    from sqlalchemy import select
    from models.tenant import Tenant

    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    hook = tenant_slack_webhook(tenant)
    if not hook:
        return False
    ok = await _post_slack(
        hook, title=f"Abenix — {title}", message=message, link=_full_link(link)
    )
    if ok:
        _emit_notif_metric("slack", _severity_for("approval_pending"))
    return ok


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
    slack: bool = True,
    email: bool = False,
) -> Notification | None:
    """Persist, push and fan out a notification, None when the user turned its type off.

    email=True sends the email copy whatever the severity, still subject to the person's channel settings.
    """
    # Load the user + tenant config so we know who to notify and where.
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
        if push:
            t_res = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = t_res.scalar_one_or_none()
            # Tenant traffic never falls back to the operator channel
            slack_webhook = tenant_slack_webhook(tenant)
    except Exception as e:
        logger.debug("notification context load failed: %s", e)

    if not _settings_allows(prefs, type_key=type, channel_key=""):
        return None

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
    if (
        slack
        and slack_webhook
        and _settings_allows(prefs, type_key=type, channel_key="slack")
    ):
        ok = await _post_slack(
            slack_webhook,
            title=f"Abenix — {title}",
            message=message,
            link=_full_link(link),
        )
        if ok:
            _emit_notif_metric("slack", severity)

    # Email — only fires for error-severity by default, to avoid inbox
    # noise. Operators can override per-user via prefs.email_for_info=true
    # if they really want everything.
    email_eligible = (
        email
        or severity == "error"
        or str(type) in EMAIL_ALWAYS
        or bool(prefs and prefs.get("email_for_info") is True)
    )
    if email_eligible and _settings_allows(prefs, type_key=type, channel_key="email"):
        ok = await _send_email(
            to=user_email,
            subject=f"Abenix: {title}",
            body=_email_body(title, message, link),
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


async def notify_platform_alert(
    db: AsyncSession,
    *,
    name: str,
    severity: str,
    summary: str,
    since: str | None,
    labels: dict | None = None,
    link: str = "/alerts",
    fingerprint: str | None = None,
    status: str = "firing",
    source: str = "prometheus",
) -> int:
    """Fan a platform alert out to every active admin and to Slack.

    In-app rows go through create_notification with push=False and a manual
    WS push, so one alert produces one Slack post per distinct webhook rather
    than one per admin. Returns the number of admin notifications written.
    """
    from sqlalchemy import select
    from models.notification import NotificationType
    from models.tenant import Tenant
    from models.user import User, UserRole

    sev = (severity or "info").lower()
    resolved = (status or "firing").lower() == "resolved"
    if resolved:
        title = f"[RESOLVED] {name}"
        body = f"{summary} has resolved." if summary else f"Alert {name} resolved."
        if since:
            body = f"{body} (at {since})"
    else:
        title = f"[{sev.upper()}] {name}"
        body = summary or f"Alert {name} is firing."
        if since:
            body = f"{body} (since {since})"
    metadata = {
        "source": source,
        "status": "resolved" if resolved else "firing",
        "fingerprint": fingerprint,
        "alertname": name,
        "severity": sev,
        "active_since": since,
        "labels": labels or {},
    }

    admins = (
        (
            await db.execute(
                select(User).where(
                    User.role == UserRole.ADMIN, User.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    written = 0
    tenant_ids = set()
    for admin in admins:
        try:
            n = await create_notification(
                db,
                tenant_id=admin.tenant_id,
                user_id=admin.id,
                type=NotificationType.SYSTEM_ALERT.value,
                title=title,
                message=body,
                link=link,
                metadata=metadata,
                push=False,
            )
            if n is None:
                continue
            written += 1
            tenant_ids.add(admin.tenant_id)
            try:
                await ws_manager.send_to_user(
                    admin.id, "notification", _serialize_notification(n)
                )
            except Exception as e:
                logger.debug("ws push failed: %s", e)
        except Exception as e:
            logger.warning("platform alert notify failed for %s: %s", admin.id, e)

    webhooks: set[str] = set()
    platform_hook = (os.environ.get("ABENIX_SLACK_WEBHOOK_URL") or "").strip()
    if platform_hook:
        webhooks.add(platform_hook)
    if tenant_ids:
        try:
            t_rows = (
                (await db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))))
                .scalars()
                .all()
            )
            for t in t_rows:
                # stored encrypted, posting the ciphertext never reached Slack
                hook = tenant_slack_webhook(t)
                if hook:
                    webhooks.add(hook)
        except Exception as e:
            logger.debug("tenant webhook lookup failed: %s", e)
    for hook in webhooks:
        ok = await _post_slack(
            hook,
            title=f"Abenix — {title}",
            message=body,
            link=_full_link(link),
        )
        if ok:
            _emit_notif_metric(
                "slack", "error" if sev in ("critical", "error") else "warning"
            )
    return written
