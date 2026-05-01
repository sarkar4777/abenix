import re
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.tenant import Tenant
from models.user import User, UserRole

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _user_dict(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "avatar_url": user.avatar_url,
        "role": user.role.value,
        "tenant_id": str(user.tenant_id),
    }


@router.post("/register")
async def register(body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        return error("Email already registered", 409)

    tenant = Tenant(
        id=uuid.uuid4(),
        name=f"{body.full_name}'s Workspace",
        slug=_slugify(f"{body.full_name}-{uuid.uuid4().hex[:6]}"),
    )
    db.add(tenant)
    await db.flush()

    user = User(
        id=uuid.uuid4(),
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=UserRole.ADMIN,
        tenant_id=tenant.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    await log_action(db, tenant.id, user.id, "user.registered", {"email": user.email}, request)
    await db.commit()

    access = create_access_token(user.id, tenant.id, user.role.value)
    refresh = create_refresh_token(user.id)

    return success({
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": _user_dict(user),
    }, status_code=201)


@router.post("/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        return error("Invalid email or password", 401)

    if not user.is_active:
        return error("Account is disabled", 403)

    await log_action(db, user.tenant_id, user.id, "user.login", None, request)
    await db.commit()

    access = create_access_token(user.id, user.tenant_id, user.role.value)
    refresh = create_refresh_token(user.id)

    return success({
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": _user_dict(user),
    })


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = verify_token(body.refresh_token)
    sub = payload.get("sub")
    if not sub or payload.get("type") != "refresh":
        return error("Invalid refresh token", 401)

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        return error("Invalid refresh token", 401)

    result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    user = result.scalar_one_or_none()
    if not user:
        return error("User not found", 401)

    access = create_access_token(user.id, user.tenant_id, user.role.value)

    return success({
        "access_token": access,
        "token_type": "bearer",
    })


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return success({"user": _user_dict(user)})
