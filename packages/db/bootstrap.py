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


def _create_missing_enums_sync(conn) -> int:
    """Create Postgres ENUM types that `create_all` will not create itself.

    A couple of models declare their enum with `create_type=False` (e.g.
    `Enum(MemoryType, name="memory_type", create_type=False)`) because an
    alembic migration owns the CREATE TYPE. That is fine on the migration
    path, but this module's fresh-install fast path uses
    `Base.metadata.create_all`, which then emits a table referencing a type
    that does not exist yet and fails with:

        asyncpg.exceptions.UndefinedObjectError: type "memory_type" does not exist

    Because the api pod runs this as an init container, that single failure
    kept the whole API from ever starting on a brand-new database. Walk the
    metadata, find every named enum, and create the ones Postgres is missing
    before create_all runs. Idempotent, and a no-op on an existing DB.
    """
    from sqlalchemy import text as _text
    from sqlalchemy import Enum as _Enum

    from models.base import Base

    created = 0
    seen: set[str] = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            enum_type = column.type
            name = getattr(enum_type, "name", None)
            if not isinstance(enum_type, _Enum) or not name or name in seen:
                continue
            seen.add(name)
            labels = list(getattr(enum_type, "enums", []) or [])
            if not labels:
                continue
            exists = conn.execute(
                _text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}
            ).first()
            if exists is not None:
                continue
            values = ", ".join("'" + str(v).replace("'", "''") + "'" for v in labels)
            # CREATE TYPE has no IF NOT EXISTS; the pg_type check above plus
            # this transaction is enough, and a racing creator is tolerated.
            conn.execute(_text(f"CREATE TYPE {name} AS ENUM ({values})"))
            print(f"[bootstrap] created missing enum type {name}")
            created += 1
    return created


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


LEAKED_TXN_SQL = (
    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
    "WHERE datname = current_database() AND pid <> pg_backend_pid() "
    "AND state LIKE 'idle in transaction%' "
    "AND xact_start < now() - interval '5 minutes'"
)


def _report_leaked(n: int | None) -> None:
    if n:
        print(
            f"[bootstrap] ended {n} session(s) idle in a transaction for over 5 minutes"
        )


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
    from sqlalchemy import create_engine, inspect, text

    import models  # noqa: F401  — registers every table on Base.metadata
    from models.base import Base

    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        if _alembic_version_exists_sync(conn):
            # an abandoned transaction would hold the locks the upgrade needs
            _report_leaked(conn.execute(text(LEAKED_TXN_SQL)).scalar())
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
            _create_missing_enums_sync(conn)
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
                # an abandoned transaction would hold the locks the upgrade needs
                _report_leaked((await conn.execute(text(LEAKED_TXN_SQL))).scalar())
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
                await conn.run_sync(_create_missing_enums_sync)
                await conn.run_sync(Base.metadata.create_all)
                await conn.run_sync(_patch_missing_columns_sync)
            else:
                print(
                    "[bootstrap] Fresh DB detected — creating schema from ORM (async driver)."
                )
                await conn.run_sync(_create_missing_enums_sync)
                await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()

    return 2  # caller stamps once asyncio.run has returned


def migration_trigger_sql() -> dict[str, list[str]]:
    """Every trigger the migrations create, with the statements that build it, read from the migrations themselves."""
    import ast
    import re

    stmts_by_file: list[list[str]] = []
    for f in sorted((ROOT / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        up = next(
            (
                n
                for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "upgrade"
            ),
            None,
        )
        if up is None:
            continue
        found: list[str] = []
        for node in ast.walk(up):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                and node.args
            ):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Call) and arg.args:
                arg = arg.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value)
        stmts_by_file.append(found)
    out: dict[str, list[str]] = {}
    for found in stmts_by_file:
        for sql in found:
            m = re.search(r"CREATE TRIGGER\s+(\w+)", sql)
            if not m:
                continue
            name = m.group(1)
            # the function it calls, any drop before it, then the trigger itself
            out[name] = [
                s
                for s in found
                if re.search(rf"(FUNCTION|TRIGGER)\s+(IF EXISTS\s+)?{name}\b", s)
            ]
    return out


def _heal_missing_triggers_sync(conn) -> list[str]:
    """Create triggers a stamped bootstrap skipped. create_all only makes tables."""
    from sqlalchemy import text

    present = {
        r[0]
        for r in conn.execute(
            text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        )
    }
    made = []
    for name, stmts in migration_trigger_sql().items():
        if name in present:
            continue
        for sql in stmts:
            conn.execute(text(sql))
        made.append(name)
    return made


def _heal_missing_tables_sync(conn) -> list[str]:
    """Create ORM tables a stamped bootstrap skipped, after every migration has run."""
    from sqlalchemy import inspect

    import models  # noqa: F401  — registers every table on Base.metadata
    from models.base import Base

    present = set(inspect(conn).get_table_names())
    missing = [t for t in Base.metadata.sorted_tables if t.name not in present]
    if missing:
        _create_missing_enums_sync(conn)
        Base.metadata.create_all(bind=conn, tables=missing)
    return [t.name for t in missing] + [
        f"trigger {n}" for n in _heal_missing_triggers_sync(conn)
    ]


def verify_heads() -> int:
    """Fail when the database is not at every migration head, so a no-op upgrade cannot pass."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    url, mode = _resolve_database_url()
    query = text("SELECT version_num FROM alembic_version")
    if mode == "sync":
        with create_engine(url).connect() as conn:
            current = {r[0] for r in conn.execute(query)}
    else:
        from sqlalchemy.ext.asyncio import create_async_engine

        async def _rows() -> set[str]:
            engine = create_async_engine(url)
            try:
                async with engine.connect() as conn:
                    return {r[0] for r in await conn.execute(query)}
            finally:
                await engine.dispose()

        current = asyncio.run(_rows())
    missing = heads - current
    if missing:
        print(
            f"[bootstrap] database is not at the migration heads, missing {sorted(missing)}, at {sorted(current)}"
        )
        return 1
    print(f"[bootstrap] database is at every head: {sorted(heads)}")
    if mode == "sync":
        with create_engine(url).begin() as conn:
            healed = _heal_missing_tables_sync(conn)
    else:

        async def _heal() -> list[str]:
            engine = create_async_engine(url)
            try:
                async with engine.begin() as conn:
                    return await conn.run_sync(_heal_missing_tables_sync)
            finally:
                await engine.dispose()

        healed = asyncio.run(_heal())
    if healed:
        print(f"[bootstrap] created what a stamped install had skipped: {healed}")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        return verify_heads()
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
