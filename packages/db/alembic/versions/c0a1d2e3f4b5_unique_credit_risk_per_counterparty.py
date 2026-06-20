"""Unique partial index on contractiq_credit_risks (user_id, counterparty_name).

Concurrent /credit-risk/assess calls were creating 3+ duplicate rows for the
same counterparty with inconsistent enrichment. The router now serializes on a
pg_advisory_xact_lock keyed by (user, counterparty); this index is the belt+
braces guarantee if a future caller bypasses the lock. Failed rows are excluded
from the unique constraint so a retry after a transient agent error doesn't
collide with the failure record.

Revision ID: c0a1d2e3f4b5
Revises: c0d1e2f3a4b5
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "c0a1d2e3f4b5"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT 1 FROM information_schema.tables " "WHERE table_name = :t"),
        {"t": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("contractiq_credit_risks"):
        # Fresh DBs may run this before the ContractIQ tables exist. The
        # constraint ships in the model layer too, so create_all picks it
        # up; nothing to do here.
        return

    # Collapse pre-existing duplicates first — the unique index would
    # otherwise fail to create. Keep the most recent non-failed row per
    # (user_id, counterparty_name); demote earlier copies to failed so
    # they're excluded by the partial predicate.
    op.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY user_id, counterparty_name
                           ORDER BY assessed_at DESC NULLS LAST,
                                    created_at DESC NULLS LAST
                       ) AS rn
                FROM contractiq_credit_risks
                WHERE status <> 'failed'
            )
            UPDATE contractiq_credit_risks r
               SET status = 'failed',
                   error_message = COALESCE(error_message,
                                            'superseded by newer assessment')
              FROM ranked
             WHERE r.id = ranked.id
               AND ranked.rn > 1
            """
        )
    )

    op.create_index(
        "ix_ciq_credit_risk_user_cp",
        "contractiq_credit_risks",
        ["user_id", "counterparty_name"],
        unique=True,
        postgresql_where=text("status != 'failed'"),
    )


def downgrade() -> None:
    if not _table_exists("contractiq_credit_risks"):
        return
    op.drop_index(
        "ix_ciq_credit_risk_user_cp",
        table_name="contractiq_credit_risks",
    )
