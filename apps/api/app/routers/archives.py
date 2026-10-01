from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services.archiver import (
    ARCHIVABLE_TABLES,
    DEFAULT_RETENTION_DAYS,
    is_under_archive_root,
    run_archive,
)
from models.archive import ArchiveRun, RetentionPolicy
from models.user import User

router = APIRouter(prefix="/api/admin/archives", tags=["archives"])


def _is_admin(user: User) -> bool:
    return (getattr(user.role, "value", str(user.role))).lower() == "admin"


@router.get("")
async def list_archive_runs(
    table: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Admin only", 403)
    q = select(ArchiveRun).where(ArchiveRun.tenant_id == user.tenant_id)
    if table:
        q = q.where(ArchiveRun.source_table == table)
    q = q.order_by(ArchiveRun.created_at.desc()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    items = [
        {
            "id": str(r.id),
            "source_table": r.source_table,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "is_manual": r.is_manual,
            "triggered_by": str(r.triggered_by) if r.triggered_by else None,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "cutoff_at": r.cutoff_at.isoformat() if r.cutoff_at else None,
            "rows_archived": r.rows_archived,
            "rows_deleted": r.rows_deleted,
            "file_uri": r.file_uri,
            "file_size_bytes": r.file_size_bytes,
            "file_sha256": r.file_sha256,
            "oldest_row_at": r.oldest_row_at.isoformat() if r.oldest_row_at else None,
            "newest_row_at": r.newest_row_at.isoformat() if r.newest_row_at else None,
            "error_message": r.error_message,
        }
        for r in rows
    ]
    return success({"items": items, "archivable_tables": ARCHIVABLE_TABLES})


@router.post("/trigger")
async def trigger_archive(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Admin only", 403)
    table = (body or {}).get("table")
    if not table or table not in ARCHIVABLE_TABLES:
        return error(f"table must be one of {ARCHIVABLE_TABLES}", 400)
    run = await run_archive(
        db, table, tenant_id=user.tenant_id, triggered_by=user.id, is_manual=True
    )
    return success(
        {
            "id": str(run.id),
            "source_table": run.source_table,
            "status": (
                run.status.value if hasattr(run.status, "value") else str(run.status)
            ),
            "rows_archived": run.rows_archived,
            "rows_deleted": run.rows_deleted,
            "file_uri": run.file_uri,
            "file_size_bytes": run.file_size_bytes,
            "error_message": run.error_message,
        }
    )


@router.get("/retention-policies")
async def list_retention_policies(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Admin only", 403)
    rows = (
        (
            await db.execute(
                select(RetentionPolicy).where(
                    RetentionPolicy.tenant_id == user.tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    by_table = {r.source_table: r for r in rows}
    items = []
    for t in ARCHIVABLE_TABLES:
        rp = by_table.get(t)
        items.append(
            {
                "source_table": t,
                "retention_days": (
                    rp.retention_days if rp else DEFAULT_RETENTION_DAYS.get(t, 30)
                ),
                "enabled": rp.enabled if rp else True,
                "description": (
                    rp.description
                    if rp
                    else f"default {DEFAULT_RETENTION_DAYS.get(t, 30)} days"
                ),
                "updated_by": str(rp.updated_by) if rp and rp.updated_by else None,
                "updated_at": (
                    rp.updated_at.isoformat() if rp and rp.updated_at else None
                ),
            }
        )
    return success({"items": items})


@router.put("/retention-policies/{table}")
async def update_retention_policy(
    table: str,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Admin only", 403)
    if table not in ARCHIVABLE_TABLES:
        return error(f"table must be one of {ARCHIVABLE_TABLES}", 400)
    days = int((body or {}).get("retention_days") or 30)
    enabled = bool((body or {}).get("enabled", True))
    description = ((body or {}).get("description") or "").strip() or None
    existing = (
        await db.execute(
            select(RetentionPolicy).where(
                RetentionPolicy.tenant_id == user.tenant_id,
                RetentionPolicy.source_table == table,
            )
        )
    ).scalar_one_or_none()
    if existing:
        existing.retention_days = days
        existing.enabled = enabled
        if description is not None:
            existing.description = description
        existing.updated_by = user.id
    else:
        existing = RetentionPolicy(
            tenant_id=user.tenant_id,
            source_table=table,
            retention_days=days,
            enabled=enabled,
            description=description,
            updated_by=user.id,
        )
        db.add(existing)
    await db.commit()
    return success(
        {
            "source_table": existing.source_table,
            "retention_days": existing.retention_days,
            "enabled": existing.enabled,
            "description": existing.description,
        }
    )


@router.get("/{run_id}/download")
async def download_archive_file(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin(user):
        return error("Admin only", 403)
    run = (
        await db.execute(
            select(ArchiveRun).where(
                ArchiveRun.id == run_id, ArchiveRun.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if not run or not run.file_uri:
        return error("Archive not found", 404)
    p = Path(run.file_uri)
    if not is_under_archive_root(p):
        return error("Archive not found", 404)
    if not p.exists():
        return error("Archive file missing on disk", 410)
    return FileResponse(
        path=str(p),
        filename=p.name,
        media_type="application/gzip",
    )
