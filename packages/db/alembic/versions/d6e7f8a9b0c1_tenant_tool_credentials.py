"""Per-tenant tool credentials.

One row per (tenant, key). A row here wins over the platform row in
platform_settings for that tenant only.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None

TABLE = "tenant_tool_credentials"


def _has_table(name: str) -> bool:
    row = (
        op.get_bind()
        .execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": name},
        )
        .first()
    )
    return row is not None


def upgrade() -> None:
    if _has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("key", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    if _has_table(TABLE):
        op.drop_table(TABLE)
