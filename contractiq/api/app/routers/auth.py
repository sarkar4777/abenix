"""ContractIQ Authentication — separate from Abenix platform auth."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success

from app.models.contractiq_models import ContractIQUser, ContractIQUserRole

router = APIRouter(prefix="/api/contractiq/auth", tags=["contractiq-auth"])

# ContractIQ uses its own JWT secret (separate from Abenix)
import os
CIQ_JWT_SECRET = os.environ.get("CONTRACTIQ_JWT_SECRET", "contractiq-dev-secret")
CIQ_JWT_ALGORITHM = "HS256"
CIQ_ACCESS_TOKEN_EXPIRE_MINUTES = 60
CIQ_REFRESH_TOKEN_EXPIRE_DAYS = 30

# RFC 6750 §3 — 401 responses MUST carry a WWW-Authenticate challenge.
CONTRACTIQ_UNAUTH = HTTPException(
    status_code=401,
    detail="ContractIQ authentication required",
    headers={"WWW-Authenticate": 'Bearer realm="contractiq"'},
)


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(
    user_id: uuid.UUID,
    role: str,
    tenant_id: str | None = None,
    token_type: str = "access",
) -> str:
    now = datetime.now(timezone.utc)
    if token_type == "access":
        exp = now + timedelta(minutes=CIQ_ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        exp = now + timedelta(days=CIQ_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "tenant_id": tenant_id or str(user_id),
        "type": token_type,
        "iss": "contractiq",
        "exp": exp,
        "iat": now,
    }
    return jwt.encode(payload, CIQ_JWT_SECRET, algorithm=CIQ_JWT_ALGORITHM)


def tenant_id_for(user: "ContractIQUser") -> str:
    """Canonical tenant id for a CIQ user — falls back to user id when blank."""
    return (user.tenant_id or str(user.id))


def _verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, CIQ_JWT_SECRET, algorithms=[CIQ_JWT_ALGORITHM])
        if payload.get("iss") != "contractiq":
            return {}
        return payload
    except JWTError:
        return {}


async def get_contractiq_user(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-CIQ-Key"),
    db: AsyncSession = Depends(get_db),
) -> ContractIQUser:
    """Authenticate a ContractIQ user via JWT or API key."""
    # Try API key first
    if x_api_key and x_api_key.startswith("ciq_"):
        key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
        result = await db.execute(
            select(ContractIQUser).where(
                ContractIQUser.api_key_hash == key_hash,
                ContractIQUser.is_active.is_(True),
            )
        )
        user = result.scalar_one_or_none()
        if user:
            return user

    # Try JWT Bearer token
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
                    select(ContractIQUser).where(
                        ContractIQUser.id == user_id,
                        ContractIQUser.is_active.is_(True),
                    )
                )
                user = result.scalar_one_or_none()
                if user:
                    return user

    raise CONTRACTIQ_UNAUTH


@router.post("/register")
async def register(body: dict, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Register a new ContractIQ user."""
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    full_name = body.get("full_name", "")
    organization = body.get("organization", "")

    if not email or not password or not full_name:
        return error("email, password, and full_name are required", 400)
    if len(password) < 8:
        return error("Password must be at least 8 characters", 400)

    # Check if email already exists
    existing = await db.execute(
        select(ContractIQUser).where(ContractIQUser.email == email)
    )
    if existing.scalar_one_or_none():
        return error("Email already registered", 409)

    user_id = uuid.uuid4()
    user = ContractIQUser(
        id=user_id,
        email=email,
        password_hash=_hash_password(password),
        full_name=full_name,
        organization=organization,
        # Default tenant scope is the user's own id; users can be re-homed to
        # a shared tenant later by an admin.
        tenant_id=str(user_id),
        role=ContractIQUserRole.ANALYST,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    tid = tenant_id_for(user)
    access_token = _create_token(user.id, user.role.value, tid)
    refresh_token = _create_token(user.id, user.role.value, tid, "refresh")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "organization": user.organization,
            "tenant_id": tid,
            "role": user.role.value,
        },
    })


@router.post("/login")
async def login(body: dict, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Login to ContractIQ."""
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    if not email or not password:
        return error("email and password are required", 400)

    result = await db.execute(
        select(ContractIQUser).where(
            ContractIQUser.email == email,
            ContractIQUser.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if not user or not _verify_password(password, user.password_hash):
        return error("Invalid email or password", 401)

    # Backfill tenant_id for accounts created before the column existed so
    # downstream callers always see a non-empty value.
    if not user.tenant_id:
        user.tenant_id = str(user.id)
        await db.commit()
        await db.refresh(user)

    tid = tenant_id_for(user)
    access_token = _create_token(user.id, user.role.value, tid)
    refresh_token = _create_token(user.id, user.role.value, tid, "refresh")

    return success({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "organization": user.organization,
            "tenant_id": tid,
            "role": user.role.value,
        },
    })


@router.get("/me")
async def get_me(
    user: ContractIQUser = Depends(get_contractiq_user),
) -> JSONResponse:
    """Get current ContractIQ user profile."""
    return success({
        "id": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "organization": user.organization,
        "tenant_id": tenant_id_for(user),
        "role": user.role.value,
    })


@router.post("/api-key")
async def generate_api_key(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Generate a ContractIQ API key (ciq_ prefix)."""
    import secrets
    raw_key = f"ciq_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:12]

    user.api_key_hash = key_hash
    user.api_key_prefix = prefix
    await db.commit()

    return success({
        "api_key": raw_key,
        "prefix": prefix,
        "warning": "Save this key now — it cannot be retrieved later.",
    })
