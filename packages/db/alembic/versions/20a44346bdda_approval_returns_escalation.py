"""Approvals: returned for correction, escalation timestamp.

Revision ID: 20a44346bdda
Revises: fe18a43f0be1
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20a44346bdda"
down_revision = "fe18a43f0be1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'returned'")
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("approvals")}
    if "escalated_at" not in cols:
        op.add_column(
            "approvals",
            sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("approvals", "escalated_at")
