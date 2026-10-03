"""Record how many rows or vectors each GDPR purge step removed.

Revision ID: 6f7e442a4250
Revises: 9465d37a97f1
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "6f7e442a4250"
down_revision = "9465d37a97f1"
branch_labels = None
depends_on = None


def _cols() -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table("gdpr_purge_log"):
        return set()
    return {c["name"] for c in insp.get_columns("gdpr_purge_log")}


def upgrade() -> None:
    have = _cols()
    if have and "affected_count" not in have:
        op.add_column(
            "gdpr_purge_log", sa.Column("affected_count", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    if "affected_count" in _cols():
        op.drop_column("gdpr_purge_log", "affected_count")
