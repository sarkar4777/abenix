"""Resilient schema bootstrap for ContractIQ.

ContractIQ owns its own DeclarativeBase, so its tables come from
``create_all`` at startup rather than from the platform's alembic chain
(``packages/db`` bootstrap stamps alembic at heads on a fresh install, which
means the ``add_contractiq`` migration never actually runs). That made the
startup path the only thing standing between a fresh database and a working
login, and it had two failure modes that both ended with zero tables:

1. ``create_all`` ran inside a single transaction together with the follow-up
   ALTERs. An index left behind by a half-finished earlier attempt raised
   DuplicateTable, which rolled back every table created in that same
   transaction. The orphan index survived, so every subsequent restart failed
   the same way — a permanently broken app reporting only a logged exception.
2. The follow-up ALTERs looped with a per-statement ``try/except``, which does
   nothing useful in Postgres: the first failing statement aborts the whole
   transaction, so every later statement fails with "current transaction is
   aborted" regardless of the except.

This module fixes both: orphan indexes are reconciled first, table creation
gets its own transaction with a bounded retry, and each ALTER runs in its own
transaction so one skip cannot poison the rest.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("contractiq")

# Columns that widened, enum values that were added, and lookup indexes. Each
# runs in its own transaction and is expected to be a no-op on an up-to-date
# database.
WIDENING_DDL: tuple[str, ...] = (
    "ALTER TABLE contractiq_credit_risks ALTER COLUMN risk_level TYPE VARCHAR(40)",
    "ALTER TABLE contractiq_credit_risks ALTER COLUMN z_score_zone TYPE VARCHAR(40)",
    "ALTER TABLE contractiq_credit_risks ALTER COLUMN credit_rating TYPE VARCHAR(80)",
    "ALTER TABLE contractiq_credit_risks ALTER COLUMN sector TYPE VARCHAR(255)",
    "ALTER TABLE contractiq_credit_risks ALTER COLUMN ticker TYPE VARCHAR(40)",
    "ALTER TYPE contract_type ADD VALUE IF NOT EXISTS 'metals'",
    "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS asset_class VARCHAR(40)",
    "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS pricing_pattern VARCHAR(40)",
    "ALTER TABLE contractiq_contracts ADD COLUMN IF NOT EXISTS quantity JSONB",
    "ALTER TABLE contractiq_kyc_checks ALTER COLUMN outcome_of_check TYPE VARCHAR(40)",
    "CREATE INDEX IF NOT EXISTS ix_contractiq_kyc_name_country "
    "ON contractiq_kyc_checks (counterparty_name, country_iso2)",
    "CREATE INDEX IF NOT EXISTS ix_contractiq_kyc_next_review "
    "ON contractiq_kyc_checks (next_review_due)",
)

_ORPHAN_INDEX_SQL = """
SELECT i.relname
FROM pg_class i
JOIN pg_namespace n ON n.oid = i.relnamespace
JOIN pg_index x ON x.indexrelid = i.oid
LEFT JOIN pg_class t ON t.oid = x.indrelid
WHERE n.nspname = current_schema()
  AND i.relkind = 'i'
  AND i.relname LIKE 'ix_contractiq%'
  AND t.oid IS NULL
"""


async def _drop_orphan_indexes(engine: Any) -> int:
    """Drop ContractIQ indexes whose table no longer exists.

    A normal DROP TABLE takes its indexes with it, so these only appear after
    a rolled-back create_all left the database half-built. They are what makes
    the failure sticky.
    """
    dropped = 0
    async with engine.begin() as conn:
        rows = (await conn.execute(text(_ORPHAN_INDEX_SQL))).fetchall()
        names = [r[0] for r in rows]
    for name in names:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
            dropped += 1
            logger.warning("schema_boot: dropped orphan index %s", name)
        except Exception as e:
            logger.warning("schema_boot: could not drop orphan index %s: %s", name, e)
    return dropped


async def _create_all_with_retry(engine: Any, base: Any, attempts: int = 3) -> None:
    """create_all in its own transaction, retrying past a duplicate index.

    An index that already exists while its table does not is not something
    create_all's checkfirst can see, so drop whatever it trips over and try
    again rather than losing every table to the rollback.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(base.metadata.create_all)
            return
        except Exception as e:  # noqa: BLE001 — need the message to decide
            last = e
            msg = str(e)
            if "already exists" not in msg:
                raise
            name = _relation_name_from_error(msg)
            if not name:
                raise
            logger.warning(
                "schema_boot: create_all hit existing relation %s (attempt %d) — dropping it",
                name,
                attempt,
            )
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
            except Exception as drop_err:
                logger.warning("schema_boot: drop of %s failed: %s", name, drop_err)
                raise e from drop_err
    if last is not None:
        raise last


def _relation_name_from_error(msg: str) -> str | None:
    """Pull the relation name out of a Postgres DuplicateTable message."""
    marker = 'relation "'
    i = msg.find(marker)
    if i < 0:
        return None
    j = msg.find('"', i + len(marker))
    return msg[i + len(marker) : j] if j > 0 else None


async def _apply_widening_ddl(engine: Any) -> int:
    """Run each widening statement in its own transaction.

    Separate transactions are the whole point: a statement that legitimately
    does not apply must not abort the ones after it.
    """
    applied = 0
    for ddl in WIDENING_DDL:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
            applied += 1
        except Exception as e:
            logger.debug("schema_boot: skip %r: %s", ddl, e)
    return applied


async def ensure_schema(engine: Any, base: Any) -> bool:
    """Bring the ContractIQ schema up. Returns True when login can work.

    The return value is deliberately checked by the caller: a silently logged
    exception is how this went unnoticed, so the caller logs an explicit error
    when the users table still is not there.
    """
    await _drop_orphan_indexes(engine)
    await _create_all_with_retry(engine, base)
    applied = await _apply_widening_ddl(engine)
    logger.info("schema_boot: tables ensured, %d widening statements applied", applied)

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'contractiq_users'"
                )
            )
        ).first()
    return row is not None
