"""Dump then restore round trip on sqlite, with the real coercion and insert path."""

from __future__ import annotations

import enum
import gzip
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.object_storage import LocalObjectStorage
from app.routers import archives as archives_router
from app.services import archiver
from models.archive import ArchiveRun, ArchiveRunStatus
from models.user import UserRole


class TBase(DeclarativeBase):
    pass


class Status(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"


class Thing(TBase):
    """Postgres-typed model standing in for executions, created on sqlite by hand."""

    __tablename__ = "things"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[Status] = mapped_column(sa.Enum(Status, name="thing_status"))
    cost: Mapped[Decimal | None] = mapped_column(sa.Numeric(10, 6), nullable=True)
    ok: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    n: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), sa.ForeignKey("things.id"), nullable=True
    )


DDL = (
    "CREATE TABLE things (id CHAR(32) PRIMARY KEY, created_at TIMESTAMP, "
    "payload JSON, status VARCHAR(16), cost NUMERIC(10, 6), ok BOOLEAN, "
    "n INTEGER, parent_id CHAR(32) REFERENCES things(id))"
)


class SyncAsAsync:
    """Enough of AsyncSession for restore_archive, over a sync sqlite connection."""

    def __init__(self, engine):
        self.conn = engine.connect()

    async def execute(self, stmt, params=None):
        return self.conn.execute(stmt, params) if params is not None else self.conn.execute(stmt)

    async def commit(self):
        self.conn.commit()

    async def rollback(self):
        self.conn.rollback()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text(DDL))
    yield SyncAsAsync(engine)
    engine.dispose()


PARENT = uuid.uuid4()
CHILD = uuid.uuid4()
LONER = uuid.uuid4()
T0 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

# Raw DB labels as SELECT * returns them, child listed before its parent on purpose
ROWS = [
    {
        "id": str(CHILD),
        "created_at": T0.isoformat(),
        "payload": {"k": [1, 2]},
        "status": "COMPLETED",
        "cost": "1.5",
        "ok": True,
        "n": 7,
        "parent_id": str(PARENT),
    },
    {
        "id": str(PARENT),
        "created_at": "2026-01-02T03:04:06",
        "payload": '{"nested": true}',
        "status": "running",
        "cost": 2,
        "ok": "false",
        "n": None,
        "parent_id": None,
    },
    {
        "id": str(LONER),
        "created_at": T0.isoformat(),
        "payload": None,
        "status": "COMPLETED",
        "cost": None,
        "ok": 1,
        "n": "3",
        "parent_id": str(uuid.uuid4()),  # parent never archived, stays NULL
        "legacy_col": "dropped on restore",
    },
]


def _run(tenant=None, **kw) -> ArchiveRun:
    tenant = tenant or uuid.uuid4()
    rid = uuid.uuid4()
    base = dict(
        id=rid,
        tenant_id=tenant,
        source_table="things",
        status=ArchiveRunStatus.COMPLETED,
        rows_archived=len(ROWS),
        storage_key=archiver.archive_key(tenant, rid),
        storage_backend="local",
        restored_rows=0,
    )
    base.update(kw)
    return ArchiveRun(**base)


async def _write_dump(storage, run, rows=ROWS, header=None, with_header=True):
    path = storage.path_for(run.storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as gz:
        w = archiver.DumpWriter(gz)
        if with_header:
            w.header(
                header
                or archiver.dump_header(
                    "things", run.tenant_id, run.id, list(rows[0].keys())
                )
            )
        for r in rows:
            w.row(r)
    run.file_sha256 = w.sha256
    run.file_size_bytes = path.stat().st_size
    return run


async def _restore(db, storage, run):
    return await archiver.restore_archive(
        db, run, storage=storage, table=Thing.__table__, batch_size=2
    )


async def test_dump_then_restore_round_trip_with_coercion(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = await _write_dump(storage, _run())

    run = await _restore(db, storage, run)

    assert run.restored_rows == 3
    assert run.restore_error is None
    assert run.restored_at is not None
    assert run.notes["restore"]["rows_in_dump"] == 3
    assert run.notes["restore"]["skipped_existing"] == 0
    assert run.notes["restore"]["relinked"] == 1
    assert run.notes["restore"]["dropped_columns"] == ["legacy_col"]

    got = {
        r.id: r
        for r in (await db.execute(sa.select(Thing.__table__))).all()
    }
    assert set(got) == {PARENT, CHILD, LONER}
    child, parent, loner = got[CHILD], got[PARENT], got[LONER]
    # uuid, json, enum, numeric, bool, int all came back typed
    assert isinstance(child.id, uuid.UUID)
    assert child.payload == {"k": [1, 2]}
    assert parent.payload == {"nested": True}
    assert child.status is Status.COMPLETED and parent.status is Status.RUNNING
    assert child.cost == Decimal("1.5") and parent.cost == Decimal("2")
    assert child.ok is True and parent.ok is False and loner.ok is True
    assert child.n == 7 and parent.n is None and loner.n == 3
    # timestamps survive both aware and naive inputs
    assert child.created_at.replace(tzinfo=None) == T0.replace(tzinfo=None)
    assert parent.created_at.second == 6
    # self reference re-linked after the parent landed, dangling one left NULL
    assert child.parent_id == PARENT
    assert loner.parent_id is None


async def test_second_restore_is_idempotent(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = await _write_dump(storage, _run())
    await _restore(db, storage, run)
    run = await _restore(db, storage, run)

    assert run.restored_rows == 0
    assert run.restore_error is None
    assert run.notes["restore"]["skipped_existing"] == 3
    count = (await db.execute(text("SELECT COUNT(*) FROM things"))).scalar()
    assert count == 3


async def test_partial_overlap_only_inserts_the_missing_rows(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = await _write_dump(storage, _run())
    await db.execute(
        text("INSERT INTO things (id, status) VALUES (:id, 'RUNNING')"),
        {"id": PARENT.hex},
    )
    await db.commit()
    run = await _restore(db, storage, run)
    assert run.restored_rows == 2
    assert run.notes["restore"]["skipped_existing"] == 1
    status = (
        await db.execute(text("SELECT status FROM things WHERE id = :id"), {"id": PARENT.hex})
    ).scalar()
    assert status == "RUNNING"  # existing row untouched


async def test_missing_file_is_reported_and_recorded(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = _run()
    with pytest.raises(archiver.ArchiveFileMissing):
        await _restore(db, storage, run)
    assert "gone" in run.restore_error


async def test_header_validation(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = _run()
    bad = archiver.dump_header("executions", run.tenant_id, run.id, [])
    await _write_dump(storage, run, header=bad)
    with pytest.raises(archiver.DumpError, match="executions"):
        await _restore(db, storage, run)

    run = _run()
    await _write_dump(storage, run, with_header=False)
    with pytest.raises(archiver.DumpError, match="header"):
        await _restore(db, storage, run)

    run = _run()
    other = archiver.dump_header("things", uuid.uuid4(), run.id, [])
    await _write_dump(storage, run, header=other)
    with pytest.raises(archiver.DumpError, match="tenant"):
        await _restore(db, storage, run)

    run = _run()
    newer = archiver.dump_header("things", run.tenant_id, run.id, [])
    newer["version"] = archiver.DUMP_VERSION + 1
    await _write_dump(storage, run, header=newer)
    with pytest.raises(archiver.DumpError, match="version"):
        await _restore(db, storage, run)


async def test_checksum_mismatch_refuses_before_writing(tmp_path, db):
    storage = LocalObjectStorage(tmp_path)
    run = await _write_dump(storage, _run())
    run.file_sha256 = "0" * 64
    with pytest.raises(archiver.DumpError, match="checksum"):
        await _restore(db, storage, run)
    assert (await db.execute(text("SELECT COUNT(*) FROM things"))).scalar() == 0


async def test_dump_lines_stream_across_chunk_boundaries():
    lines = [json.dumps({"i": i, "pad": "x" * 500}) for i in range(200)]
    blob = gzip.compress(("\n".join(lines) + "\n").encode())

    async def tiny_chunks():
        for i in range(0, len(blob), 37):
            yield blob[i : i + 37]

    got = [l async for l in archiver.iter_dump_lines(tiny_chunks())]
    assert got == lines


def test_coerce_value_handles_each_type():
    cv = archiver.coerce_value
    u = uuid.uuid4()
    assert cv(UUID(as_uuid=True), str(u)) == u
    assert cv(sa.DateTime(timezone=True), "2026-01-01T00:00:00").tzinfo is timezone.utc
    assert cv(sa.DateTime(timezone=True), "2026-01-01T00:00:00+02:00").utcoffset().total_seconds() == 7200
    assert cv(JSONB, '{"a": 1}') == {"a": 1}
    assert cv(JSONB, {"a": 1}) == {"a": 1}
    assert cv(sa.Enum(Status), "COMPLETED") is Status.COMPLETED
    assert cv(sa.Enum(Status), "completed") is Status.COMPLETED
    with pytest.raises(archiver.DumpError):
        cv(sa.Enum(Status), "bogus")
    assert cv(sa.Numeric(10, 6), "1.25") == Decimal("1.25")
    assert cv(sa.Float, "1.25") == 1.25
    assert cv(sa.Integer, "3") == 3
    assert cv(sa.Boolean, "t") is True and cv(sa.Boolean, "0") is False
    assert cv(sa.Text, "plain") == "plain"
    assert cv(sa.Integer, None) is None


def test_archivable_tables_resolve_to_models_with_an_id_key():
    for name in archiver.ARCHIVABLE_TABLES:
        t = archiver.table_for(name)
        assert [c.name for c in t.primary_key.columns] == ["id"]


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class RouterDB:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements: list[str] = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return FakeResult(self.rows)

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _admin():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.ADMIN)


async def test_restore_endpoint_returns_410_when_file_is_gone(tmp_path, monkeypatch):
    storage = LocalObjectStorage(tmp_path)
    monkeypatch.setattr(archiver, "get_archive_storage", lambda: storage)
    user = _admin()
    run = _run(tenant=user.tenant_id)
    db = RouterDB(rows=[run])
    resp = await archives_router.restore_archive_run(run_id=run.id, user=user, db=db)
    assert resp.status_code == 410
    assert "gone" in json.loads(resp.body)["error"]["message"]
    assert any("archive_runs.tenant_id" in s for s in db.statements)


async def test_restore_endpoint_is_tenant_scoped_and_admin_only():
    user = _admin()
    resp = await archives_router.restore_archive_run(
        run_id=uuid.uuid4(), user=user, db=RouterDB(rows=[])
    )
    assert resp.status_code == 404
    viewer = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.USER)
    resp = await archives_router.restore_archive_run(
        run_id=uuid.uuid4(), user=viewer, db=RouterDB(rows=[])
    )
    assert resp.status_code == 403


async def test_restore_endpoint_refuses_legacy_runs():
    user = _admin()
    run = SimpleNamespace(id=uuid.uuid4(), tenant_id=user.tenant_id, file_uri="/data/archives/x.gz")
    resp = await archives_router.restore_archive_run(
        run_id=run.id, user=user, db=RouterDB(rows=[run])
    )
    assert resp.status_code == 409
