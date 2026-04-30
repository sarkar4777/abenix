from __future__ import annotations

import hashlib
import secrets
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, update
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
    }


@router.get("")
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.tenant_id == user.tenant_id, ApiKey.is_active.is_(True))
        .order_by(ApiKey.created_at.desc())
    )
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

    key = ApiKey(
        tenant_id=user.tenant_id,
        user_id=user.id,
        name=body.name,
        key_hash=_hash_key(raw_key),
        key_prefix=prefix,
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
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.tenant_id == user.tenant_id,
        )
    )
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
        key.expires_at = datetime.fromisoformat(body["expires_at"]) if body["expires_at"] else None

    await db.commit()
    return success({
        "id": str(key.id),
        "name": key.name,
        "key_prefix": key.key_prefix,
        "scopes": key.scopes,
    })
