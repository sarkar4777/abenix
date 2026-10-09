"""Propose, prove, approve, release and watch: the proposal side of /api/improvements."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.routers.journey import note_seen
from app.services import improvements as svc
from models.user import User

router = APIRouter(prefix="/api/improvements", tags=["improvements"])

PROPOSE = require_capability("improvements.propose")


def _seen_after(
    db: AsyncSession, user: User, fn: Callable[[], Awaitable[Any]]
) -> Callable[[], Awaitable[Any]]:
    async def go() -> Any:
        out = await fn()
        await note_seen(db, user, "improvements")
        return out

    return go


async def _run(
    fn: Callable[[], Awaitable[Any]], status_code: int = 200
) -> JSONResponse:
    try:
        return success(await fn(), status_code=status_code)
    except svc.ImprovementError as e:
        return error(e.message, e.status, e.code, e.details)


class RerunBody(BaseModel):
    diff: dict[str, Any] | None = None

    model_config = {"extra": "forbid"}


class RollbackBody(BaseModel):
    reason: str = Field(default="", max_length=2000)

    model_config = {"extra": "forbid"}


@router.post("/clusters/{cluster_id}/propose")
async def propose_fix(
    cluster_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        _seen_after(db, user, lambda: svc.propose_for(db, user, cluster_id)), 202
    )


@router.get("/proposals")
async def list_proposals(
    agent_id: str | None = Query(None),
    state: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        lambda: svc.list_for(db, user, agent_id=agent_id, state=state, limit=limit)
    )


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(_seen_after(db, user, lambda: svc.get_row(db, user, proposal_id)))


@router.post("/proposals/{proposal_id}/rerun")
async def rerun_proof(
    proposal_id: str,
    body: RerunBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    diff = body.diff if body else None
    return await _run(lambda: svc.rerun(db, user, proposal_id, diff), 202)


@router.post("/proposals/{proposal_id}/request-approval")
async def request_approval(
    proposal_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(
        _seen_after(db, user, lambda: svc.request_approval_for(db, user, proposal_id))
    )


@router.post("/proposals/{proposal_id}/rollback")
async def rollback(
    proposal_id: str,
    body: RollbackBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    reason = (body.reason if body else "") or "Rolled back by a person."
    return await _run(
        _seen_after(
            db, user, lambda: svc.rollback_by_user(db, user, proposal_id, reason)
        )
    )


@router.post("/proposals/{proposal_id}/watch-check")
async def watch_check(
    proposal_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.watch_now(db, user, proposal_id))


@router.get("/budget")
async def budget(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.budget(db, user))


@router.post("/sample")
async def install_sample(
    user: User = Depends(PROPOSE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _run(lambda: svc.install_sample(db, user))
