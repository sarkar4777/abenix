"""Queue lease on executions so a redelivered run is not run twice at once.

Revision ID: 09519dee709f
Revises: 6f7e442a4250
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "09519dee709f"
down_revision = "6f7e442a4250"
branch_labels = None
depends_on = None


def _cols() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("executions")}


def upgrade() -> None:
    have = _cols()
    if "runner_id" not in have:
        op.add_column(
            "executions", sa.Column("runner_id", sa.String(128), nullable=True)
        )
    if "lease_expires_at" not in have:
        op.add_column(
            "executions",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "delivery_attempts" not in have:
        op.add_column(
            "executions",
            sa.Column(
                "delivery_attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    have = _cols()
    for name in ("delivery_attempts", "lease_expires_at", "runner_id"):
        if name in have:
            op.drop_column("executions", name)
