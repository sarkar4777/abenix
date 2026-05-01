"""Saudi Tourism Authentication — separate from Abenix platform auth."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.models.tourism_models import STUser, STUserRole

router = APIRouter(prefix="/api/st/auth", tags=["st-auth"])

ST_JWT_SECRET = os.environ.get("ST_JWT_SECRET", "sauditourism-dev-secret")
ST_JWT_ALGORITHM = "HS256"
ST_ACCESS_TOKEN_EXPIRE_MINUTES = 60
ST_REFRESH_TOKEN_EXPIRE_DAYS = 30


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(user_id: uuid.UUID, role: str, token_type: str = "access") -> str:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        exp = now + timedelta(minutes=ST_ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        exp = now + timedelta(days=ST_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iss": "sauditourism",
        "exp": exp,
        "iat": now,
    }
    return jwt.encode(payload, ST_JWT_SECRET, algorithm=ST_JWT_ALGORITHM)


def _verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, ST_JWT_SECRET, algorithms=[ST_JWT_ALGORITHM])
        if payload.get("iss") != "sauditourism":
            return {}
        return payload
    except JWTError:
        return {}


async def get_st_user(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-ST-Key"),
    db: AsyncSession = Depends(get_db),
) -> STUser:
    """Authenticate a Saudi Tourism user via JWT or API key."""
    if x_api_key and x_api_key.startswith("st_"):
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        result = await db.execute(
            select(STUser).where(STUser.api_key_hash == key_hash, STUser.is_active.is_(True))
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        payload = _verify_token(token)
        sub = payload.get("sub")
        if sub and payload.get("type") == "access":
            try:
                user_id = uuid.UUID(sub)
            except ValueError:
                pass
            else:
                result = await db.execute(
                    select(STUser).where(STUser.id == user_id, STUser.is_active.is_(True))
                )
                user = result.scalar_one_or_none()
                if user:
                    return user

    raise HTTPException(status_code=401, detail="Saudi Tourism authentication required")


@router.post("/register")
async def register(body: dict, db: AsyncSession = Depends(get_db)):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    full_name = body.get("full_name", "")
    organization = body.get("organization", "")

    if not email or not password or not full_name:
        return error("email, password, and full_name are required", 400)
    if len(password) < 8:
        return error("Password must be at least 8 characters", 400)

    existing = await db.execute(select(STUser).where(STUser.email == email))
    if existing.scalar_one_or_none():
        return error("Email already registered", 409)

    user = STUser(
        id=uuid.uuid4(),
        email=email,
        password_hash=_hash_password(password),
        full_name=full_name,
        organization=organization,
        role=STUserRole.ANALYST,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    access_token = _create_token(user.id, user.role.value)
    refresh_token = _create_token(user.id, user.role.value, "refresh")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "organization": user.organization,
            "role": user.role.value,
        },
    })


@router.post("/login")
async def login(body: dict, db: AsyncSession = Depends(get_db)):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return error("email and password are required", 400)

    result = await db.execute(
        select(STUser).where(STUser.email == email, STUser.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user or not _verify_password(password, user.password_hash):
        return error("Invalid email or password", 401)

    access_token = _create_token(user.id, user.role.value)
    refresh_token = _create_token(user.id, user.role.value, "refresh")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "organization": user.organization,
            "role": user.role.value,
        },
    })


@router.get("/me")
async def get_me(user: STUser = Depends(get_st_user)):
    return success({
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "organization": user.organization,
        "role": user.role.value,
    })
