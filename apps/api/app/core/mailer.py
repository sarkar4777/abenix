"""Outgoing email through the SMTP_* settings. Best effort, never raises."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def available() -> bool:
    if not os.environ.get("SMTP_HOST", "").strip():
        return False
    try:
        import aiosmtplib  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def _start_tls(port: int) -> bool | None:
    """True requires STARTTLS, False never tries it, None uses it when offered."""
    raw = os.environ.get("SMTP_STARTTLS", "auto").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    # implicit TLS ports speak TLS from the first byte
    return None if port != 465 else False


def frontend_url(path: str = "") -> str:
    base = (os.environ.get("FRONTEND_URL") or "http://localhost:3000").rstrip("/")
    if not path:
        return base
    return f"{base}{path if path.startswith('/') else '/' + path}"


async def send(*, to: str, subject: str, text: str, html: str | None = None) -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host or not to:
        return False
    try:
        import aiosmtplib  # type: ignore
        from email.message import EmailMessage

        port = int(os.environ.get("SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["From"] = os.environ.get("SMTP_FROM") or "no-reply@abenix.dev"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=os.environ.get("SMTP_USER") or None,
            password=os.environ.get("SMTP_PASS") or None,
            use_tls=port == 465,
            start_tls=_start_tls(port),
            timeout=10,
        )
        return True
    except ImportError:
        logger.debug("aiosmtplib not installed, email is off")
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("email to %s failed: %s", to, e)
        return False
