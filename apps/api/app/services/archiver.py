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

from sqlalchemy import bindparam, select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from models.archive import ArchiveRun, ArchiveRunStatus, RetentionPolicy

logger = logging.getLogger(__name__)

# Local volume. No object-storage abstraction exists in the API yet.
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
BATCH_SIZE = 1000
MAX_ROWS_PER_RUN = int(os.environ.get("ARCHIVE_MAX_ROWS_PER_RUN", "200000"))

# How each archivable table is pinned to a tenant
_TENANT_PREDICATE = {
    "executions": "tenant_id = :tenant_id",
    "activity_logs": "tenant_id = :tenant_id",
    "code_asset_invocations": "tenant_id = :tenant_id",
    "ml_model_invocations": "tenant_id = :tenant_id",
    "kb_query_invocations": "tenant_id = :tenant_id",
    "messages": (
        "conversation_id IN (SELECT id FROM conversations WHERE tenant_id = :tenant_id)"
    ),
}

# RESTRICT children that must go before their parent rows, in order
_CHILD_DELETES: dict[str, list[tuple[str, str]]] = {
    "executions": [
        ("approvals", "DELETE FROM approvals WHERE agent_execution_id IN :ids"),
        (
            "dead_letter_executions",
            "DELETE FROM dead_letter_executions WHERE execution_id IN :ids",
        ),
        (
            "execution_idempotency",
            "DELETE FROM execution_idempotency WHERE execution_id IN :ids",
        ),
        (
            "retrieval_feedback",
            "DELETE FROM retrieval_feedback WHERE execution_id IN :ids",
        ),
        (
            "executions",
            "UPDATE executions SET parent_execution_id = NULL "
            "WHERE parent_execution_id IN :ids AND id NOT IN :ids",
        ),
    ],
}


def _path_for(tenant_id: uuid.UUID, table: str, run_started: datetime) -> Path:
    yyyymm = run_started.strftime("%Y-%m")
    fname = f"{table}-{run_started.strftime('%Y-%m-%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.jsonl.gz"
    return ARCHIVE_ROOT / str(tenant_id) / table / yyyymm / fname


def is_under_archive_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ARCHIVE_ROOT.resolve())
        return True
    except ValueError:
        return False


async def _resolve_retention(
    db: AsyncSession, tenant_id: uuid.UUID, table: str
) -> tuple[int, bool]:
    rp = (
        await db.execute(
            select(RetentionPolicy).where(
                RetentionPolicy.tenant_id == tenant_id,
                RetentionPolicy.source_table == table,
            )
        )
    ).scalar_one_or_none()
    if rp:
        return rp.retention_days, rp.enabled
    return DEFAULT_RETENTION_DAYS.get(table, 30), True


def _row_to_dict(row) -> dict[str, Any]:
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


async def _existing_tables(db: AsyncSession, names: set[str]) -> set[str]:
    if not names:
        return set()
    res = await db.execute(
        sql_text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name IN :names"
        ).bindparams(bindparam("names", expanding=True)),
        {"names": list(names)},
    )
    return {r[0] for r in res.all()}


async def _delete_batch(
    db: AsyncSession, table: str, ids: list[uuid.UUID], present: set[str]
) -> int:
    """Children first, then the parent rows, all in one transaction."""
    params = {"ids": ids}
    for child_table, stmt in _CHILD_DELETES.get(table, []):
        if child_table not in present:
            continue
        await db.execute(
            sql_text(stmt).bindparams(bindparam("ids", expanding=True)), params
        )
    res = await db.execute(
        sql_text(f"DELETE FROM {table} WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        params,
    )
    await db.commit()
    return res.rowcount or 0


async def run_archive(
    db: AsyncSession,
    table: str,
    *,
    tenant_id: uuid.UUID,
    triggered_by: uuid.UUID | None = None,
    is_manual: bool = False,
) -> ArchiveRun:
    if table not in ARCHIVABLE_TABLES:
        raise ValueError(f"table {table} not archivable")
    run = ArchiveRun(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        source_table=table,
        triggered_by=triggered_by,
        is_manual=is_manual,
        status=ArchiveRunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    path: Path | None = None
    try:
        retention_days, enabled = await _resolve_retention(db, tenant_id, table)
        if not enabled and not is_manual:
            run.status = ArchiveRunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.notes = {"reason": "retention policy disabled"}
            await db.commit()
            return run
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        run.cutoff_at = cutoff
        await db.commit()

        scope = _TENANT_PREDICATE[table]
        first_q = sql_text(
            f"SELECT * FROM {table} WHERE {scope} AND created_at < :cutoff "
            "ORDER BY created_at ASC, id ASC LIMIT :batch"
        )
        next_q = sql_text(
            f"SELECT * FROM {table} WHERE {scope} AND created_at < :cutoff "
            "AND (created_at, id) > (:last_created, :last_id) "
            "ORDER BY created_at ASC, id ASC LIMIT :batch"
        )

        path = _path_for(tenant_id, table, run.started_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        oldest: datetime | None = None
        newest: datetime | None = None
        archived_ids: list[uuid.UUID] = []
        last_created: datetime | None = None
        last_id: uuid.UUID | None = None

        # Keyset-paginated stream so a big table never lands in memory at once
        with gzip.open(path, "wt", encoding="utf-8") as gz:
            while len(archived_ids) < MAX_ROWS_PER_RUN:
                params: dict[str, Any] = {
                    "tenant_id": tenant_id,
                    "cutoff": cutoff,
                    "batch": min(BATCH_SIZE, MAX_ROWS_PER_RUN - len(archived_ids)),
                }
                if last_id is None:
                    rows = (await db.execute(first_q, params)).all()
                else:
                    params.update({"last_created": last_created, "last_id": last_id})
                    rows = (await db.execute(next_q, params)).all()
                if not rows:
                    break
                for r in rows:
                    m = r._mapping
                    d = _row_to_dict(r)
                    line = json.dumps(d, default=str)
                    gz.write(line)
                    gz.write("\n")
                    h.update(line.encode("utf-8"))
                    archived_ids.append(m["id"])
                    ca = m.get("created_at")
                    if isinstance(ca, datetime):
                        oldest = ca if oldest is None or ca < oldest else oldest
                        newest = ca if newest is None or ca > newest else newest
                last_created = rows[-1]._mapping["created_at"]
                last_id = rows[-1]._mapping["id"]
                if len(rows) < params["batch"]:
                    break

        if not archived_ids:
            path.unlink(missing_ok=True)
            run.status = ArchiveRunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.notes = {"reason": "no rows older than cutoff"}
            await db.commit()
            return run

        file_size = path.stat().st_size
        run.file_uri = str(path)
        run.file_size_bytes = file_size
        run.file_sha256 = h.hexdigest()
        run.rows_archived = len(archived_ids)
        run.oldest_row_at = oldest
        run.newest_row_at = newest
        await db.commit()

        child_tables = {t for t, _ in _CHILD_DELETES.get(table, [])}
        present = await _existing_tables(db, child_tables)
        deleted = 0
        for i in range(0, len(archived_ids), BATCH_SIZE):
            deleted += await _delete_batch(
                db, table, archived_ids[i : i + BATCH_SIZE], present
            )

        run.rows_deleted = deleted
        run.status = ArchiveRunStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "archive %s tenant=%s: %d rows -> %s (%d bytes)",
            table,
            tenant_id,
            len(archived_ids),
            path,
            file_size,
        )
        return run
    except Exception as e:
        logger.exception("archive %s tenant=%s failed: %s", table, tenant_id, e)
        await db.rollback()
        run.status = ArchiveRunStatus.FAILED
        run.error_message = str(e)[:2000]
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return run


async def run_all_archives(session_factory) -> list[ArchiveRun]:
    from models.tenant import Tenant

    runs: list[ArchiveRun] = []
    async with session_factory() as db:
        tenant_ids = [row[0] for row in (await db.execute(select(Tenant.id))).all()]
    for tenant_id in tenant_ids:
        for table in ARCHIVABLE_TABLES:
            async with session_factory() as db:
                try:
                    run = await run_archive(db, table, tenant_id=tenant_id)
                    runs.append(run)
                except Exception as e:
                    logger.exception(
                        "scheduled archive %s tenant=%s failed: %s", table, tenant_id, e
                    )
    return runs
