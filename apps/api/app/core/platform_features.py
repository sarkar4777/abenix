"""Marketplace and monetization switches.

Two independent server-side settings. The env (helm configmap) sets the
default, a platform operator can override either from the UI, and the
override lives in platform_settings so every API pod sees the same value.

The switches are deployment-wide, so a tenant admin cannot change them. A
platform operator is an admin listed in ABENIX_PLATFORM_OPERATORS (emails,
comma separated). When that is unset, the admins of the platform tenant, the
one holding system@abenix.dev, are the operators.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db

logger = logging.getLogger(__name__)

MARKETPLACE_KEY = "features.marketplace.enabled"
MONETIZATION_KEY = "features.monetization.enabled"

# setting key -> (feature name, env var, built-in default)
SWITCHES: dict[str, tuple[str, str, bool]] = {
    MARKETPLACE_KEY: ("marketplace", "MARKETPLACE_ENABLED", True),
    MONETIZATION_KEY: ("monetization", "MONETIZATION_ENABLED", False),
}

OPERATORS_ENV = "ABENIX_PLATFORM_OPERATORS"
SYSTEM_USER_EMAIL = "system@abenix.dev"
OPERATOR_ONLY = (
    "These switches apply to every tenant on this deployment, so only a "
    "platform operator can change them."
)

MARKETPLACE_OFF = "The marketplace is turned off on this deployment."
MONETIZATION_OFF = "Monetization is turned off on this deployment."

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    v = str(value if value is not None else "").strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def env_default(key: str) -> bool:
    _, env, fallback = SWITCHES[key]
    parsed = parse_bool(os.environ.get(env))
    return fallback if parsed is None else parsed


def operator_emails() -> set[str]:
    raw = os.environ.get(OPERATORS_ENV, "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _is_admin(user: Any) -> bool:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    return r.lower() == "admin"


async def _platform_tenant_id(db: AsyncSession) -> Any:
    try:
        row = (
            await db.execute(
                text("SELECT tenant_id FROM users WHERE lower(email) = :e"),
                {"e": SYSTEM_USER_EMAIL},
            )
        ).first()
    except Exception as exc:  # noqa: BLE001
        logger.debug("platform tenant lookup failed: %s", exc)
        return None
    return row[0] if row else None


async def is_platform_operator(db: AsyncSession, user: Any) -> bool:
    if not _is_admin(user):
        return False
    listed = operator_emails()
    if listed:
        return str(getattr(user, "email", "") or "").lower() in listed
    tid = await _platform_tenant_id(db)
    return tid is not None and str(tid) == str(getattr(user, "tenant_id", ""))


def operator_rule() -> str:
    if operator_emails():
        return f"Admins listed in {OPERATORS_ENV}."
    return "Admins of the platform tenant, the one that holds the system account."


async def read_features(db: AsyncSession) -> dict[str, Any]:
    """Current value of both switches, plus where each one came from."""
    stored: dict[str, str] = {}
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT key, value FROM platform_settings " "WHERE key IN (:a, :b)"
                ),
                {"a": MARKETPLACE_KEY, "b": MONETIZATION_KEY},
            )
        ).all()
        stored = {str(k): str(v or "") for k, v in rows}
    except Exception as exc:  # noqa: BLE001 — fall back to the env default
        logger.debug("platform features read skipped: %s", exc)

    out: dict[str, Any] = {"source": {}, "defaults": {}}
    for key, (name, _env, _fb) in SWITCHES.items():
        default = env_default(key)
        override = parse_bool(stored.get(key))
        out[name] = default if override is None else override
        out["source"][name] = "default" if override is None else "admin"
        out["defaults"][name] = default
    return out


async def write_feature(db: AsyncSession, key: str, value: bool, user_id: Any) -> None:
    name = SWITCHES[key][0]
    await db.execute(
        text(
            """
            INSERT INTO platform_settings (key, value, category, description, updated_by)
            VALUES (:key, :value, 'features', :desc, :uid)
            ON CONFLICT (key)
            DO UPDATE SET value = :value, updated_by = :uid, updated_at = now()
            """
        ),
        {
            "key": key,
            "value": "true" if value else "false",
            "desc": f"Whether the {name} is turned on.",
            "uid": user_id,
        },
    )


async def marketplace_enabled(db: AsyncSession) -> bool:
    return bool((await read_features(db))["marketplace"])


async def monetization_enabled(db: AsyncSession) -> bool:
    return bool((await read_features(db))["monetization"])


async def require_marketplace(db: AsyncSession = Depends(get_db)) -> None:
    if not await marketplace_enabled(db):
        raise HTTPException(
            status_code=404,
            detail={"message": MARKETPLACE_OFF, "error_code": "MARKETPLACE_OFF"},
        )


async def require_monetization(db: AsyncSession = Depends(get_db)) -> None:
    if not await monetization_enabled(db):
        raise HTTPException(
            status_code=404,
            detail={"message": MONETIZATION_OFF, "error_code": "MONETIZATION_OFF"},
        )
