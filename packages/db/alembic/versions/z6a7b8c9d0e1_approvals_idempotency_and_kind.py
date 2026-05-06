"""Add client_token + gate_kind columns to approvals.

Both back HITL ergonomics improvements that the SDKs now expose:
  • client_token — collapses retried POST /api/approvals + POST signoff
    calls onto a single decision row, so a flaky network can't double-
    create or double-sign.
  • gate_kind — free-form discriminator (e.g. "device.remote_reset",
    "claim.adjudicate") that lets reviewer UIs and SDK consumers
    dispatch handlers per gate type without parsing the payload.

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "z6a7b8c9d0e1"
down_revision = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _has_column("approvals", "client_token"):
        op.add_column(
            "approvals",
            sa.Column("client_token", sa.String(length=120), nullable=True),
        )
        op.create_index(
            "uq_approvals_tenant_client_token",
            "approvals",
            ["tenant_id", "client_token"],
            unique=True,
            postgresql_where=text("client_token IS NOT NULL"),
        )

    if not _has_column("approvals", "gate_kind"):
        op.add_column(
            "approvals",
            sa.Column("gate_kind", sa.String(length=120), nullable=True),
        )
        op.create_index(
            "ix_approvals_tenant_kind",
            "approvals",
            ["tenant_id", "gate_kind"],
        )


def downgrade() -> None:
    if _has_column("approvals", "gate_kind"):
        op.drop_index("ix_approvals_tenant_kind", table_name="approvals")
        op.drop_column("approvals", "gate_kind")
    if _has_column("approvals", "client_token"):
        op.drop_index("uq_approvals_tenant_client_token", table_name="approvals")
        op.drop_column("approvals", "client_token")
