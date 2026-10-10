"""Improvements API, capture side: feedback, lessons, lesson groups and suggested test cases."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.routers.journey import note_seen
from app.services import lessons as svc
from models.user import User

router = APIRouter(prefix="/api/improvements", tags=["improvements"])

FEEDBACK = require_capability("feedback.give")


async def _run(
    fn: Callable[[], Awaitable[Any]], status_code: int = 200
) -> JSONResponse:
    try:
        return success(await fn(), status_code=status_code)
    except svc.LessonError as e:
        return error(e.message, e.status, e.code)


class FeedbackBody(BaseModel):
    execution_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    agent_id: str | None = None
    rating: int
    correction: str | None = Field(default=None, max_length=8000)


class LessonBody(BaseModel):
    agent_id: str | None = None
    execution_id: str | None = None
    note: str = Field(default="", max_length=4000)
    expected: str | None = Field(default=None, max_length=8000)
    input: str | None = Field(default=None, max_length=20000)
    output: str | None = Field(default=None, max_length=20000)
    source: str | None = Field(default=None, pattern=r"^(note|sdk)$")


class DismissBody(BaseModel):
    reason: str = Field(default="", max_length=1000)


class CasePatch(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    input_message: str | None = Field(default=None, max_length=20000)
    reference_output: str | None = Field(default=None, max_length=20000)
    assertions: list[dict[str, Any]] | None = None

    model_config = {"extra": "forbid"}


class GateBody(BaseModel):
    gating: bool


class BulkBody(BaseModel):
    ids: list[str] = Field(default_factory=list)
    action: str


@router.post("/feedback")
async def give_feedback(
    body: FeedbackBody,
    background: BackgroundTasks,
    user: User = Depends(FEEDBACK),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    async def go() -> dict[str, Any]:
        out = await svc.give_feedback(db, user, body.model_dump())
        if out.get("lesson_id"):
            background.add_task(svc.cluster_soon, user.tenant_id)
        return out

    return await _run(go, 201)


@router.get("/overview")
async def overview(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.overview(db, user, q=q, limit=limit))


@router.get("/agents/{agent_id}")
async def agent_view(
    agent_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.agent_view(db, user, agent_id))


@router.get("/clusters/{cluster_id}")
async def cluster_detail(
    cluster_id: str,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    async def go() -> dict[str, Any]:
        out = await svc.cluster_detail(db, user, cluster_id, before=before, limit=limit)
        await note_seen(db, user, "improvements")
        return out

    return await _run(go)


@router.post("/clusters/{cluster_id}/dismiss")
async def dismiss_cluster(
    cluster_id: str,
    body: DismissBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    async def go() -> Any:
        out = await svc.dismiss_cluster(db, user, cluster_id, body.reason)
        await note_seen(db, user, "improvements")
        return out

    return await _run(go)


@router.get("/lessons")
async def list_lessons(
    agent_id: str | None = None,
    source: str | None = None,
    before: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.list_lessons(
            db, user, agent_id=agent_id, source=source, before=before, limit=limit
        )
    )


@router.post("/lessons")
async def add_lesson(
    body: LessonBody,
    background: BackgroundTasks,
    user: User = Depends(FEEDBACK),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    async def go() -> dict[str, Any]:
        out = await svc.add_note(db, user, body.model_dump())
        background.add_task(svc.cluster_soon, user.tenant_id)
        return out

    return await _run(go, 201)


@router.post("/cases/bulk")
async def bulk_cases(
    body: BulkBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.bulk_cases(db, user, body.ids, body.action))


@router.post("/cases/{case_id}/accept")
async def accept_case(
    case_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.case_action(db, user, case_id, "accept"))


@router.post("/cases/{case_id}/drop")
async def drop_case(
    case_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.case_action(db, user, case_id, "drop"))


@router.patch("/cases/{case_id}")
async def patch_case(
    case_id: str,
    body: CasePatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.patch_case(db, user, case_id, body.model_dump(exclude_unset=True))
    )


@router.put("/agents/{agent_id}/gate")
async def set_gate(
    agent_id: str,
    body: GateBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.set_gate(db, user, agent_id, body.gating))


def _lesson_retention_payload(settings: dict | None, can_edit: bool) -> dict:
    raw = dict((settings or {}).get("improvements") or {})
    return {
        "retention_days": svc.retention_days(settings),
        "default_days": svc.RETENTION_DEFAULT,
        "min_days": svc.RETENTION_LIMITS[0],
        "max_days": svc.RETENTION_LIMITS[1],
        "updated_at": raw.get("retention_updated_at"),
        "updated_by_name": raw.get("retention_updated_by_name"),
        "can_edit": can_edit,
    }


@router.get("/retention")
async def get_lesson_retention(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from sqlalchemy import select

    from models.tenant import Tenant
    from models.user import UserRole

    settings = (
        await db.execute(select(Tenant.settings).where(Tenant.id == user.tenant_id))
    ).scalar()
    return success(_lesson_retention_payload(settings, user.role == UserRole.ADMIN))


@router.put("/retention")
async def put_lesson_retention(
    body: dict,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.audit import log_action
    from models.tenant import Tenant
    from models.user import UserRole

    if user.role != UserRole.ADMIN:
        return error("Only tenant admins can change how long lessons are kept.", 403)
    lo, hi = svc.RETENTION_LIMITS
    raw = (body or {}).get("retention_days")
    try:
        days = int(raw)
        if isinstance(raw, bool) or float(raw) != days:
            raise ValueError
    except (TypeError, ValueError):
        return error(
            "Retention needs a whole number of days.", 422, "INVALID_RETENTION"
        )
    if not lo <= days <= hi:
        return error(
            f"Retention must be between {lo} and {hi} days.", 422, "INVALID_RETENTION"
        )
    tenant = (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one()
    settings = dict(tenant.settings or {})
    before = svc.retention_days(settings)
    imp = dict(settings.get("improvements") or {})
    imp["retention_days"] = days
    imp["retention_updated_at"] = datetime.now(timezone.utc).isoformat()
    imp["retention_updated_by_name"] = user.full_name or user.email
    settings["improvements"] = imp
    tenant.settings = settings
    await log_action(
        db,
        user.tenant_id,
        user.id,
        action="lesson_retention_updated",
        details={"retention_days": days},
        request=request,
        resource_type="tenant",
        resource_id=str(user.tenant_id),
        old_value={"retention_days": before},
        new_value={"retention_days": days},
    )
    await db.commit()
    return success(_lesson_retention_payload(settings, True))
