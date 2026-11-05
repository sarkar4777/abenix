"""The upgrade path: a plain chunks table moves to the generation key, a partitioned one is left alone."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]
REV = ROOT / "packages/db/alembic/versions/kbops260a01_knowledge_operations.py"


def _load():
    spec = importlib.util.spec_from_file_location("kbops_rev", REV)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def plain_chunks_db(kb_db_url):
    import psycopg2

    name = f"up_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(kb_db_url)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    url = kb_db_url.rsplit("/", 1)[0] + "/" + name
    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION vector")
    cur.execute("CREATE TABLE tenants (id uuid PRIMARY KEY)")
    cur.execute(
        "CREATE TABLE knowledge_collections (id uuid PRIMARY KEY, tenant_id uuid)"
    )
    cur.execute("CREATE TABLE documents (id uuid PRIMARY KEY, kb_id uuid)")
    cur.execute(
        "CREATE TABLE chunks (id uuid PRIMARY KEY, collection_id uuid NOT NULL, "
        "document_id uuid NOT NULL, chunk_index int NOT NULL, content text NOT NULL, "
        "metadata jsonb NOT NULL DEFAULT '{}', embedding vector(1536), "
        "created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (document_id, chunk_index))"
    )
    k, d = uuid.uuid4(), uuid.uuid4()
    cur.execute("INSERT INTO knowledge_collections VALUES (%s, NULL)", (str(k),))
    cur.execute("INSERT INTO documents VALUES (%s, %s)", (str(d), str(k)))
    cur.execute(
        "INSERT INTO chunks (id, collection_id, document_id, chunk_index, content) "
        "VALUES (%s, %s, %s, 0, 'old')",
        (str(uuid.uuid4()), str(k), str(d)),
    )
    yield url, cur, str(k), str(d)
    conn.close()
    admin.cursor().execute(f"DROP DATABASE {name} WITH (FORCE)")
    admin.close()


def _upgrade(url, mod):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"transactional_ddl": True})
        with Operations.context(ctx), ctx.begin_transaction():
            mod.upgrade()
    engine.dispose()


def test_upgrade_moves_the_unique_key_and_keeps_rows(plain_chunks_db):
    url, cur, kb, doc = plain_chunks_db
    _upgrade(url, _load())
    cur.execute("SELECT embedding_generation FROM chunks")
    assert cur.fetchone()[0] == 0
    cur.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = 'chunks'::regclass AND contype = 'u'"
    )
    assert cur.fetchall() == []
    cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'")
    names = {r[0] for r in cur.fetchall()}
    assert {
        "uq_chunks_doc_index_generation",
        "ix_chunks_collection_generation",
    } <= names
    cur.execute(
        "INSERT INTO chunks (id, collection_id, document_id, chunk_index, content, "
        "embedding_generation) VALUES (%s, %s, %s, 0, 'next', 1)",
        (str(uuid.uuid4()), kb, doc),
    )
    cur.execute("SELECT count(*) FROM kb_connector_sources")
    assert cur.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_upgrade_through_asyncpg_like_the_real_env(plain_chunks_db):
    """asyncpg returns a "char" column as bytes, which once skipped these steps silently."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.ext.asyncio import create_async_engine

    url, cur, *_ = plain_chunks_db
    mod = _load()
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))

    def run(conn):
        ctx = MigrationContext.configure(conn, opts={"transactional_ddl": True})
        with Operations.context(ctx), ctx.begin_transaction():
            mod.upgrade()

    async with engine.connect() as conn:
        await conn.run_sync(run)
        await conn.commit()
    await engine.dispose()
    cur.execute("SELECT embedding_generation FROM chunks")
    assert cur.fetchone()[0] == 0


def test_upgrade_runs_twice_without_harm(plain_chunks_db):
    url, cur, *_ = plain_chunks_db
    mod = _load()
    _upgrade(url, mod)
    _upgrade(url, mod)


def test_a_partitioned_table_is_left_alone(kb_conn, kb_db_url):
    cur = kb_conn.cursor()
    mod = _load()
    engine = create_engine(kb_db_url.replace("postgresql://", "postgresql+psycopg2://"))
    with engine.connect() as conn:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            assert mod._plain_chunks() is False
    engine.dispose()
    cur.execute("SELECT relkind FROM pg_class WHERE oid = 'chunks'::regclass")
    assert cur.fetchone()[0] == "p"


def test_fresh_and_upgraded_schemas_match(kb_db_url):
    """A model column missing from the migration would only ever show up on upgrades."""
    import models  # noqa: F401
    from models.base import Base

    src = REV.read_text()
    for table in (
        "kb_reembed_jobs",
        "kb_reembed_documents",
        "kb_delete_jobs",
        "tenant_knowledge_quotas",
        "knowledge_spend",
        "kb_connector_sources",
        "kb_connector_items",
    ):
        for col in Base.metadata.tables[table].columns:
            assert f'"{col.name}"' in src, f"{table}.{col.name} not in the migration"
