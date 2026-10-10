"""Read and change the marketplace and monetization switches."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core import secret_storage
from app.core.permissions import features_for
from app.core.platform_features import (
    MARKETPLACE_KEY,
    MONETIZATION_KEY,
    OPERATOR_ONLY,
    is_platform_operator,
    operator_rule,
    parse_bool,
    read_features,
    write_feature,
)
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(tags=["platform-features"])

_BODY_KEYS = {"marketplace": MARKETPLACE_KEY, "monetization": MONETIZATION_KEY}


@router.get("/api/platform/features")
async def get_features(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Which of the two switches are on. Open to anyone, it only holds booleans."""
    return success(await read_features(db))


@router.get("/api/admin/platform-features")
async def get_features_for_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """The switches plus whether this caller may change them."""
    data = await read_features(db)
    data["can_change"] = await is_platform_operator(db, user)
    data["operator_rule"] = operator_rule()
    return success(data)


@router.put("/api/admin/platform-features")
async def set_features(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await is_platform_operator(db, user):
        return error(OPERATOR_ONLY, 403, error_code="PLATFORM_OPERATOR_REQUIRED")
    changes: dict[str, bool] = {}
    for name, key in _BODY_KEYS.items():
        if name not in body:
            continue
        val = parse_bool(body.get(name))
        if val is None:
            return error(f"'{name}' must be true or false", 400)
        changes[key] = val
    if not changes:
        return error("Send marketplace, monetization or both", 400)

    for key, val in changes.items():
        await write_feature(db, key, val, user.id)
    await db.commit()
    try:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "platform.features_changed",
            {k.split(".")[1]: v for k, v in changes.items()},
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — the switch itself is saved
        logger.warning("audit for platform features failed: %s", exc)
    logger.info("[platform.features] %s set %s", user.email, changes)
    return success(await read_features(db))


@router.get("/api/admin/secret-storage")
async def get_secret_storage(user: User = Depends(get_current_user)) -> JSONResponse:
    """Whether tool and connector secrets are encrypted at rest."""
    if not features_for(user).get("manage_settings"):
        return error("Admin role required", 403)
    return success(secret_storage.status())
