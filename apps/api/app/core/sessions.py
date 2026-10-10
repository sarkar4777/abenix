"""Sign-in sessions. Every token pair carries a session id, revoking the row ends it."""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user_session import UserSession

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

TOUCH_EVERY = 60.0
_touched: dict[str, float] = {}


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


async def start(
    db: AsyncSession, user: Any, request: Request | None, method: str = "password"
) -> UserSession:
    row = UserSession(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        user_id=user.id,
        method=method[:32],
        ip_address=client_ip(request),
        user_agent=(
            (request.headers.get("user-agent") or "")[:500] if request else None
        ),
        last_seen_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()
    return row


def tokens(user: Any, session: UserSession) -> dict[str, str]:
    role = getattr(user.role, "value", user.role)
    return {
        "access_token": create_access_token(
            user.id, user.tenant_id, role, sid=session.id
        ),
        "refresh_token": create_refresh_token(user.id, sid=session.id),
        "token_type": "bearer",
    }


async def sign_in(
    db: AsyncSession, user: Any, request: Request | None, method: str = "password"
) -> dict[str, str]:
    row = await start(db, user, request, method)
    out = tokens(user, row)
    await db.commit()
    return out


async def is_live(db: AsyncSession, sid: Any, user_id: Any = None) -> bool:
    sid_u = _uuid(sid)
    if sid_u is None:
        return False
    row = (
        await db.execute(
            select(
                UserSession.user_id, UserSession.revoked_at, UserSession.created_at
            ).where(UserSession.id == sid_u)
        )
    ).first()
    if row is None or row[1] is not None:
        return False
    if user_id is not None and str(row[0]) != str(user_id):
        return False
    # a session cannot outlive the refresh token that started it
    age_limit = timedelta(days=settings.refresh_token_expire_days)
    if row[2] is not None and row[2] < datetime.now(timezone.utc) - age_limit:
        return False
    return True


async def touch(sid: Any) -> None:
    """Record activity at most once a minute per session, on its own connection."""
    key = str(sid)
    now = time.monotonic()
    if now - _touched.get(key, 0.0) < TOUCH_EVERY:
        return
    _touched[key] = now
    if len(_touched) > 50_000:
        _touched.clear()
    try:
        from app.core.deps import async_session

        async with async_session() as side:
            await side.execute(
                update(UserSession)
                .where(UserSession.id == _uuid(sid))
                .values(last_seen_at=datetime.now(timezone.utc))
            )
            await side.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("session touch failed: %s", e)


async def revoke(
    db: AsyncSession,
    user_id: Any,
    *,
    sid: Any = None,
    keep: Any = None,
    reason: str = "signed_out",
) -> int:
    """Revoke one session, or every live one except `keep`. Returns how many."""
    q = update(UserSession).where(
        UserSession.user_id == _uuid(user_id), UserSession.revoked_at.is_(None)
    )
    if sid is not None:
        q = q.where(UserSession.id == _uuid(sid))
    if keep is not None:
        q = q.where(UserSession.id != _uuid(keep))
    res = await db.execute(
        q.values(revoked_at=datetime.now(timezone.utc), revoked_reason=reason[:64])
    )
    return int(res.rowcount or 0)


async def list_live(db: AsyncSession, user_id: Any) -> list[UserSession]:
    since = datetime.now(timezone.utc) - timedelta(
        days=settings.refresh_token_expire_days
    )
    rows = (
        (
            await db.execute(
                select(UserSession)
                .where(
                    UserSession.user_id == _uuid(user_id),
                    UserSession.revoked_at.is_(None),
                    UserSession.created_at >= since,
                )
                .order_by(UserSession.last_seen_at.desc().nullslast())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
