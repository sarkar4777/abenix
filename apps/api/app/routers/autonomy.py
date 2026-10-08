"""Earned autonomy API: the ladder, grants, the action ledger, reviews and the sample plant."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services import autonomy as svc
from models.user import User

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])

VIEW = require_capability("autonomy.view")
MANAGE = require_capability("autonomy.manage")
GRANT = require_capability("autonomy.grant")
REVIEW = require_capability("actions.review")


async def _run(
    fn: Callable[[], Awaitable[Any]], status_code: int = 200
) -> JSONResponse:
    try:
        return success(await fn(), status_code=status_code)
    except svc.AutonomyError as e:
        return error(e.message, e.status, e.code, e.details)


class DemoteBody(BaseModel):
    to_level: int = Field(ge=0, le=4)
    reason: str = Field(default="", max_length=2000)


class GrantPatch(BaseModel):
    state: str | None = None
    scope: dict[str, Any] | None = None
    ceiling: int | None = Field(default=None, ge=0, le=4)

    model_config = {"extra": "forbid"}


class ActionTypePatch(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    description: str | None = None
    world_model: dict[str, Any] | None = None
    outcome_probe: dict[str, Any] | None = None
    limits_decision_key: str | None = Field(default=None, max_length=160)
    max_band_width: float | None = None
    match: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    reversible: bool | None = None
    ceiling: int | None = Field(default=None, ge=0, le=4)

    model_config = {"extra": "forbid"}


class PartTestBody(BaseModel):
    part: str
    action_id: str | None = None


class ActionTypeSpec(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    key: str | None = Field(
        default=None, max_length=200, pattern=r"^[a-z0-9][a-z0-9._:-]*$"
    )
    description: str = ""
    world_model: dict[str, Any] | None = None
    outcome_probe: dict[str, Any] | None = None
    limits_decision_key: str | None = Field(default=None, max_length=160)
    max_band_width: float | None = None
    match: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    reversible: bool | None = None


class EnrolBody(BaseModel):
    agent_id: str
    tool_name: str = Field(min_length=1, max_length=160)
    action_type: ActionTypeSpec
    scope: dict[str, Any] | None = None


class SampleRunBody(BaseModel):
    count: int = Field(default=1, ge=1, le=5)


class ReviewBody(BaseModel):
    answer: str
    alternative: str | None = Field(default=None, max_length=2000)


class OutcomeBody(BaseModel):
    value: float | int | str
    note: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, pattern=r"^(manual|api)$")


class HarmBody(BaseModel):
    note: str = Field(default="", max_length=2000)


class ProposeBody(BaseModel):
    agent_id: str | None = None
    action_key: str = Field(min_length=1, max_length=200)
    target: str | None = Field(default=None, max_length=500)
    arguments: dict[str, Any] = Field(default_factory=dict)
    intent: str | None = Field(default=None, max_length=4000)
    prediction: dict[str, Any] | None = None


class ExecutedBody(BaseModel):
    ok: bool
    result_preview: str | None = Field(default=None, max_length=20000)


@router.get("/overview")
async def overview(
    user: User = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.overview(db, user))


@router.get("/grants/{grant_id}")
async def get_grant(
    grant_id: str, user: User = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.grant_detail(db, user, grant_id))


@router.get("/grants/{grant_id}/actions")
async def grant_actions(
    grant_id: str,
    status: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    before: str | None = Query(None, max_length=64),
    user: User = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.grant_actions_page(db, user, grant_id, status, limit, before)
    )


@router.post("/grants/{grant_id}/promote")
async def promote(
    grant_id: str, user: User = Depends(GRANT), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.promote(db, user, grant_id), 201)


@router.post("/grants/{grant_id}/demote")
async def demote(
    grant_id: str,
    body: DemoteBody,
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.demote_by_user(db, user, grant_id, body.to_level, body.reason)
    )


@router.patch("/grants/{grant_id}")
async def patch_grant(
    grant_id: str,
    body: GrantPatch,
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.patch_grant(db, user, grant_id, body.model_dump(exclude_unset=True))
    )


@router.delete("/grants/{grant_id}")
async def delete_grant(
    grant_id: str, user: User = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.remove_grant(db, user, grant_id))


@router.get("/action-types")
async def list_action_types(
    user: User = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    async def go() -> list[dict[str, Any]]:
        return [
            svc.action_type_json(t)
            for t in await svc.list_action_types(db, user.tenant_id)
        ]

    return await _run(go)


@router.get("/action-types/{type_id}")
async def get_action_type(
    type_id: str, user: User = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    async def go() -> dict[str, Any]:
        at = await svc.get_action_type(db, user.tenant_id, type_id)
        if at is None:
            raise svc.AutonomyError("This action type was not found.", 404, "NOT_FOUND")
        return svc.action_type_json(at)

    return await _run(go)


@router.patch("/action-types/{type_id}")
async def patch_action_type(
    type_id: str,
    body: ActionTypePatch,
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.patch_action_type(
            db, user, type_id, body.model_dump(exclude_unset=True)
        )
    )


@router.post("/action-types/{type_id}/test")
async def test_action_type(
    type_id: str,
    body: PartTestBody,
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.test_action_type(db, user, type_id, body.part, body.action_id)
    )


@router.get("/enrol/options")
async def enrol_options(
    agent_id: str = Query(..., max_length=64),
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.enrol_options(db, user, agent_id))


@router.post("/enrol")
async def enrol(
    body: EnrolBody, user: User = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    spec = body.action_type.model_dump(exclude_none=True)
    return await _run(
        lambda: svc.enrol(db, user, body.agent_id, body.tool_name, spec, body.scope),
        201,
    )


@router.post("/sample")
async def install_sample(
    user: User = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.install_sample(db, user))


@router.post("/sample/run")
async def run_sample(
    body: SampleRunBody | None = None,
    user: User = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    count = body.count if body else 1
    return await _run(lambda: svc.run_sample(db, user, count), 202)


@router.get("/reviews")
async def reviews(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(REVIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.reviews(db, user, limit))


@router.post("/actions/propose")
async def propose(
    body: ProposeBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.propose(db, user, body.model_dump()), 201)


@router.get("/actions/{action_id}")
async def get_action(
    action_id: str, user: User = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _run(lambda: svc.action_detail(db, user, action_id))


@router.get("/actions/{action_id}/wait")
async def wait_action(
    action_id: str,
    timeout_s: int = Query(30, ge=1, le=120),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.wait(db, user, action_id, timeout_s))


@router.post("/actions/{action_id}/executed")
async def mark_executed(
    action_id: str,
    body: ExecutedBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.mark_executed(db, user, action_id, body.ok, body.result_preview)
    )


@router.post("/actions/{action_id}/review")
async def review(
    action_id: str,
    body: ReviewBody,
    user: User = Depends(REVIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.review(db, user, action_id, body.answer, body.alternative)
    )


@router.post("/actions/{action_id}/outcome")
async def record_outcome(
    action_id: str,
    body: OutcomeBody,
    user: User = Depends(REVIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # an API key caller is an app reporting through the SDK
    source = body.source or (
        "api" if getattr(user, "_api_key_id", None) is not None else "manual"
    )
    return await _run(
        lambda: svc.record_outcome(
            db, user, action_id, body.value, body.note, source=source
        )
    )


@router.post("/actions/{action_id}/harm")
async def flag_harm(
    action_id: str,
    body: HarmBody,
    user: User = Depends(REVIEW),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.flag_harm(db, user, action_id, body.note))
