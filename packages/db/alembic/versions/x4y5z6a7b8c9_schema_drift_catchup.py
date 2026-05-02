"""Schema-drift catchup: add columns that exist in the ORM but never had a migration.

Several columns were added directly to the SQLAlchemy models (executions
.node_results, executions.execution_trace, executions.failure_code,
agent_shares.shared_with_user_id, agent_shares.shared_with_email) without
ever being captured in an alembic migration. The result: every fresh
`alembic upgrade head` produces a database missing those columns, every
API call that touches them returns 500, and the only fix was a manual
DROP DATABASE — which is fine locally and catastrophic in prod.

This migration is the catchup. Every column it adds is guarded by an
information_schema lookup so it's idempotent: safe to re-run on a
database that already has them. It runs as part of `alembic upgrade
head` everywhere (k8s deploy job + dev-local Step 4/7), so any
environment that's drifted gets repaired non-destructively without
losing data.

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # ── executions.node_results, execution_trace, failure_code ──
    if not _has_column("executions", "node_results"):
        op.add_column(
            "executions",
            sa.Column("node_results", postgresql.JSONB(), nullable=True),
        )
    if not _has_column("executions", "execution_trace"):
        op.add_column(
            "executions",
            sa.Column("execution_trace", postgresql.JSONB(), nullable=True),
        )
    if not _has_column("executions", "failure_code"):
        op.add_column(
            "executions",
            sa.Column("failure_code", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_executions_failure_code",
            "executions",
            ["failure_code"],
        )

    # ── executions.parent_execution_id + retry_count + moderation_blocked ──
    if not _has_column("executions", "parent_execution_id"):
        op.add_column(
            "executions",
            sa.Column(
                "parent_execution_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("executions.id"),
                nullable=True,
            ),
        )
    if not _has_column("executions", "retry_count"):
        op.add_column(
            "executions",
            sa.Column("retry_count", sa.Integer(), nullable=True, server_default="0"),
        )
    if not _has_column("executions", "moderation_blocked"):
        op.add_column(
            "executions",
            sa.Column(
                "moderation_blocked",
                sa.Boolean(),
                nullable=True,
                server_default=sa.false(),
            ),
        )

    # ── agent_shares.shared_with_user_id + shared_with_email ──
    if not _has_column("agent_shares", "shared_with_user_id"):
        op.add_column(
            "agent_shares",
            sa.Column(
                "shared_with_user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
        )
        op.create_index(
            "ix_agent_shares_shared_with_user_id",
            "agent_shares",
            ["shared_with_user_id"],
        )
    if not _has_column("agent_shares", "shared_with_email"):
        op.add_column(
            "agent_shares",
            sa.Column("shared_with_email", sa.String(length=255), nullable=True),
        )


def downgrade() -> None:
    # Best-effort drops; idempotent if the columns already gone.
    for tbl, col, idx in (
        ("agent_shares", "shared_with_email", None),
        ("agent_shares", "shared_with_user_id", "ix_agent_shares_shared_with_user_id"),
        ("executions", "moderation_blocked", None),
        ("executions", "retry_count", None),
        ("executions", "parent_execution_id", None),
        ("executions", "failure_code", "ix_executions_failure_code"),
        ("executions", "execution_trace", None),
        ("executions", "node_results", None),
    ):
        if _has_column(tbl, col):
            if idx:
                try:
                    op.drop_index(idx, table_name=tbl)
                except Exception:
                    pass
            op.drop_column(tbl, col)
