"""Flag agent MCP tools the server no longer offers instead of deleting them.

Revision ID: f8a9b0c1d2e3
Revises: c5d6e7f8a9b0
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "f8a9b0c1d2e3"
down_revision = "c5d6e7f8a9b0"
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
    if not _has_column("agent_mcp_tools", "is_orphaned"):
        op.add_column(
            "agent_mcp_tools",
            sa.Column(
                "is_orphaned",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column("agent_mcp_tools", "orphaned_at"):
        op.add_column(
            "agent_mcp_tools",
            sa.Column("orphaned_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_column("agent_mcp_tools", "orphaned_at"):
        op.drop_column("agent_mcp_tools", "orphaned_at")
    if _has_column("agent_mcp_tools", "is_orphaned"):
        op.drop_column("agent_mcp_tools", "is_orphaned")
