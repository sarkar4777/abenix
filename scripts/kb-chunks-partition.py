#!/usr/bin/env python3
"""Move an existing chunks table onto hash partitions, the old one stays as chunks_legacy until --drop-legacy."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "db"))

import chunks_store as cs

NEW = "chunks_next"
COLUMNS = (
    "id, collection_id, document_id, chunk_index, content, metadata, embedding, "
    "dedicated_index, created_at, embedding_generation"
)
SELECT_COLUMNS = (
    "c.id, c.collection_id, c.document_id, c.chunk_index, c.content, c.metadata, "
    "c.embedding{cast}, c.dedicated_index, c.created_at, c.embedding_generation"
)


def log(message: str) -> None:
    print(f"[kb-chunks-partition] {message}", flush=True)


def relkind(cur, table: str) -> str | None:
    cur.execute(
        "SELECT relkind::text FROM pg_class WHERE oid = to_regclass(%s)", (table,)
    )
    row = cur.fetchone()
    return row[0] if row else None


def ensure_columns(cur) -> None:
    cur.execute(cs.DEDICATED_COLUMN)
    cur.execute(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
        "embedding_generation INTEGER NOT NULL DEFAULT 0"
    )


def copy_rows(conn, cast: str, batch: int) -> int:
    """Keyset batches, safe to stop and run again."""
    copied = 0
    last = "00000000-0000-0000-0000-000000000000"
    columns = SELECT_COLUMNS.format(cast=cast)
    while True:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH page AS (
                    SELECT {columns} FROM chunks c WHERE c.id > %s ORDER BY c.id LIMIT %s
                ), moved AS (
                    INSERT INTO {NEW} ({COLUMNS}) SELECT * FROM page
                    ON CONFLICT DO NOTHING
                )
                SELECT count(*), max(id::text) FROM page
                """,
                (last, batch),
            )
            count, highest = cur.fetchone()
        conn.commit()
        if not count:
            return copied
        copied += count
        last = highest
        log(f"copied {copied} rows")


def catch_up(cur, cast: str) -> tuple[int, int]:
    """Bring the new table level with the old one, rows added and removed since the copy."""
    columns = SELECT_COLUMNS.format(cast=cast)
    cur.execute(
        f"""
        INSERT INTO {NEW} ({COLUMNS})
        SELECT {columns} FROM chunks c
        WHERE NOT EXISTS (
            SELECT 1 FROM {NEW} n
            WHERE n.collection_id = c.collection_id AND n.id = c.id)
        ON CONFLICT DO NOTHING
        """
    )
    added = cur.rowcount
    cur.execute(
        f"""
        DELETE FROM {NEW} n
        WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.id = n.id)
        """
    )
    return added, cur.rowcount


def swap(cur, partitions: int) -> None:
    cur.execute("ALTER TABLE chunks RENAME TO chunks_legacy")
    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'chunks_legacy' "
        "AND indexname NOT LIKE '%\\_pkey'"
    )
    for (name,) in cur.fetchall():
        cur.execute(f'ALTER INDEX "{name}" RENAME TO "{name}_legacy"')
    cur.execute(f"ALTER TABLE {NEW} RENAME TO chunks")
    for i in range(partitions):
        cur.execute(f"ALTER TABLE {NEW}_p{i:03d} RENAME TO chunks_p{i:03d}")
    cur.execute(f"ALTER INDEX ix_{NEW}_document RENAME TO ix_chunks_document")
    cur.execute(f"ALTER INDEX ix_{NEW}_embedding_hnsw RENAME TO {cs.SHARED_INDEX}")


def run(args: argparse.Namespace) -> int:
    import psycopg2

    url = args.database_url.replace("postgresql+asyncpg", "postgresql").split("?")[0]
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        kind = relkind(cur, "chunks")
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()
    version = row[0] if row else ""
    conn.commit()
    if kind is None:
        log("no chunks table, the API creates it partitioned on its next start")
        return 0
    if kind == "p":
        log("chunks is already partitioned")
        if args.drop_legacy:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS chunks_legacy")
            conn.commit()
            log("dropped chunks_legacy")
        return 0
    if args.storage == "halfvec" and cs.version_tuple(version) < (0, 7):
        log(f"halfvec needs pgvector 0.7, this database has {version}")
        return 2
    cast = "::halfvec(1536)" if args.storage == "halfvec" else ""

    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '10s'")
        ensure_columns(cur)
        if relkind(cur, NEW) is None:
            for stmt in cs.partitioned_ddl(NEW, args.partitions, args.storage):
                cur.execute(stmt)
            log(f"created {NEW} with {args.partitions} partitions")
        else:
            cur.execute(
                "SELECT count(*) FROM pg_inherits WHERE inhparent = to_regclass(%s)",
                (NEW,),
            )
            args.partitions = cur.fetchone()[0]
    conn.commit()

    started = time.monotonic()
    copy_rows(conn, cast, args.batch)
    with conn.cursor() as cur:
        cur.execute("SET maintenance_work_mem = %s", (args.maintenance_work_mem,))
        cur.execute(
            "SET max_parallel_maintenance_workers = %s", (args.parallel_workers,)
        )
        log("building the shared vector index, this is the slow part")
        cur.execute(cs.shared_hnsw_ddl(NEW, args.storage))
    conn.commit()
    log(f"copy and index took {time.monotonic() - started:.0f}s")

    if args.dry_run:
        log("dry run, the live table is untouched")
        return 0

    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '30s'")
        # catching up unlocked first keeps the locked pass short
        added, removed = catch_up(cur, cast)
    conn.commit()
    log(f"caught up {added} added, {removed} removed")
    locked = time.monotonic()
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '30s'")
        cur.execute("LOCK TABLE chunks IN SHARE ROW EXCLUSIVE MODE")
        added, removed = catch_up(cur, cast)
        swap(cur, args.partitions)
    conn.commit()
    log(
        f"swapped, writers waited {time.monotonic() - locked:.1f}s, "
        f"last pass {added} added, {removed} removed"
    )
    with conn.cursor() as cur:
        cur.execute("ANALYZE chunks")
        if args.drop_legacy:
            cur.execute("DROP TABLE chunks_legacy")
            log("dropped chunks_legacy")
        else:
            log("chunks_legacy kept, rerun with --drop-legacy once this looks right")
    conn.commit()
    conn.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""))
    parser.add_argument("--partitions", type=int, default=cs.partition_count())
    parser.add_argument("--storage", choices=("vector", "halfvec"), default="vector")
    parser.add_argument("--batch", type=int, default=20000)
    parser.add_argument("--maintenance-work-mem", default="1GB")
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--drop-legacy", action="store_true")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
