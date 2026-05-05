"""Add execution_idempotency table.

Backs `Idempotency-Key` on /api/agents/{id}/execute. The composite
UNIQUE on (tenant_id, key) keeps tenants from colliding on the same
header value. A 24h TTL is enforced by a sweeper using the partial
index below.

Revision ID: 1100_c_idempotency
Revises: 1100_b_approvals
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "1100_c_idempotency"
down_revision = "1100_b_approvals"
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


def _index_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :n"),
        {"n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("execution_idempotency"):
        op.create_table(
            "execution_idempotency",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("key", sa.String(255), nullable=False, index=True),
            sa.Column(
                "agent_id",
                UUID(as_uuid=True),
                sa.ForeignKey("agents.id"),
                nullable=True,
            ),
            sa.Column(
                "execution_id",
                UUID(as_uuid=True),
                sa.ForeignKey("executions.id"),
                nullable=True,
            ),
            sa.Column(
                "status", sa.String(40), server_default="pending", nullable=False
            ),
            sa.Column("cached_response", JSONB, nullable=True),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
                index=True,
            ),
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
            sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
        )

    # Plain b-tree index on created_at for the 24h TTL sweeper. A partial
    # index with NOW() is rejected by Postgres (NOW() is STABLE, not IMMUTABLE)
    # so the sweeper does the cutoff filter at query time instead.
    if not _index_exists("ix_execution_idempotency_sweep"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_execution_idempotency_sweep "
            "ON execution_idempotency (created_at)"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_execution_idempotency_sweep")
    if _table_exists("execution_idempotency"):
        op.drop_table("execution_idempotency")
