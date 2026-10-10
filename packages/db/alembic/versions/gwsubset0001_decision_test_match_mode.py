"""Golden tests can match the expected result as a subset.

Revision ID: gwsubset0001
Revises: acctsec00001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "gwsubset0001"
down_revision = "acctsec00001"
branch_labels = None
depends_on = None


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # the API's startup create_all may have added it already
    if not _has_column("decision_tests", "match_mode"):
        op.add_column(
            "decision_tests",
            sa.Column(
                "match_mode",
                sa.String(16),
                nullable=False,
                server_default="exact",
            ),
        )


def downgrade() -> None:
    if _has_column("decision_tests", "match_mode"):
        op.drop_column("decision_tests", "match_mode")
