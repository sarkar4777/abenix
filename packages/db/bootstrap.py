"""Schema bootstrap — single source of truth for fresh-install schema.

Run this BEFORE `alembic upgrade heads`. It detects whether the database
is a fresh install (no `alembic_version` table yet) and, if so:
    1. Calls ``Base.metadata.create_all()`` once — every table the ORM
       knows about lands in one shot, no replay of 40+ historical
       migrations.
    2. Runs ``alembic stamp heads`` so alembic considers the database
       to be at every current head, and future ``alembic upgrade heads``
       calls just advance from that point.

If the database already has an ``alembic_version`` table, this is a
no-op — existing installs keep their incremental upgrade path. There
is no scenario where this script destroys data.

The script supports BOTH driver shapes the platform might be using:
asyncpg-only (apps/api image — production AKS pods) and
psycopg2-only (dev-local containers and the legacy sync paths). It
detects which is available at runtime and uses it natively — no
silent fallbacks, no swallowed import errors.

Usage (any environment):
    cd packages/db && python -m bootstrap

Wired into:
    - scripts/dev-local.sh         (local Postgres in Docker)
    - scripts/deploy-azure.sh      (AKS — runs inside the api pod)
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _have_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _resolve_database_url() -> tuple[str, str]:
    """Return (url, mode) where mode is 'sync' or 'async'.

    We prefer asyncpg when the apps/api image only ships asyncpg (the
    AKS pod case); we prefer psycopg2/psycopg when only those are
    installed (dev-local and the legacy sync paths). If both are
    available we choose sync because Base.metadata.create_all is
    naturally synchronous and the rest of the script gets simpler.
    """
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not set. Bootstrap needs a Postgres connection string."
        )

    have_psycopg2 = _have_module("psycopg2")
    have_psycopg = _have_module("psycopg")
    have_asyncpg = _have_module("asyncpg")

    if have_psycopg2:
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://") and "+psycopg2" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url, "sync"

    if have_psycopg:
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://") and "+psycopg" not in url:
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url, "sync"

    if have_asyncpg:
        if url.startswith("postgresql+psycopg2://"):
            url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql+psycopg://"):
            url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url, "async"

    raise RuntimeError(
        "No usable Postgres driver found in this environment. Install one of: "
        "asyncpg, psycopg, psycopg2-binary."
    )


def _alembic_version_exists_sync(conn) -> bool:
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = 'alembic_version'"
        )
    ).first()
    return row is not None


def _parse_migration_graph() -> dict[str, set[str]]:
    """Parse every alembic versions/*.py and return {revision: set(parents)}.

    Loads each file as a Python module so that tuple/list/str down_revision
    shapes resolve correctly. Revisions whose module fails to import (rare,
    only on truly broken files) are skipped with a warning.
    """
    import importlib.util

    versions_dir = ROOT / "alembic" / "versions"
    graph: dict[str, set[str]] = {}
    for f in sorted(versions_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"_mig_{f.stem}", f)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"[bootstrap] WARN failed to parse {f.name}: {e}")
            continue
        rev = getattr(mod, "revision", None)
        down = getattr(mod, "down_revision", None)
        if not isinstance(rev, str):
            continue
        if down is None:
            parents: set[str] = set()
        elif isinstance(down, str):
            parents = {down}
        elif isinstance(down, (tuple, list)):
            parents = {p for p in down if isinstance(p, str)}
        else:
            parents = set()
        graph[rev] = parents
    return graph


def _all_ancestors(rev: str, graph: dict[str, set[str]]) -> set[str]:
    """Transitive closure of ancestors for a single revision."""
    seen: set[str] = set()
    stack = list(graph.get(rev, set()))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.get(cur, set()))
    return seen


def _heal_alembic_version_sync(conn) -> int:
    """Prune stale ancestor rows from alembic_version.

    Across environment versions, alembic_version can drift into a state
    where it tracks both a revision X AND one of X's descendants Y. This
    drift happens when a merge migration applied but the version-row
    cleanup did not commit, or when a stamp left stragglers behind. The
    next ``alembic upgrade heads`` then complains that X overlaps with Y
    and the deploy halts.

    Self-heal: for every pair (X, Y) of tracked revisions, if X is a
    transitive ancestor of Y in the script graph, DELETE the row for X.
    Idempotent and additive-safe — only deletes rows that the migration
    graph already implies as "applied via descendant."
    """
    from sqlalchemy import text

    rows: list[str] = [
        r[0]
        for r in conn.execute(text("SELECT version_num FROM alembic_version")).all()
    ]
    if len(rows) < 2:
        return 0

    try:
        graph = _parse_migration_graph()
    except Exception as e:
        print(f"[bootstrap] WARN could not parse migration graph: {e}")
        return 0

    ancestors_per_rev = {r: _all_ancestors(r, graph) for r in rows if r in graph}
    to_delete: set[str] = set()
    for r1 in rows:
        for r2 in rows:
            if r1 == r2 or r1 in to_delete:
                continue
            if r1 in ancestors_per_rev.get(r2, set()):
                to_delete.add(r1)
                break

    deleted = 0
    for r in to_delete:
        conn.execute(
            text("DELETE FROM alembic_version WHERE version_num = :v"), {"v": r}
        )
        print(f"[bootstrap] healed alembic_version: removed stale ancestor {r}")
        deleted += 1
    return deleted


def _patch_missing_columns_sync(conn) -> int:
    """Compare ORM Base.metadata to live schema, ALTER ADD any column the
    ORM declares that the live DB lacks. Idempotent, additive only —
    never drops or alters existing columns. Used when alembic_version is
    missing AND tables already exist (drift recovery)."""
    from sqlalchemy import inspect, text

    from models.base import Base

    inspector = inspect(conn)
    added = 0
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        live_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in live_cols:
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            nullable = "" if col.nullable else " NOT NULL"
            default = ""
            if col.server_default is not None:
                default_text = getattr(col.server_default, "arg", None)
                if default_text is not None:
                    default = f" DEFAULT {default_text}"
            elif col.default is not None and getattr(col.default, "is_scalar", False):
                default = f" DEFAULT {col.default.arg!r}"
            stmt = (
                f"ALTER TABLE {table.name} "
                f"ADD COLUMN IF NOT EXISTS {col.name} {col_type}{default}{nullable}"
            )
            try:
                conn.execute(text(stmt))
                added += 1
                print(f"[bootstrap] ADD COLUMN {table.name}.{col.name}")
            except Exception as e:
                print(f"[bootstrap] WARN failed to add {table.name}.{col.name}: {e}")
    return added


def _run_alembic_stamp_heads() -> None:
    """Mark every alembic head as applied, without running migrations.

    Alembic's own ``stamp`` command opens its own engine via the
    sqlalchemy.url config in ``alembic.ini`` — that config wins
    regardless of which driver bootstrap chose, so this works in both
    sync and async deployments.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.stamp(cfg, "heads")


def _bootstrap_sync(url: str) -> int:
    from sqlalchemy import create_engine, inspect

    import models  # noqa: F401  — registers every table on Base.metadata
    from models.base import Base

    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        if _alembic_version_exists_sync(conn):
            _heal_alembic_version_sync(conn)
            print(
                "[bootstrap] alembic_version table present — "
                "skipping fresh-install bootstrap."
            )
            return 0
        inspector = inspect(conn)
        had_tables = bool(inspector.get_table_names())
        if had_tables:
            print("[bootstrap] Drift recovery — tables exist but alembic untracked.")
            Base.metadata.create_all(bind=conn)
            _patch_missing_columns_sync(conn)
        else:
            print(
                "[bootstrap] Fresh DB detected — creating schema from ORM (sync driver)."
            )
            Base.metadata.create_all(bind=conn)
    return 2  # caller stamps after this returns


async def _bootstrap_async(url: str) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    import models  # noqa: F401
    from models.base import Base

    engine = create_async_engine(url, future=True)
    try:
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'alembic_version'"
                    )
                )
            ).first()
            if row is not None:
                await conn.run_sync(_heal_alembic_version_sync)
                print(
                    "[bootstrap] alembic_version table present — "
                    "skipping fresh-install bootstrap."
                )
                return 0

            def _existing_tables(sync_conn) -> list[str]:
                from sqlalchemy import inspect as _inspect

                return _inspect(sync_conn).get_table_names()

            existing = await conn.run_sync(_existing_tables)
            if existing:
                print(
                    "[bootstrap] Drift recovery — tables exist but alembic untracked."
                )
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_patch_missing_columns_sync)
            else:
                print(
                    "[bootstrap] Fresh DB detected — creating schema from ORM (async driver)."
                )
                await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    return 2  # caller stamps once asyncio.run has returned


def main() -> int:
    url, mode = _resolve_database_url()
    if mode == "sync":
        rc = _bootstrap_sync(url)
    else:
        rc = asyncio.run(_bootstrap_async(url))
    if rc == 2:
        _run_alembic_stamp_heads()
        print("[bootstrap] Schema created and alembic stamped at heads.")
        rc = 0
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
