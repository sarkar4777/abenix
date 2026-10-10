"""Decisions 2.5.7: a version keeps the tier it was proposed under, approvals can be withdrawn.

Revision ID: dec257a01
Revises: gwsubset0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "dec257a01"
down_revision = "gwsubset0001"
branch_labels = None
depends_on = None


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    op.execute("ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'withdrawn'")
    if not _has_column("decision_versions", "risk_tier_at_proposal"):
        op.add_column(
            "decision_versions",
            sa.Column("risk_tier_at_proposal", sa.String(16), nullable=True),
        )


def downgrade() -> None:
    if _has_column("decision_versions", "risk_tier_at_proposal"):
        op.drop_column("decision_versions", "risk_tier_at_proposal")
