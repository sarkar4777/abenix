"""Archive runs, policies, files and deletes are pinned to one tenant."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.routers import archives as archives_router
from app.services import archiver
from models.archive import ArchiveRun, RetentionPolicy
from models.user import UserRole


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class RecordingDB:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements: list[str] = []
        self.added: list = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return FakeResult(self.rows)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None

    async def refresh(self, obj):
        return None

    async def close(self):
        return None


def _admin(tenant_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id or uuid.uuid4(), role=UserRole.ADMIN
    )


def test_every_archivable_table_has_a_tenant_predicate():
    for table in archiver.ARCHIVABLE_TABLES:
        assert ":tenant_id" in archiver._TENANT_PREDICATE[table]


def test_messages_scope_goes_through_conversations():
    assert "conversations" in archiver._TENANT_PREDICATE["messages"]


def test_archive_key_is_namespaced_by_tenant():
    tenant, run_id = uuid.uuid4(), uuid.uuid4()
    key = archiver.archive_key(tenant, run_id)
    assert key == f"archives/{tenant}/{run_id}.jsonl.gz"
    local = archiver.get_archive_storage()
    assert local.backend == "local"
    assert archiver.is_under_archive_root(local.path_for(key))


def test_download_rejects_paths_outside_archive_root():
    assert not archiver.is_under_archive_root(Path("/etc/passwd"))
    assert not archiver.is_under_archive_root(archiver.ARCHIVE_ROOT / ".." / "x.gz")


def test_execution_children_are_deleted_before_parents():
    steps = archiver._CHILD_DELETES["executions"]
    tables = [t for t, _ in steps]
    for child in (
        "approvals",
        "dead_letter_executions",
        "execution_idempotency",
        "retrieval_feedback",
    ):
        assert child in tables
    assert all(":ids" in stmt for _, stmt in steps)
    assert "parent_execution_id = NULL" in steps[-1][1]


def test_models_carry_tenant_id():
    assert "tenant_id" in ArchiveRun.__table__.columns
    assert "tenant_id" in RetentionPolicy.__table__.columns
    pk = [c.name for c in RetentionPolicy.__table__.primary_key.columns]
    assert pk == ["tenant_id", "source_table"]


@pytest.mark.asyncio
async def test_list_runs_filters_by_tenant():
    user = _admin()
    db = RecordingDB()
    await archives_router.list_archive_runs(table=None, limit=50, user=user, db=db)
    assert any("archive_runs.tenant_id" in s for s in db.statements)


@pytest.mark.asyncio
async def test_policy_reads_and_writes_are_tenant_scoped():
    user = _admin()
    db = RecordingDB()
    await archives_router.list_retention_policies(user=user, db=db)
    assert any("retention_policies.tenant_id" in s for s in db.statements)

    db = RecordingDB()
    resp = await archives_router.update_retention_policy(
        table="executions",
        body={"retention_days": 7, "enabled": True},
        user=user,
        db=db,
    )
    assert json.loads(resp.body)["data"]["retention_days"] == 7
    assert any("retention_policies.tenant_id" in s for s in db.statements)
    created = [o for o in db.added if isinstance(o, RetentionPolicy)]
    assert created and created[0].tenant_id == user.tenant_id


@pytest.mark.asyncio
async def test_download_hides_other_tenants_runs():
    user = _admin()
    db = RecordingDB(rows=[])
    resp = await archives_router.download_archive_file(
        run_id=uuid.uuid4(), user=user, db=db
    )
    assert resp.status_code == 404
    assert any("archive_runs.tenant_id" in s for s in db.statements)


@pytest.mark.asyncio
async def test_download_refuses_file_uri_outside_root():
    user = _admin()
    run = SimpleNamespace(id=uuid.uuid4(), tenant_id=user.tenant_id, file_uri="/etc/passwd")
    resp = await archives_router.download_archive_file(
        run_id=run.id, user=user, db=RecordingDB(rows=[run])
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_is_refused():
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=UserRole.USER)
    resp = await archives_router.trigger_archive(
        body={"table": "executions"}, user=user, db=RecordingDB()
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_run_archive_requires_tenant():
    with pytest.raises(TypeError):
        await archiver.run_archive(RecordingDB(), "executions")  # type: ignore[call-arg]
