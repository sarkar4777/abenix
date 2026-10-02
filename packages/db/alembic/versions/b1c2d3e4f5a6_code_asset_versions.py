"""Code asset versions: a version number and the archives it replaced.

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "code_assets",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "code_assets",
        sa.Column("version_history", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("code_assets", "version_history")
    op.drop_column("code_assets", "version")
