from __future__ import annotations

import hashlib
import secrets
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.schemas.settings import CreateApiKeyRequest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.api_key import ApiKey
from models.user import User

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _serialize(k: ApiKey) -> dict:
    return {
        "id": str(k.id),
        "name": k.name,
        "key_prefix": k.key_prefix,
        "is_active": k.is_active,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "scopes": getattr(k, "scopes", None),
        "expires_at": (
            k.expires_at.isoformat() if getattr(k, "expires_at", None) else None
        ),
        "tokens_used": int(getattr(k, "tokens_used", 0) or 0),
        "cost_used": float(getattr(k, "cost_used", 0) or 0.0),
        "max_monthly_tokens": getattr(k, "max_monthly_tokens", None),
        "max_monthly_cost": (
            float(k.max_monthly_cost)
            if getattr(k, "max_monthly_cost", None) is not None
            else None
        ),
    }


def _is_admin(user: User) -> bool:
    role = getattr(user, "role", None)
    role_val = getattr(role, "value", role) if role is not None else ""
    return str(role_val).lower() == "admin"


def _is_superadmin(user: User) -> bool:
    role = getattr(user, "role", None)
    role_val = getattr(role, "value", role) if role is not None else ""
    return str(role_val).lower() in ("superadmin", "super_admin", "platform_admin")


def _normalize_scopes(scopes: dict | None) -> dict | None:
    """Accept the two production shapes and reject anything else.

    Valid:
      {"can_delegate": true, ...}
      {"allowed_actions": [...]}
    """
    if scopes is None:
        return None
    if not isinstance(scopes, dict):
        return None
    if "can_delegate" in scopes or "allowed_actions" in scopes:
        return scopes
    # Unknown shape — drop it rather than persist garbage that silently breaks delegation.
    return None


@router.get("")
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(ApiKey).where(
        ApiKey.tenant_id == user.tenant_id, ApiKey.is_active.is_(True)
    )
    if not _is_admin(user):
        q = q.where(ApiKey.user_id == user.id)
    q = q.order_by(ApiKey.created_at.desc())
    result = await db.execute(q)
    keys = result.scalars().all()
    return success([_serialize(k) for k in keys])


@router.post("")
async def create_api_key(
    body: CreateApiKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    raw_key = f"af_{secrets.token_urlsafe(32)}"
    prefix = raw_key[:7] + "****" + raw_key[-4:]

    # Only platform superadmin can mint cross-tenant; everyone else stamps own tenant.
    target_tenant = user.tenant_id
    if body.tenant_id and _is_superadmin(user):
        try:
            target_tenant = uuid.UUID(body.tenant_id)
        except (ValueError, AttributeError):
            target_tenant = user.tenant_id

    key = ApiKey(
        tenant_id=target_tenant,
        user_id=user.id,
        name=body.name,
        key_hash=_hash_key(raw_key),
        key_prefix=prefix,
        scopes=_normalize_scopes(body.scopes),
        expires_at=body.expires_at,
        max_monthly_tokens=body.max_monthly_tokens,
        max_monthly_cost=body.max_monthly_cost,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    data = _serialize(key)
    data["raw_key"] = raw_key
    return success(data, status_code=201)


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(ApiKey).where(
        ApiKey.id == key_id,
        ApiKey.tenant_id == user.tenant_id,
    )
    if not _is_admin(user):
        q = q.where(ApiKey.user_id == user.id)
    result = await db.execute(q)
    key = result.scalar_one_or_none()
    if not key:
        return error("API key not found", 404)

    key.is_active = False
    await db.commit()

    return success({"id": str(key.id), "status": "revoked"})


@router.patch("/{key_id}")
async def update_api_key(
    key_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Update an API key's name, scopes, or expiry."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        return error("API key not found", 404)

    if "name" in body:
        key.name = body["name"]
    if "scopes" in body:
        key.scopes = body["scopes"]
    if "expires_at" in body:
        from datetime import datetime

        key.expires_at = (
            datetime.fromisoformat(body["expires_at"]) if body["expires_at"] else None
        )

    await db.commit()
    return success(
        {
            "id": str(key.id),
            "name": key.name,
            "key_prefix": key.key_prefix,
            "scopes": key.scopes,
        }
    )
