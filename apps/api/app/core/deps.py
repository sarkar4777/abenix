import contextlib
import hashlib
import sys
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import verify_token

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.api_key import ApiKey
from models.tenant import Tenant
from models.user import User

import os as _os
import ssl as _ssl_mod

_db_url = settings.database_url
# In K8s with Bitnami PostgreSQL, SSL is not configured — disable asyncpg SSL
if "+asyncpg" in _db_url and _os.environ.get("PGSSLMODE") == "disable":
    _connect_args: dict = {"ssl": False}
elif "+asyncpg" in _db_url:
    # Default: try SSL but don't verify (allow self-signed)
    try:
        _ctx = _ssl_mod.create_default_context()
        _ctx.check_hostname = False
        _ctx.verify_mode = _ssl_mod.CERT_NONE
        _connect_args = {"ssl": _ctx}
    except Exception:
        _connect_args = {}
else:
    _connect_args = {}
if "+asyncpg" in _db_url:
    # a transaction left idle by a leak is ended by the server instead of pinning locks
    _connect_args["server_settings"] = {
        "idle_in_transaction_session_timeout": _os.environ.get(
            "DB_IDLE_TXN_TIMEOUT_MS", "300000"
        )
    }

import os as _os

# per uvicorn worker, so a pod holds up to workers x (size + overflow); requests queue on the pool, not on Postgres
_pool_size = int(_os.environ.get("DB_POOL_SIZE", "10"))
_max_overflow = int(_os.environ.get("DB_MAX_OVERFLOW", "5"))
_pool_timeout = int(_os.environ.get("DB_POOL_TIMEOUT", "20"))
engine = create_async_engine(
    _db_url,
    # every statement in the log costs real throughput, so it is opt-in
    echo=_os.environ.get("SQL_ECHO", "").lower() in ("1", "true", "yes"),
    connect_args=_connect_args,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_timeout=_pool_timeout,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


@contextlib.asynccontextmanager
async def fresh_session() -> AsyncGenerator[AsyncSession, None]:
    """Open a brand-new AsyncSession for use inside a concurrent task or
    background job.

    Use this — NOT the request-scoped `db: AsyncSession = Depends(get_db)` —
    whenever you need DB access from:
      * an `asyncio.create_task(...)` fire-and-forget background job, or
      * any coroutine that runs in parallel with another await on the same
        session (e.g. siblings inside `asyncio.gather` / `asyncio.wait`).

    asyncpg's underlying connection is single-threaded: two overlapping
    `await session.execute(...)` calls on the same session produce
    `InterfaceError: another operation is in progress`. Passing the
    request's `db` into a task also outlives the request — the request's
    `async with` will close the session out from under the task.
    """
    async with async_session() as session:
        yield session


_LAST_USED_UPDATED: dict[uuid.UUID, datetime] = {}
_LAST_USED_THROTTLE_S = 60.0


async def _touch_api_key_last_used(api_key_id: uuid.UUID) -> None:
    """Update api_keys.last_used_at on a SEPARATE session that commits immediately.

    Holding the row lock for the lifetime of the request (the previous behaviour)
    serialised concurrent API-key requests on the same key — under load that
    presented as a 30s+ hang. Doing the update on its own short-lived session,
    throttled to once per minute per key, releases the lock instantly.
    """
    now = datetime.now(timezone.utc)
    prev = _LAST_USED_UPDATED.get(api_key_id)
    if prev and (now - prev).total_seconds() < _LAST_USED_THROTTLE_S:
        return
    _LAST_USED_UPDATED[api_key_id] = now
    try:
        async with async_session() as side:
            from sqlalchemy import update as _sa_update

            await side.execute(
                _sa_update(ApiKey)
                .where(ApiKey.id == api_key_id)
                .values(last_used_at=now)
            )
            await side.commit()
    except Exception:
        _LAST_USED_UPDATED.pop(api_key_id, None)


async def _authenticate_via_api_key(raw_key: str, db: AsyncSession) -> User | None:
    """Authenticate a request using an af_ API key. Returns the User or None."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        return None

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="API key expired")

    # `is not None` instead of truthiness — a cap of 0 (or 0.00 after a
    # numeric column rounded a sub-precision input) is "spend nothing",
    # NOT "no cap". Using `if X and ...` silently disabled the quota
    # whenever a customer set a cap that rounded to zero.
    if (
        api_key.max_monthly_tokens is not None
        and (api_key.tokens_used or 0) >= api_key.max_monthly_tokens
    ):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="API key monthly quota exceeded (token quota)",
        )
    if api_key.max_monthly_cost is not None and float(api_key.cost_used or 0) >= float(
        api_key.max_monthly_cost
    ):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=403,
            detail="API key monthly quota exceeded (cost quota)",
        )

    await _touch_api_key_last_used(api_key.id)

    result = await db.execute(
        select(User).where(User.id == api_key.user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()

    if user:
        user._api_key_id = api_key.id  # type: ignore[attr-defined]
        if api_key.scopes:
            user._api_key_scopes = api_key.scopes  # type: ignore[attr-defined]

    return user


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_abenix_subject: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    # Try API key auth first (X-API-Key header)
    if x_api_key and x_api_key.startswith("af_"):
        user = await _authenticate_via_api_key(x_api_key, db)
        if user:
            # Extract acting subject if API key has delegation permission
            from app.core.acting_subject import ActingSubject, can_delegate

            scopes = getattr(user, "_api_key_scopes", None)
            if can_delegate(scopes):
                subject = ActingSubject.from_header(x_abenix_subject)
                if subject:
                    user._acting_subject = subject  # type: ignore[attr-defined]
            elif x_abenix_subject:
                # Fail loud rather than silently drop the subject header.
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "API key lacks can_delegate scope; X-Abenix-Subject "
                        "cannot be honored. Add can_delegate to scopes via "
                        "PATCH /api/api-keys/{id}."
                    ),
                )
            return user
        raise _auth_error()

    # Fall back to JWT Bearer token
    if not authorization or not authorization.startswith("Bearer "):
        raise _auth_error()

    token = authorization.removeprefix("Bearer ")
    # Accept af_ API keys via Authorization: Bearer <key> too — easier for
    # SDK / edge-runtime clients that already standardise on Bearer.
    if token.startswith("af_"):
        user = await _authenticate_via_api_key(token, db)
        if user:
            # Same actAs delegation as the X-API-Key branch above — the
            # Python SDK (and every standalone app proxy) uses Bearer af_<key>
            # by default, so dropping the X-Abenix-Subject header here breaks
            # ownership stamping on the Execution row.
            from app.core.acting_subject import ActingSubject, can_delegate

            scopes = getattr(user, "_api_key_scopes", None)
            if can_delegate(scopes):
                subject = ActingSubject.from_header(x_abenix_subject)
                if subject:
                    user._acting_subject = subject  # type: ignore[attr-defined]
            elif x_abenix_subject:
                # Same loud-fail as the X-API-Key branch above.
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=403,
                    detail=(
                        "API key lacks can_delegate scope; X-Abenix-Subject "
                        "cannot be honored. Add can_delegate to scopes via "
                        "PATCH /api/api-keys/{id}."
                    ),
                )
            return user
        raise _auth_error()
    payload = verify_token(token)
    sub = payload.get("sub")
    if not sub or payload.get("type") != "access":
        raise _auth_error()

    try:
        user_id = uuid.UUID(sub)
    except ValueError:
        raise _auth_error()

    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise _auth_error()
    return user


async def get_current_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise _auth_error()
    return tenant


def require_scope(scope: str) -> Callable:
    """Dependency that checks API key scopes. JWT users pass through."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        scopes = getattr(user, "_api_key_scopes", None)
        if scopes is not None and scope not in scopes:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403, detail=f"API key missing required scope: {scope}"
            )
        return user

    return _check


def require_role(roles: list[str]) -> Callable:
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role.value not in roles:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return _check


def _auth_error():
    from fastapi import HTTPException

    return HTTPException(status_code=401, detail="Not authenticated")
