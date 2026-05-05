"""Add dead_letter_executions table.

The stale sweeper (failure_code=STALE_SWEEP) and any tool that ends with
an unrecoverable failure can drop a row here. The /admin/dlq page lists
unresolved entries; the operator clicks "replay" to re-enqueue.

Revision ID: 1100_d_dead_letter
Revises: 1100_c_idempotency
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "1100_d_dead_letter"
down_revision = "1100_c_idempotency"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :n AND table_schema = current_schema()"
        ),
        {"n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if _table_exists("dead_letter_executions"):
        return

    op.create_table(
        "dead_letter_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "failure_code", sa.String(80), server_default="UNKNOWN", nullable=False
        ),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("original_input", JSONB, nullable=True),
        sa.Column("replay_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_replay_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved", sa.Boolean, server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_dead_letter_failure_code",
        "dead_letter_executions",
        ["failure_code"],
    )
    op.create_index(
        "ix_dead_letter_tenant_resolved",
        "dead_letter_executions",
        ["tenant_id", "resolved"],
    )


def downgrade() -> None:
    if _table_exists("dead_letter_executions"):
        op.drop_index(
            "ix_dead_letter_tenant_resolved", table_name="dead_letter_executions"
        )
        op.drop_index(
            "ix_dead_letter_failure_code", table_name="dead_letter_executions"
        )
        op.drop_table("dead_letter_executions")
