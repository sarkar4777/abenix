"""A cached, read-only caller identity for hot paths that must not touch the database per request."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout

from app.core.deps import async_session
from app.core.security import verify_token

_TTL = 15.0
_MAX = 50_000
_cache: dict[str, tuple[float, "Principal"]] = {}


@dataclass(frozen=True)
class Principal:
    id: uuid.UUID
    tenant_id: uuid.UUID
    role: Any
    email: str
    via: str  # jwt | api_key


def _put(k: str, p: "Principal") -> None:
    if len(_cache) >= _MAX:
        cutoff = time.monotonic() - _TTL
        for key in [key for key, (t, _) in _cache.items() if t < cutoff][: _MAX // 4]:
            _cache.pop(key, None)
        if len(_cache) >= _MAX:
            _cache.clear()
    _cache[k] = (time.monotonic(), p)


def _get(k: str) -> "Principal | None":
    hit = _cache.get(k)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    return None


def forget(user_id: uuid.UUID | None = None) -> None:
    if user_id is None:
        _cache.clear()
        return
    for k, (_, p) in list(_cache.items()):
        if p.id == user_id:
            _cache.pop(k, None)


def _denied() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated")


# a saturated pool or a db blip is not a bad credential, say so and let the client retry
_INFRA = (PoolTimeout, DBAPIError, OSError, asyncio.TimeoutError)


def _busy() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="The service is busy, retry shortly.",
        headers={"Retry-After": "2"},
    )


_loading: dict[str, asyncio.Lock] = {}


def _lock(k: str) -> asyncio.Lock:
    if len(_loading) > 10_000:
        _loading.clear()
    return _loading.setdefault(k, asyncio.Lock())


async def _from_api_key(raw: str) -> Principal:

    h = hashlib.sha256(raw.encode()).hexdigest()
    k = f"k:{h}"
    p = _get(k)
    if p:
        return p
    async with _lock(k):
        p = _get(k)
        if p:
            return p
        return await _load_api_key(k, h)


async def _load_api_key(k: str, h: str) -> Principal:
    from datetime import datetime, timezone

    from models.api_key import ApiKey
    from models.user import User

    async with async_session() as db:
        row = (
            await db.execute(
                select(ApiKey).where(ApiKey.key_hash == h, ApiKey.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if row is None:
            raise _denied()
        if row.expires_at and row.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="API key expired")
        u = (
            await db.execute(
                select(User).where(User.id == row.user_id, User.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if u is None:
            raise _denied()
        p = Principal(
            id=u.id, tenant_id=u.tenant_id, role=u.role, email=u.email, via="api_key"
        )
    _put(k, p)
    return p


async def _from_jwt(token: str) -> Principal:
    payload = verify_token(token)
    sub = payload.get("sub")
    if not sub or payload.get("type") != "access":
        raise _denied()
    k = f"u:{sub}"
    p = _get(k)
    if p:
        return p
    try:
        uid = uuid.UUID(sub)
    except ValueError:
        raise _denied() from None
    async with _lock(k):
        p = _get(k)
        if p:
            return p
        return await _load_user(k, uid)


async def _load_user(k: str, uid: uuid.UUID) -> Principal:
    from models.user import User

    async with async_session() as db:
        u = (
            await db.execute(
                select(User).where(User.id == uid, User.is_active.is_(True))
            )
        ).scalar_one_or_none()
        if u is None:
            raise _denied()
        p = Principal(
            id=u.id, tenant_id=u.tenant_id, role=u.role, email=u.email, via="jwt"
        )
    _put(k, p)
    return p


async def current_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    try:
        if x_api_key and x_api_key.startswith("af_"):
            return await _from_api_key(x_api_key)
        if not authorization or not authorization.startswith("Bearer "):
            raise _denied()
        token = authorization.removeprefix("Bearer ")
        if token.startswith("af_"):
            return await _from_api_key(token)
        return await _from_jwt(token)
    except HTTPException:
        raise
    except _INFRA:
        raise _busy() from None
    except Exception:
        raise _denied() from None


def principal_with(cap: str) -> Callable:
    """Hot-path counterpart of require_capability: no session unless a cache misses."""
    from app.core.capabilities import has_capability

    async def _check(p: Principal = Depends(current_principal)) -> Principal:
        try:
            async with async_session() as db:
                ok = await has_capability(db, p, cap)  # type: ignore[arg-type]
        except _INFRA:
            raise _busy() from None
        if not ok:
            raise HTTPException(
                status_code=403,
                detail=f"This needs the {cap} capability. An admin can grant it under Admin, Permissions.",
            )
        return p

    return _check
