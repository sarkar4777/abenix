"""Two-step sign-in state on the user row: an encrypted TOTP secret plus one-time recovery codes."""

from __future__ import annotations

import logging
from typing import Any

from app.core import crypto, totp

logger = logging.getLogger(__name__)


def secret_of(user: Any) -> str:
    raw = (getattr(user, "totp_secret", None) or "").strip()
    if not raw:
        return ""
    try:
        return crypto.decrypt(user.tenant_id, raw).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("two-step secret for %s could not be read: %s", user.id, e)
        return ""


def store_secret(user: Any, secret: str) -> None:
    user.totp_secret = crypto.encrypt(user.tenant_id, secret)


def check_code(user: Any, code: str) -> str | None:
    """'app' or 'recovery' when the code is good, None when it is not. Marks it used."""
    secret = secret_of(user)
    if not secret:
        return None
    step = totp.verify(secret, code, last_step=user.totp_last_step)
    if step is not None:
        user.totp_last_step = step
        return "app"
    digest = totp.digest_code(code)
    left = list(user.totp_recovery_codes or [])
    if digest in left:
        left.remove(digest)
        # a new list so the JSONB change is seen
        user.totp_recovery_codes = left
        return "recovery"
    return None


def issue_recovery_codes(user: Any) -> list[str]:
    codes = totp.new_recovery_codes()
    user.totp_recovery_codes = [totp.digest_code(c) for c in codes]
    return codes


def qr_svg_data_uri(uri: str) -> str | None:
    try:
        import segno  # type: ignore
    except ImportError:
        return None
    qr = segno.make(uri, error="m")
    return qr.svg_data_uri(scale=5, border=2, dark="#0f172a", light="#ffffff")
