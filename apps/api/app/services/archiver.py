from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from models.archive import ArchiveRun, ArchiveRunStatus, RetentionPolicy

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT", "/data/archives"))
DEFAULT_RETENTION_DAYS = {
    "code_asset_invocations": 30,
    "ml_model_invocations": 30,
    "kb_query_invocations": 30,
    "executions": 60,
    "messages": 60,
    "activity_logs": 90,
}
ARCHIVABLE_TABLES = list(DEFAULT_RETENTION_DAYS.keys())
BATCH_DELETE_SIZE = 1000


def _path_for(table: str, run_started: datetime) -> Path:
    yyyymm = run_started.strftime("%Y-%m")
    fname = f"{table}-{run_started.strftime('%Y-%m-%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    return ARCHIVE_ROOT / table / yyyymm / fname


async def _resolve_retention_days(db: AsyncSession, table: str) -> int:
    rp = (
        await db.execute(
            select(RetentionPolicy).where(RetentionPolicy.source_table == table)
        )
    ).scalar_one_or_none()
    if rp and rp.enabled:
        return rp.retention_days
    return DEFAULT_RETENTION_DAYS.get(table, 30)


async def _row_to_dict(row) -> dict[str, Any]:
    out = {}
    for k, v in row._mapping.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif hasattr(v, "value"):
            out[k] = getattr(v, "value", str(v))
        else:
            out[k] = v
    return out


async def run_archive(
    db: AsyncSession,
    table: str,
    *,
    triggered_by: uuid.UUID | None = None,
    is_manual: bool = False,
) -> ArchiveRun:
    if table not in ARCHIVABLE_TABLES:
        raise ValueError(f"table {table} not archivable")
    run = ArchiveRun(
        id=uuid.uuid4(),
        source_table=table,
        triggered_by=triggered_by,
        is_manual=is_manual,
        status=ArchiveRunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    try:
        retention_days = await _resolve_retention_days(db, table)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        run.cutoff_at = cutoff
        await db.commit()

        rows = (
            await db.execute(
                sql_text(
                    f"SELECT * FROM {table} WHERE created_at < :cutoff ORDER BY created_at ASC LIMIT 100000"
                ),
                {"cutoff": cutoff},
            )
        ).all()
        if not rows:
            run.status = ArchiveRunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.notes = {"reason": "no rows older than cutoff"}
            await db.commit()
            return run

        path = _path_for(table, run.started_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        oldest = None
        newest = None
        with gzip.open(path, "wt", encoding="utf-8") as gz:
            for r in rows:
                d = await _row_to_dict(r)
                line = json.dumps(d, default=str)
                gz.write(line)
                gz.write("\n")
                h.update(line.encode("utf-8"))
                ca = d.get("created_at")
                if ca:
                    if oldest is None or ca < oldest:
                        oldest = ca
                    if newest is None or ca > newest:
                        newest = ca

        file_size = path.stat().st_size
        run.file_uri = str(path)
        run.file_size_bytes = file_size
        run.file_sha256 = h.hexdigest()
        run.rows_archived = len(rows)
        if oldest:
            run.oldest_row_at = datetime.fromisoformat(str(oldest))
        if newest:
            run.newest_row_at = datetime.fromisoformat(str(newest))
        await db.commit()

        deleted = 0
        while True:
            del_q = sql_text(
                f"DELETE FROM {table} WHERE id IN ("
                f"SELECT id FROM {table} WHERE created_at < :cutoff "
                f"ORDER BY created_at ASC LIMIT :batch)"
            )
            res = await db.execute(
                del_q, {"cutoff": cutoff, "batch": BATCH_DELETE_SIZE}
            )
            n = res.rowcount or 0
            deleted += n
            await db.commit()
            if n == 0 or deleted >= len(rows):
                break

        run.rows_deleted = deleted
        run.status = ArchiveRunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "archive %s: %d rows -> %s (%d bytes)", table, len(rows), path, file_size
        )
        return run
    except Exception as e:
        logger.exception("archive %s failed: %s", table, e)
        run.status = ArchiveRunStatus.FAILED
        run.error_message = str(e)[:2000]
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return run


async def run_all_archives(session_factory) -> list[ArchiveRun]:
    runs: list[ArchiveRun] = []
    for table in ARCHIVABLE_TABLES:
        async with session_factory() as db:
            try:
                run = await run_archive(db, table)
                runs.append(run)
            except Exception as e:
                logger.exception("scheduled archive %s failed: %s", table, e)
    return runs
