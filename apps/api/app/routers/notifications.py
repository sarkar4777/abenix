from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.notifications import _serialize_notification
from app.core.responses import success
from app.core.security import verify_token
from app.core.ws_manager import ws_manager

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.notification import Notification
from models.user import User

router = APIRouter(tags=["notifications"])


@router.websocket("/api/ws/{user_id}")
async def websocket_endpoint(
    ws: WebSocket,
    user_id: uuid.UUID,
) -> None:
    token = ws.query_params.get("token", "")
    try:
        payload = verify_token(token)
        sub = payload.get("sub")
        if not sub or str(user_id) != sub:
            await ws.close(code=4001, reason="Unauthorized")
            return
    except Exception:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws_manager.connect(user_id, ws)

    async def _heartbeat() -> None:
        """Send a ping every 30 seconds to keep the connection alive."""
        try:
            while True:
                await asyncio.sleep(30)
                await ws.send_text(json.dumps({"event": "ping"}))
        except Exception:
            pass  # connection closed; task will be cancelled

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text('{"event":"pong","data":{}}')
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, ws)
    except Exception:
        ws_manager.disconnect(user_id, ws)
    finally:
        heartbeat_task.cancel()


@router.get("/api/notifications")
async def list_notifications(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    base = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )

    count_result = await db.execute(
        select(func.count(Notification.id)).where(Notification.user_id == user.id)
    )
    total = count_result.scalar() or 0

    unread_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    unread = unread_result.scalar() or 0

    offset = (page - 1) * per_page
    result = await db.execute(base.offset(offset).limit(per_page))
    rows = result.scalars().all()

    return success(
        [_serialize_notification(n) for n in rows],
        meta={"total": total, "unread": unread, "page": page, "per_page": per_page},
    )


@router.get("/api/notifications/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )
    count = result.scalar() or 0
    return success({"unread": count})


@router.post("/api/notifications/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        from app.core.responses import error
        return error("Notification not found", 404)

    notification.is_read = True
    await db.commit()
    return success({"id": str(notification.id), "is_read": True})


@router.post("/api/notifications/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.commit()
    return success({"marked_all_read": True})
