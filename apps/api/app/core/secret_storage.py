"""Whether tool and connector secrets are encrypted at rest, and the startup check."""

from __future__ import annotations

import logging
import os

from app.core import crypto

logger = logging.getLogger(__name__)

KEK_ENV = "ABENIX_DATA_KEY_KEK_BASE64"
OPT_OUT_ENV = "ABENIX_ALLOW_PLAINTEXT_SECRETS"
DOC_SLUG = "08-howto/06-encryption-setup"
WARNING = (
    "Secrets are stored unencrypted. Set ABENIX_DATA_KEY_KEK_BASE64 to encrypt them."
)

_TRUE = {"1", "true", "yes", "on"}


def environment() -> str:
    return os.environ.get("ENVIRONMENT", "").strip().lower()


def is_production() -> bool:
    return environment() in {"production", "prod"}


def plaintext_allowed() -> bool:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() in _TRUE


def encrypted() -> bool:
    return crypto._is_kek_configured()


def status() -> dict:
    enc = encrypted()
    return {
        "encrypted_at_rest": enc,
        "message": None if enc else WARNING,
        "doc_slug": DOC_SLUG,
        "environment": environment() or "development",
    }


def check_at_startup() -> None:
    """Warn without a KEK. In production refuse to start unless opted out."""
    if encrypted():
        return
    if is_production() and not plaintext_allowed():
        raise RuntimeError(
            f"{KEK_ENV} is not set (or is not 32 bytes) and ENVIRONMENT=production. "
            "Tool and connector secrets would be stored in plain text. Set the key "
            f"with `openssl rand -base64 32`, or set {OPT_OUT_ENV}=true to start anyway."
        )
    logger.warning(
        "%s Without a valid %s every tool credential and connector secret is "
        "written to the database in plain text.",
        WARNING,
        KEK_ENV,
    )
