"""Background jobs: what each scheduled job does, how its runs went, and Run now."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import job_runs
from app.core.audit import log_action
from app.core.deps import get_db, require_role
from app.core.responses import error, success

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.user import User  # noqa: E402

router = APIRouter(prefix="/api/admin/jobs", tags=["admin-jobs"])


@router.get("")
async def list_jobs(
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.platform_features import is_platform_operator, operator_rule

    data = await job_runs.list_jobs()
    # jobs act on every tenant, so only platform operators may run them
    data["can_run_jobs"] = await is_platform_operator(db, user)
    data["operator_rule"] = operator_rule()
    return success(data)


@router.post("/{job_id}/run")
async def run_job(
    job_id: str,
    request: Request,
    body: dict | None = None,
    user: User = Depends(require_role(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.platform_features import is_platform_operator

    if not await is_platform_operator(db, user):
        return error(
            "Background jobs act on every workspace, so only platform operators can run them.",
            403,
            error_code="PLATFORM_OPERATOR_REQUIRED",
        )
    confirmed = bool((body or {}).get("confirm"))
    try:
        out = await job_runs.run_now(job_id, by=user.email, confirmed=confirmed)
    except job_runs.RunNowError as e:
        return error(e.message, e.status, error_code=e.code)
    run = out.get("run") or {}
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "job.run_now",
        {
            "job": job_id,
            "status": out.get("status"),
            "summary": run.get("summary"),
            "error": run.get("error"),
        },
        request,
        resource_type="background_job",
        resource_id=job_id,
    )
    await db.commit()
    return success(out)
