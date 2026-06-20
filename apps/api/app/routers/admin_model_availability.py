from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "db"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))
from models.llm_pricing import ModelAvailability  # type: ignore  # noqa: E402
from models.user import User  # type: ignore  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/admin/model-availability", tags=["admin-model-availability"]
)


def _ensure_admin(user: User) -> None:
    role = getattr(user, "role", None)
    r = role.value if hasattr(role, "value") else str(role or "")
    if r.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


@router.get("")
async def list_availability(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    rows = (
        (await db.execute(select(ModelAvailability).order_by(ModelAvailability.model)))
        .scalars()
        .all()
    )
    return success(
        {
            "rows": [
                {
                    "model": r.model,
                    "provider": r.provider,
                    "status": r.status,
                    "last_checked_at": (
                        r.last_checked_at.isoformat() if r.last_checked_at else None
                    ),
                    "last_ok_at": r.last_ok_at.isoformat() if r.last_ok_at else None,
                    "last_error": r.last_error,
                    "consecutive_failures": r.consecutive_failures,
                    "latency_ms": r.latency_ms,
                    "status_since": (
                        r.status_since.isoformat() if r.status_since else None
                    ),
                }
                for r in rows
            ]
        }
    )


@router.post("/force-status")
async def force_status(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    model = (body.get("model") or "").strip()
    status = (body.get("status") or "").strip().lower()
    if not model or status not in {"available", "unavailable", "degraded"}:
        return error("model and status (available/unavailable/degraded) required", 400)

    row = (
        await db.execute(
            select(ModelAvailability).where(ModelAvailability.model == model)
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        provider = (
            await db.execute(
                text(
                    "SELECT provider FROM llm_model_pricing WHERE model = :m ORDER BY effective_from DESC LIMIT 1"
                ),
                {"m": model},
            )
        ).scalar_one_or_none() or "other"
        row = ModelAvailability(
            model=model,
            provider=provider,
            status=status,
            status_since=now,
            last_checked_at=now,
        )
        db.add(row)
    else:
        old = row.status
        if old != status:
            row.status = status
            row.status_since = now
            await db.execute(
                text(
                    """
                    INSERT INTO model_availability_events (model, from_status, to_status, error)
                    VALUES (:m, :f, :t, :e)
                    """
                ),
                {"m": model, "f": old, "t": status, "e": "admin_forced"},
            )
        row.last_checked_at = now
        if status == "available":
            row.consecutive_failures = 0
            row.last_error = None
    await db.commit()
    try:
        from engine.model_resolver import invalidate_cache

        invalidate_cache()
    except Exception:
        pass
    return success({"model": model, "status": status})


@router.post("/ping/{model}")
async def ping_one_now(
    model: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    _ensure_admin(user)
    provider = (
        await db.execute(
            text(
                "SELECT provider FROM llm_model_pricing WHERE model = :m ORDER BY effective_from DESC LIMIT 1"
            ),
            {"m": model},
        )
    ).scalar_one_or_none()
    if not provider:
        return error(f"unknown model {model}", 404)
    from app.services.model_availability import ping_one

    result = await ping_one(model, str(provider).lower())
    return success(result)
