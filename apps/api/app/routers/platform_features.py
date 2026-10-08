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
from app.core.platform_features import (
    MARKETPLACE_KEY,
    MONETIZATION_KEY,
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


def _is_admin(user: User) -> bool:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    return r.lower() == "admin"


@router.get("/api/platform/features")
async def get_features(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Which of the two switches are on. Open to anyone, it only holds booleans."""
    return success(await read_features(db))


@router.put("/api/admin/platform-features")
async def set_features(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Only an admin can change these settings", 403)
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
