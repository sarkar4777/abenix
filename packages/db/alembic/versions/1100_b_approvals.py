"""Add approvals table.

Backs the approval_gate primitive. An agent that needs human sign-off
calls approval_gate(...) which inserts a row here, then polls/awaits
status flip. The /api/approvals endpoints + UI page operate on this
single source of truth.

Revision ID: 1100_b_approvals
Revises: 1100_a_connectors
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "1100_b_approvals"
down_revision = "1100_a_connectors"
branch_labels = None
depends_on = None

_STATUSES = ("pending", "approved", "denied", "expired")


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


def _enum_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _enum_exists("approval_status"):
        op.execute(
            "CREATE TYPE approval_status AS ENUM "
            "(" + ", ".join(f"'{s}'" for s in _STATUSES) + ")"
        )

    if _table_exists("approvals"):
        return

    op.create_table(
        "approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), server_default="", nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column(
            "required_signoffs",
            sa.Integer,
            nullable=False,
            server_default="1",
        ),
        sa.Column("signoffs", JSONB, nullable=True, server_default="[]"),
        sa.Column(
            "status",
            sa.Enum(
                *_STATUSES,
                name="approval_status",
                native_enum=True,
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "requested_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_index("ix_approvals_agent", "approvals", ["agent_id"])
    op.create_index("ix_approvals_execution", "approvals", ["agent_execution_id"])


def downgrade() -> None:
    if _table_exists("approvals"):
        op.drop_index("ix_approvals_execution", table_name="approvals")
        op.drop_index("ix_approvals_agent", table_name="approvals")
        op.drop_index("ix_approvals_status", table_name="approvals")
        op.drop_table("approvals")
    op.execute("DROP TYPE IF EXISTS approval_status")
