"""Public, read-write builder validation model endpoint.

The Models page lets admins pick which LLM previews + validates agents and
pipelines from the AI Builder. Both the Builder UI (any authenticated user)
and the validation backend need to read that value, so we expose a slim
authenticated-only surface here. Writes still require admin via the underlying
`platform_settings` row update.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.platform_settings import DEFAULTS, get_setting, invalidate
from app.core.responses import error, success

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
from models.user import User  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["public-settings"])

_BUILDER_KEY = "ai_builder.validation.model"


def _is_admin(user: User) -> bool:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    return r.lower() == "admin"


@router.get("/builder_model")
async def get_builder_model(
    user: User = Depends(get_current_user),
) -> JSONResponse:
    """Return the model the AI Builder uses to preview/validate drafts."""
    value = await get_setting(_BUILDER_KEY)
    default = str(DEFAULTS.get(_BUILDER_KEY, {}).get("value", "azure-gpt-4o"))
    return success({"key": _BUILDER_KEY, "value": value or default, "default": default})


@router.put("/builder_model")
async def set_builder_model(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Admin-only writer that mirrors PATCH /api/admin/settings/{key}."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin role required")

    # Avoid an import cycle: pull AVAILABLE_MODELS at call time.
    from app.routers.admin_settings import AVAILABLE_MODELS  # type: ignore

    value = body.get("value")
    if not isinstance(value, str) or not value.strip():
        return error("'value' is required and must be a non-empty string", 400)
    if value not in {m["id"] for m in AVAILABLE_MODELS}:
        return error(f"Model '{value}' is not in the allowed list", 400)

    meta = DEFAULTS[_BUILDER_KEY]
    await db.execute(
        text(
            """
            INSERT INTO platform_settings (key, value, category, description, updated_by)
            VALUES (:key, :value, :cat, :desc, :uid)
            ON CONFLICT (key)
            DO UPDATE SET value = :value, category = :cat, description = :desc,
                          updated_by = :uid, updated_at = now()
            """
        ),
        {
            "key": _BUILDER_KEY,
            "value": value,
            "cat": meta["category"],
            "desc": meta["description"],
            "uid": user.id,
        },
    )
    await db.commit()
    invalidate(_BUILDER_KEY)
    logger.info("[settings] %s set builder_model=%s", user.email, value)
    return success({"key": _BUILDER_KEY, "value": value})
