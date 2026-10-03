from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from app.services.archiver import (
    ARCHIVABLE_TABLES,
    DEFAULT_RETENTION_DAYS,
    DUMP_CONTENT_TYPE,
    ArchiveFileMissing,
    DumpError,
    get_archive_storage,
    is_under_archive_root,
    restore_archive,
    run_archive,
)
from models.archive import ArchiveRun, RetentionPolicy
from models.user import User

router = APIRouter(prefix="/api/admin/archives", tags=["archives"])


def _is_admin(user: User) -> bool:
    return (getattr(user.role, "value", str(user.role))).lower() == "admin"


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _serialize(r: ArchiveRun) -> dict:
    status = r.status.value if hasattr(r.status, "value") else str(r.status)
    return {
        "id": str(r.id),
        "source_table": r.source_table,
        "status": status,
        "is_manual": r.is_manual,
        "triggered_by": str(r.triggered_by) if r.triggered_by else None,
        "started_at": _iso(r.started_at),
        "completed_at": _iso(r.completed_at),
        "cutoff_at": _iso(r.cutoff_at),
        "rows_archived": r.rows_archived,
        "rows_deleted": r.rows_deleted,
        "file_uri": r.file_uri,
        "file_size_bytes": r.file_size_bytes,
        "file_sha256": r.file_sha256,
        "storage_key": getattr(r, "storage_key", None),
        "storage_backend": getattr(r, "storage_backend", None),
        "oldest_row_at": _iso(r.oldest_row_at),
        "newest_row_at": _iso(r.newest_row_at),
        "error_message": r.error_message,
        "restored_at": _iso(getattr(r, "restored_at", None)),
        "restored_rows": getattr(r, "restored_rows", 0) or 0,
        "restore_error": getattr(r, "restore_error", None),
        "notes": r.notes,
    }


async def _own_run(
    db: AsyncSession, run_id: uuid.UUID, user: User
) -> ArchiveRun | None:
    return (
        await db.execute(
            select(ArchiveRun).where(
                ArchiveRun.id == run_id, ArchiveRun.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


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
    return success(
        {
            "items": [_serialize(r) for r in rows],
            "archivable_tables": ARCHIVABLE_TABLES,
            "storage_backend": get_archive_storage().backend,
        }
    )


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
    return success(_serialize(run))


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
    run = await _own_run(db, run_id, user)
    if not run or not run.file_uri:
        return error("Archive not found", 404)
    await db.close()
    key = getattr(run, "storage_key", None)
    if key:
        storage = get_archive_storage()
        if not await storage.exists(key):
            return error("Archive file is gone from storage", 410)
        headers = {"Content-Disposition": f'attachment; filename="{Path(key).name}"'}
        if run.file_size_bytes:
            headers["Content-Length"] = str(run.file_size_bytes)
        return StreamingResponse(
            storage.get_stream(key), media_type=DUMP_CONTENT_TYPE, headers=headers
        )
    # Runs written before object storage carry a bare local path
    p = Path(run.file_uri)
    if not is_under_archive_root(p):
        return error("Archive not found", 404)
    if not p.exists():
        return error("Archive file missing on disk", 410)
    return FileResponse(path=str(p), filename=p.name, media_type=DUMP_CONTENT_TYPE)


@router.post("/{run_id}/restore")
async def restore_archive_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not _is_admin(user):
        return error("Admin only", 403)
    run = await _own_run(db, run_id, user)
    if not run:
        return error("Archive not found", 404)
    if not getattr(run, "storage_key", None):
        return error(
            "This run predates object storage, download the dump and load it by hand",
            409,
        )
    try:
        run = await restore_archive(db, run)
    except ArchiveFileMissing as e:
        return error(str(e), 410)
    except DumpError as e:
        return error(str(e), 422)
    except Exception as e:
        return error(f"Restore failed: {e}", 500)
    return success(_serialize(run))
