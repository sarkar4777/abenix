"""Read only list of API keys that can impersonate subjects or send machine commands."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.platform_features import is_platform_operator
from app.core.responses import error, success
from app.routers.api_keys import _granted_actions, _is_admin, _sensitive

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.api_key import ApiKey  # noqa: E402
from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/admin/api-keys", tags=["admin-api-keys"])


@router.get("/privileged")
async def privileged_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Operators see every tenant, a tenant admin sees their own. Nothing is changed."""
    if not _is_admin(user):
        return error("Admin role required", 403)
    query = (
        select(ApiKey, User.email)
        .outerjoin(User, ApiKey.user_id == User.id)
        .where(ApiKey.is_active.is_(True))
    )
    if not await is_platform_operator(db, user):
        query = query.where(ApiKey.tenant_id == user.tenant_id)
    rows = (await db.execute(query)).all()
    items = []
    for key, email in rows:
        held = _sensitive(_granted_actions(key.scopes))
        if held:
            items.append(
                {
                    "id": str(key.id),
                    "name": key.name,
                    "key_prefix": key.key_prefix,
                    "tenant_id": str(key.tenant_id),
                    "created_by": email,
                    "created_at": (
                        key.created_at.isoformat() if key.created_at else None
                    ),
                    "last_used_at": (
                        key.last_used_at.isoformat() if key.last_used_at else None
                    ),
                    "expires_at": (
                        key.expires_at.isoformat() if key.expires_at else None
                    ),
                    "sensitive_scopes": sorted(held),
                }
            )
    return success({"keys": items, "count": len(items)})
