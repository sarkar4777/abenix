from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
import uuid
import zlib
from collections.abc import AsyncIterable, AsyncIterator
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Table, bindparam, select, text as sql_text
from sqlalchemy import types as sqltypes
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.object_storage import ObjectStorage, get_object_storage
from models.archive import ArchiveRun, ArchiveRunStatus, RetentionPolicy
from models.base import Base

logger = logging.getLogger(__name__)

# Legacy local layout, still honoured for downloads of pre-storage-key runs
ARCHIVE_ROOT = Path(os.environ.get("ARCHIVE_ROOT", "/data/archives"))
# Keys start with archives/, so the local object root sits one level above
ARCHIVE_LOCAL_ROOT = Path(
    os.environ.get("ARCHIVE_LOCAL_ROOT", str(ARCHIVE_ROOT.parent))
)
DUMP_FORMAT = "abenix-archive"
DUMP_VERSION = 1
DUMP_CONTENT_TYPE = "application/gzip"
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


class DumpError(ValueError):
    """The dump cannot be restored as written."""


class ArchiveFileMissing(FileNotFoundError):
    """The run's object is gone from storage."""


def archive_key(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"archives/{tenant_id}/{run_id}.jsonl.gz"


def get_archive_storage() -> ObjectStorage:
    return get_object_storage(local_root=ARCHIVE_LOCAL_ROOT)


def is_under_archive_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(ARCHIVE_ROOT.resolve())
        return True
    except ValueError:
        return False


def dump_header(
    table: str, tenant_id: uuid.UUID, run_id: uuid.UUID, columns: list[str]
) -> dict[str, Any]:
    return {
        "format": DUMP_FORMAT,
        "version": DUMP_VERSION,
        "table": table,
        "tenant_id": str(tenant_id),
        "run_id": str(run_id),
        "columns": columns,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }


class DumpWriter:
    """JSON lines into a gzip text handle, hashing exactly what restore re-reads."""

    def __init__(self, gz):
        self.gz = gz
        self._h = hashlib.sha256()
        self.rows = 0

    def header(self, header: dict[str, Any]) -> None:
        self._emit(header)

    def row(self, row: dict[str, Any]) -> None:
        self._emit(row)
        self.rows += 1

    def _emit(self, obj: Any) -> None:
        line = json.dumps(obj, default=str)
        self.gz.write(line)
        self.gz.write("\n")
        self._h.update(line.encode("utf-8"))
        self._h.update(b"\n")

    @property
    def sha256(self) -> str:
        return self._h.hexdigest()


def parse_header(line: str, run: ArchiveRun) -> dict[str, Any]:
    try:
        header = json.loads(line)
    except ValueError as e:
        raise DumpError("dump is not JSON lines") from e
    if not isinstance(header, dict) or header.get("format") != DUMP_FORMAT:
        raise DumpError(
            "dump has no header line, it predates object storage and cannot be restored"
        )
    version = header.get("version")
    if not isinstance(version, int) or version < 1 or version > DUMP_VERSION:
        raise DumpError(f"unsupported dump version {version!r}")
    if header.get("table") != run.source_table:
        raise DumpError(
            f"dump is for table {header.get('table')!r}, run is for {run.source_table!r}"
        )
    if run.tenant_id is not None and header.get("tenant_id") != str(run.tenant_id):
        raise DumpError("dump belongs to another tenant")
    return header


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
    storage: ObjectStorage | None = None,
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

    spool: Path | None = None
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

        storage = storage or get_archive_storage()
        key = archive_key(tenant_id, run.id)
        oldest: datetime | None = None
        newest: datetime | None = None
        archived_ids: list[uuid.UUID] = []
        last_created: datetime | None = None
        last_id: uuid.UUID | None = None

        # Compressed spool on local disk, then one streamed put. Keyset
        # pagination keeps the table out of memory, the spool keeps the gz out.
        fd, spool_name = tempfile.mkstemp(prefix="archive-", suffix=".jsonl.gz")
        os.close(fd)
        spool = Path(spool_name)
        # newline pinned, text mode on Windows would write CRLF and break the checksum
        with gzip.open(spool, "wt", encoding="utf-8", newline="\n") as gz:
            w = DumpWriter(gz)
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
                if not archived_ids:
                    cols = list(rows[0]._mapping.keys())
                    w.header(dump_header(table, tenant_id, run.id, cols))
                for r in rows:
                    m = r._mapping
                    w.row(_row_to_dict(r))
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
            spool.unlink(missing_ok=True)
            spool = None
            run.status = ArchiveRunStatus.COMPLETED
            run.completed_at = datetime.now(timezone.utc)
            run.notes = {"reason": "no rows older than cutoff"}
            await db.commit()
            return run

        with open(spool, "rb") as fh:
            file_size = await storage.put(key, fh, DUMP_CONTENT_TYPE)
        spool.unlink(missing_ok=True)
        spool = None
        run.storage_key = key
        run.storage_backend = storage.backend
        run.file_uri = storage.url_for(key)
        run.file_size_bytes = file_size
        run.file_sha256 = w.sha256
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
            run.file_uri,
            file_size,
        )
        return run
    except Exception as e:
        logger.exception("archive %s tenant=%s failed: %s", table, tenant_id, e)
        if spool is not None:
            spool.unlink(missing_ok=True)
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


# ── Restore ────────────────────────────────────────────────────────────────


async def iter_dump_lines(stream: AsyncIterable[bytes]) -> AsyncIterator[str]:
    """Gunzip a byte stream into text lines without holding the file."""
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    buf = bytearray()

    def feed(data: bytes) -> None:
        nonlocal d
        while data:
            buf.extend(d.decompress(data))
            if not d.eof:
                return
            # gzip allows concatenated members, start a fresh one on leftovers
            data = d.unused_data
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)

    async for chunk in stream:
        feed(chunk)
        while True:
            nl = buf.find(b"\n")
            if nl < 0:
                break
            yield bytes(buf[:nl]).decode("utf-8").rstrip("\r")
            del buf[: nl + 1]
    buf.extend(d.flush())
    if buf:
        yield bytes(buf).decode("utf-8").rstrip("\r")


def table_for(name: str) -> Table:
    for mapper in Base.registry.mappers:
        if mapper.local_table.name == name:
            return mapper.local_table
    raise DumpError(f"no model for table {name}")


def coerce_value(col_type: Any, value: Any) -> Any:
    """Turn the JSON form written by the archiver back into what the column binds."""
    # a bare type class binds the same as its default instance
    if isinstance(col_type, type):
        col_type = col_type()
    if value is None:
        return None
    if isinstance(col_type, sqltypes.Uuid):
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if isinstance(col_type, sqltypes.Enum) and col_type.enum_class is not None:
        ec = col_type.enum_class
        if isinstance(value, ec):
            return value
        if value in ec.__members__:
            return ec[value]
        try:
            return ec(value)
        except ValueError as e:
            raise DumpError(f"{value!r} is not a {ec.__name__}") from e
    if isinstance(col_type, sqltypes.DateTime):
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        if col_type.timezone and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    if isinstance(col_type, sqltypes.Date):
        return value if isinstance(value, date) else date.fromisoformat(value)
    if isinstance(col_type, sqltypes.Time):
        return value if isinstance(value, time) else time.fromisoformat(value)
    if isinstance(col_type, sqltypes.JSON):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                return value
        return value
    if isinstance(col_type, sqltypes.Boolean):
        if isinstance(value, str):
            return value.strip().lower() in ("true", "t", "1", "yes")
        return bool(value)
    if isinstance(col_type, sqltypes.Float):
        return float(value)
    if isinstance(col_type, sqltypes.Numeric):
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if isinstance(col_type, sqltypes.Integer):
        return int(value)
    return value


def coerce_row(table: Table, raw: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    """Coerce every known column, report the ones the model no longer has."""
    out: dict[str, Any] = {}
    dropped: set[str] = set()
    for k, v in raw.items():
        col = table.columns.get(k)
        if col is None:
            dropped.add(k)
            continue
        out[k] = coerce_value(col.type, v)
    return out, dropped


def _insert_stmt(table: Table, columns: tuple[str, ...], pk: str):
    cols = ", ".join(columns)
    vals = ", ".join(f":{c}" for c in columns)
    return sql_text(
        f"INSERT INTO {table.name} ({cols}) VALUES ({vals}) "
        f"ON CONFLICT ({pk}) DO NOTHING"
    ).bindparams(*[bindparam(c, type_=table.columns[c].type) for c in columns])


class _BatchResult:
    def __init__(self) -> None:
        self.inserted = 0
        self.skipped = 0
        self.failed = 0
        self.first_error: str | None = None


async def _insert_batch(
    db: AsyncSession,
    table: Table,
    pk: str,
    rows: list[dict[str, Any]],
    out: _BatchResult,
) -> None:
    """Insert the rows whose primary key is absent, one at a time if the batch trips a constraint."""
    ids = [r[pk] for r in rows]
    pk_col = table.columns[pk]
    existing = set(
        (await db.execute(select(pk_col).where(pk_col.in_(ids)))).scalars().all()
    )
    fresh = [r for r in rows if r[pk] not in existing]
    out.skipped += len(rows) - len(fresh)
    by_shape: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for r in fresh:
        by_shape.setdefault(tuple(sorted(r.keys())), []).append(r)
    for shape, group in by_shape.items():
        stmt = _insert_stmt(table, shape, pk)
        try:
            await db.execute(stmt, group)
            await db.commit()
            out.inserted += len(group)
            continue
        except IntegrityError:
            await db.rollback()
        # A parent row (agent, conversation, ...) is gone, keep the rows that still fit
        for r in group:
            try:
                await db.execute(stmt, [r])
                await db.commit()
                out.inserted += 1
            except IntegrityError as e:
                await db.rollback()
                out.failed += 1
                if out.first_error is None:
                    out.first_error = str(getattr(e, "orig", e))[:500]


async def _scan_dump(
    storage: ObjectStorage, run: ArchiveRun
) -> tuple[dict[str, Any], int]:
    """First pass. Validate the header and checksum before touching the table."""
    h = hashlib.sha256()
    header: dict[str, Any] | None = None
    count = 0
    async for line in iter_dump_lines(storage.get_stream(run.storage_key)):
        h.update(line.encode("utf-8"))
        h.update(b"\n")
        if header is None:
            header = parse_header(line, run)
            continue
        count += 1
    if header is None:
        raise DumpError("dump is empty")
    if run.file_sha256 and h.hexdigest() != run.file_sha256:
        raise DumpError("dump checksum does not match the run, refusing to restore")
    return header, count


async def restore_archive(
    db: AsyncSession,
    run: ArchiveRun,
    *,
    storage: ObjectStorage | None = None,
    table: Table | None = None,
    batch_size: int = BATCH_SIZE,
) -> ArchiveRun:
    """Stream the dump back into its table. Existing rows are left alone."""
    storage = storage or get_archive_storage()
    try:
        if not run.storage_key:
            raise DumpError(
                "run has no object-storage key, download the file and load it by hand"
            )
        if run.status != ArchiveRunStatus.COMPLETED or not run.rows_archived:
            raise DumpError("run did not archive any rows")
        if not await storage.exists(run.storage_key):
            raise ArchiveFileMissing(
                f"archive {run.storage_key} is gone from {storage.backend} storage"
            )
        table = table if table is not None else table_for(run.source_table)
        pk_cols = [c.name for c in table.primary_key.columns]
        if len(pk_cols) != 1:
            raise DumpError(f"{table.name} needs a single-column primary key")
        pk = pk_cols[0]
        self_refs = [
            c.name
            for c in table.columns
            if any(fk.column.table is table for fk in c.foreign_keys)
        ]

        header, expected = await _scan_dump(storage, run)

        result = _BatchResult()
        seen = 0
        dropped: set[str] = set()
        # (row id, column, parent id) for self references, re-linked after the inserts
        deferred: list[tuple[Any, str, Any]] = []
        batch: list[dict[str, Any]] = []
        first = True
        async for line in iter_dump_lines(storage.get_stream(run.storage_key)):
            if first:
                first = False
                continue
            row, gone = coerce_row(table, json.loads(line))
            dropped |= gone
            if pk not in row or row[pk] is None:
                raise DumpError("dump row without a primary key")
            for col in self_refs:
                if row.get(col) is not None:
                    deferred.append((row[pk], col, row[col]))
                    row[col] = None
            batch.append(row)
            seen += 1
            if len(batch) >= batch_size:
                await _insert_batch(db, table, pk, batch, result)
                batch = []
        if batch:
            await _insert_batch(db, table, pk, batch, result)
        if seen != expected:
            raise DumpError(f"dump changed while restoring ({seen} vs {expected} rows)")

        relinked = 0
        pk_type = table.columns[pk].type
        for col in self_refs:
            stmt = sql_text(
                f"UPDATE {table.name} SET {col} = :parent "
                f"WHERE {pk} = :id AND {col} IS NULL "
                f"AND EXISTS (SELECT 1 FROM {table.name} WHERE {pk} = :parent)"
            ).bindparams(
                bindparam("parent", type_=pk_type), bindparam("id", type_=pk_type)
            )
            todo = [(i, p) for i, c, p in deferred if c == col]
            for start in range(0, len(todo), batch_size):
                for i, p in todo[start : start + batch_size]:
                    res = await db.execute(stmt, {"id": i, "parent": p})
                    relinked += res.rowcount if res.rowcount and res.rowcount > 0 else 0
                await db.commit()

        run.restored_at = datetime.now(timezone.utc)
        run.restored_rows = result.inserted
        run.restore_error = (
            f"{result.failed} rows failed a constraint: {result.first_error}"
            if result.failed
            else None
        )
        notes = dict(run.notes or {})
        notes["restore"] = {
            "dump_version": header.get("version"),
            "rows_in_dump": expected,
            "skipped_existing": result.skipped,
            "failed_constraint": result.failed,
            "relinked": relinked,
            "dropped_columns": sorted(dropped),
        }
        run.notes = notes
        await db.commit()
        logger.info(
            "restore %s tenant=%s run=%s: %d inserted, %d present, %d failed",
            run.source_table,
            run.tenant_id,
            run.id,
            result.inserted,
            result.skipped,
            result.failed,
        )
        return run
    except Exception as e:
        logger.exception("restore run=%s failed: %s", run.id, e)
        await db.rollback()
        run.restore_error = str(e)[:2000]
        await db.commit()
        raise
