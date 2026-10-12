"""One agent per slug in a workspace: duplicates renamed by the migration, free slugs on create and rename, retry on a race."""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import uuid

import pytest
import sqlalchemy as sa

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _migration():
    path = ROOT / "packages/db/alembic/versions/agt258a01_agent_slug_unique.py"
    spec = importlib.util.spec_from_file_location("agt258a01", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_migration_renames_duplicates_and_adds_the_index():
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    mod = _migration()
    assert mod.down_revision == "tel258a05"
    eng = sa.create_engine("sqlite://")
    with eng.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE agents (id TEXT PRIMARY KEY, tenant_id TEXT, slug TEXT, created_at TEXT)"
            )
        )
        rows = [
            ("a1", "t1", "watcher", "2026-10-11 10:00"),
            ("a2", "t1", "watcher", "2026-10-11 10:05"),
            ("a3", "t1", "watcher", "2026-10-11 10:09"),
            ("a4", "t1", "watcher-2", "2026-10-11 09:00"),
            ("a5", "t2", "watcher", "2026-10-11 10:01"),
        ]
        for r in rows:
            conn.execute(
                sa.text("INSERT INTO agents VALUES (:i, :t, :s, :c)"),
                dict(zip("itsc", r)),
            )
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        got = dict(conn.execute(sa.text("SELECT id, slug FROM agents")).fetchall())
        assert got == {
            "a1": "watcher",
            "a2": "watcher-3",
            "a3": "watcher-4",
            "a4": "watcher-2",
            "a5": "watcher",
        }
        names = {ix["name"] for ix in sa.inspect(conn).get_indexes("agents")}
        assert mod.INDEX in names
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                sa.text("INSERT INTO agents VALUES ('a6', 't1', 'watcher', 'x')")
            )


class _DB:
    """Answers whether a slug is taken, and fails the first commit like a racing create would."""

    def __init__(self, taken: set[str], fail_commits: int = 0) -> None:
        self.taken = taken
        self.fail_commits = fail_commits
        self.added = []
        self.rollbacks = 0

    async def execute(self, q):
        from types import SimpleNamespace

        params = q.compile().params
        slug = next(v for k, v in params.items() if k.startswith("slug"))
        found = uuid.uuid4() if slug in self.taken else None
        return SimpleNamespace(scalar_one_or_none=lambda: found)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commits:
            self.fail_commits -= 1
            raise sa.exc.IntegrityError(
                "INSERT",
                {},
                Exception('duplicate key violates "uq_agents_tenant_slug"'),
            )

    async def rollback(self):
        self.rollbacks += 1


def test_a_free_slug_is_the_base_or_a_suffixed_one():
    from app.routers import agents as A

    async def go():
        t = uuid.uuid4()
        assert await A._free_slug(_DB(set()), t, "watcher") == "watcher"
        got = await A._free_slug(_DB({"watcher"}), t, "watcher")
        assert got.startswith("watcher-") and len(got) == len("watcher-") + 6

    asyncio.run(go())


def test_a_racing_create_retries_with_another_slug():
    from types import SimpleNamespace

    from app.routers import agents as A

    async def go():
        agent = SimpleNamespace(slug="watcher")
        db = _DB(set(), fail_commits=1)
        await A._insert_agent(db, agent)
        assert db.rollbacks == 1 and agent.slug.startswith("watcher-")

    asyncio.run(go())


def test_other_integrity_errors_are_not_swallowed():
    from types import SimpleNamespace

    from app.routers import agents as A

    class _Other(_DB):
        async def commit(self):
            raise sa.exc.IntegrityError("INSERT", {}, Exception("fk_agents_creator"))

    async def go():
        with pytest.raises(sa.exc.IntegrityError):
            await A._insert_agent(_Other(set()), SimpleNamespace(slug="x"))

    asyncio.run(go())


def test_the_model_declares_the_unique_index():
    from models.agent import Agent

    ix = {i.name: i for i in Agent.__table__.indexes}
    assert ix["uq_agents_tenant_slug"].unique
    assert [c.name for c in ix["uq_agents_tenant_slug"].columns] == [
        "tenant_id",
        "slug",
    ]
