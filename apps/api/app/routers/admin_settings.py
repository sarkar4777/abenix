"""Admin-only platform settings — which LLM powers each built-in"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.platform_settings import DEFAULTS, invalidate
from app.core.responses import error, success

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.user import User  # type: ignore


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


AVAILABLE_MODELS: list[dict[str, Any]] = [
    # Anthropic
    {"id": "claude-sonnet-4-5-20250929", "provider": "anthropic", "label": "Claude Sonnet 4.5", "family": "claude-4", "capabilities": ["text", "vision", "tools", "reasoning"]},
    {"id": "claude-opus-4-5-20250929",   "provider": "anthropic", "label": "Claude Opus 4.5",   "family": "claude-4", "capabilities": ["text", "vision", "tools", "reasoning"]},
    {"id": "claude-haiku-4-5-20251001",  "provider": "anthropic", "label": "Claude Haiku 4.5",  "family": "claude-4", "capabilities": ["text", "vision", "tools"]},
    # Google
    {"id": "gemini-2.0-flash",           "provider": "google",    "label": "Gemini 2.0 Flash",  "family": "gemini-2", "capabilities": ["text", "vision", "tools"]},
    {"id": "gemini-2.0-flash-exp",       "provider": "google",    "label": "Gemini 2.0 Flash (exp)", "family": "gemini-2", "capabilities": ["text", "vision", "tools"]},
    {"id": "gemini-2.5-pro",             "provider": "google",    "label": "Gemini 2.5 Pro",    "family": "gemini-2", "capabilities": ["text", "vision", "tools", "reasoning"]},
    {"id": "gemini-2.5-flash",           "provider": "google",    "label": "Gemini 2.5 Flash",  "family": "gemini-2", "capabilities": ["text", "vision", "tools"]},
    # OpenAI
    {"id": "gpt-4o",                     "provider": "openai",    "label": "GPT-4o",            "family": "gpt-4",    "capabilities": ["text", "vision", "tools"]},
    {"id": "gpt-4o-mini",                "provider": "openai",    "label": "GPT-4o mini",       "family": "gpt-4",    "capabilities": ["text", "vision", "tools"]},
    {"id": "gpt-4-turbo",                "provider": "openai",    "label": "GPT-4 Turbo",       "family": "gpt-4",    "capabilities": ["text", "vision", "tools"]},
]


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if r.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("")
async def list_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return every known setting (with current value or default) grouped by category."""
    _ensure_admin(user)

    rows = (await db.execute(text(
        "SELECT key, value, category, description, updated_at FROM platform_settings"
    ))).fetchall()
    # ISO-format the timestamp so the JSONResponse encoder is happy
    stored = {
        r[0]: {
            "value": r[1],
            "category": r[2],
            "description": r[3],
            "updated_at": r[4].isoformat() if r[4] is not None else None,
        }
        for r in rows
    }

    out: dict[str, list[dict]] = {}
    for key, meta in DEFAULTS.items():
        current = stored.get(key, {})
        item = {
            "key": key,
            "value": current.get("value") or meta["value"],
            "default": meta["value"],
            "category": meta["category"],
            "description": meta["description"],
            "updated_at": current.get("updated_at"),
            "is_default": not current.get("value") or current.get("value") == meta["value"],
        }
        out.setdefault(meta["category"], []).append(item)
    return success({"categories": out, "models": AVAILABLE_MODELS})


@router.get("/models")
async def list_models(
    user: User = Depends(get_current_user),
    capability: str = "",
) -> JSONResponse:
    """Master model list for the platform."""
    _ensure_admin(user)
    models = AVAILABLE_MODELS
    if capability:
        models = [m for m in models if capability in (m.get("capabilities") or [])]
    return success({"models": models})


@router.get("/models/public")
async def list_models_public(
    user: User = Depends(get_current_user),
    capability: str = "",
) -> JSONResponse:
    """Same master list, available to ANY authenticated user. This is the"""
    models = AVAILABLE_MODELS
    if capability:
        models = [m for m in models if capability in (m.get("capabilities") or [])]
    return success({"models": models})


@router.patch("/{key}")
async def update_setting(
    key: str,
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    if key not in DEFAULTS:
        return error(f"Unknown setting '{key}'", 400)
    value = body.get("value")
    if value is None or not isinstance(value, str) or not value.strip():
        return error("'value' is required and must be a non-empty string", 400)

    # Validate against the model catalogue for *.model settings
    if key.endswith(".model") and value not in {m["id"] for m in AVAILABLE_MODELS}:
        return error(f"Model '{value}' is not in the allowed list", 400)

    meta = DEFAULTS[key]
    await db.execute(text(
        """
        INSERT INTO platform_settings (key, value, category, description, updated_by)
        VALUES (:key, :value, :cat, :desc, :uid)
        ON CONFLICT (key)
        DO UPDATE SET value = :value, category = :cat, description = :desc,
                      updated_by = :uid, updated_at = now()
        """
    ), {"key": key, "value": value, "cat": meta["category"],
        "desc": meta["description"], "uid": user.id})
    await db.commit()
    invalidate(key)

    logger.info("[admin.settings] %s set %s=%s", user.email, key, value[:80])
    return success({"key": key, "value": value, "updated_by": str(user.id)})


@router.post("/reset")
async def reset_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    await db.execute(text("DELETE FROM platform_settings"))
    await db.commit()
    invalidate()
    logger.warning("[admin.settings] %s reset all settings to defaults", user.email)
    return success({"reset": True})
