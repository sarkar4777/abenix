"""GET /api/events/stream: platform events for apps as server-sent events, resumable by event id."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import capabilities_for
from app.core.deps import get_current_user, get_db
from app.core.permissions import is_admin
from app.core.responses import error, success
from app.services import event_stream as ES
from app.services.events import CATALOG
from models.user import User

router = APIRouter(prefix="/api/events", tags=["events"])

PING_S = 15.0
MAX_PER_USER = 10


def _viewers_key(user_id: Any) -> str:
    return f"events:sse:{user_id}"


@router.get("/types")
async def event_types(user: User = Depends(get_current_user)) -> JSONResponse:
    """The events an app can subscribe to, with a sample payload each."""
    return success(
        [
            {"type": k, "description": v["description"], "sample": v.get("sample")}
            for k, v in sorted(CATALOG.items())
        ]
    )


@router.get("/stream")
async def stream(
    request: Request,
    types: str = Query(
        "",
        description="Comma separated event types or patterns, e.g. telemetry.rule_fired,execution.*. Empty means all you may see.",
    ),
    since: str | None = Query(
        None,
        description="Resume after this event id, or replay events after this ISO time",
    ),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-sent events: one message per platform event, id is the event id to resume from."""
    pats, bad = ES.parse_types(types, CATALOG)
    if bad:
        await db.close()
        return error(
            f"Unknown event types: {', '.join(bad)}. GET /api/events/types lists them.",
            422,
            error_code="VALIDATION_ERROR",
        )
    try:
        after_id, after_time = ES.parse_since(last_event_id or since)
    except ValueError:
        await db.close()
        return error(
            "since is an event id such as 4211 or an ISO time such as 2026-10-11T09:00:00Z.",
            422,
            error_code="VALIDATION_ERROR",
        )
    from app.routers.telemetry import redis
    from app.telemetry import access

    admin = is_admin(user)
    caps = await capabilities_for(db, user)
    scope = None if admin else await access.scope_for(db, user)
    tenant = str(user.tenant_id)
    viewer = ES.Viewer(
        tenant=tenant,
        user_id=str(user.id),
        admin=admin,
        caps=caps,
        scope=scope,
        types=pats,
    )
    r = redis()
    vkey = _viewers_key(user.id)
    sid = uuid.uuid4().hex
    now = time.time()
    await r.zremrangebyscore(vkey, 0, now - 60)
    if await r.zcard(vkey) >= MAX_PER_USER:
        await db.close()
        return error(
            f"You already have {MAX_PER_USER} event streams open. Close one and try again.",
            429,
            error_code="RATE_LIMITED",
        )
    await r.zadd(vkey, {sid: now})
    await r.expire(vkey, 120)
    await ES.hub.add(viewer)
    replayed: list[dict[str, Any]] = []
    more = False
    if after_id is not None or after_time is not None:
        try:
            replayed, more = await ES.replay(db, tenant, after_id, after_time)
        except Exception:  # noqa: BLE001
            await ES.hub.remove(viewer)
            await r.zrem(vkey, sid)
            await db.close()
            raise
    await db.close()

    async def gen():
        seen = ES.Seen()
        last_ping = time.monotonic()
        last_beat = time.monotonic()
        try:
            yield "retry: 3000\n\n"
            yield ": connected\n\n"
            for env in replayed:
                if seen.add(int(env["id"])) and viewer.may_see(env):
                    yield ES.sse(viewer.shape(env))
            if more:
                yield (
                    "event: gap\ndata: "
                    '{"message": "More events were missed than one replay sends. '
                    'Reconnect with the last id you got to read the rest."}\n\n'
                )
            while True:
                if await request.is_disconnected():
                    return
                try:
                    env = await asyncio.wait_for(viewer.queue.get(), timeout=1.0)
                    if seen.add(int(env["id"])):
                        yield ES.sse(viewer.shape(env))
                except asyncio.TimeoutError:
                    pass
                t = time.monotonic()
                if t - last_ping >= PING_S:
                    last_ping = t
                    yield ": ping\n\n"
                if t - last_beat >= 30:
                    last_beat = t
                    try:
                        await r.zadd(vkey, {sid: time.time()})
                        await r.expire(vkey, 120)
                    except Exception:  # noqa: BLE001
                        pass
        finally:
            await ES.hub.remove(viewer)
            try:
                await r.zrem(vkey, sid)
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
