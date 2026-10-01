"""DLQ: one row per execution + link to the replay execution.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None

_TABLE = "dead_letter_executions"


def _has_column(table: str, column: str) -> bool:
    row = (
        op.get_bind()
        .execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name=:t AND column_name=:c"
            ),
            {"t": table, "c": column},
        )
        .first()
    )
    return row is not None


def _index_is_unique(name: str) -> bool:
    row = (
        op.get_bind()
        .execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname=:n"), {"n": name}
        )
        .first()
    )
    return row is not None and "UNIQUE" in (row[0] or "")


def upgrade() -> None:
    if not _has_column(_TABLE, "replay_execution_id"):
        op.add_column(
            _TABLE,
            sa.Column(
                "replay_execution_id",
                UUID(as_uuid=True),
                sa.ForeignKey("executions.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not _index_is_unique("ix_dead_letter_executions_execution_id"):
        # Collapse any historic duplicates before the unique index lands.
        op.execute(
            text(
                f"DELETE FROM {_TABLE} a USING {_TABLE} b "
                "WHERE a.execution_id = b.execution_id AND a.created_at > b.created_at"
            )
        )
        op.execute(text("DROP INDEX IF EXISTS ix_dead_letter_executions_execution_id"))
        op.create_index(
            "ix_dead_letter_executions_execution_id",
            _TABLE,
            ["execution_id"],
            unique=True,
        )


def downgrade() -> None:
    if _index_is_unique("ix_dead_letter_executions_execution_id"):
        op.drop_index("ix_dead_letter_executions_execution_id", table_name=_TABLE)
        op.create_index(
            "ix_dead_letter_executions_execution_id", _TABLE, ["execution_id"]
        )
    if _has_column(_TABLE, "replay_execution_id"):
        op.drop_column(_TABLE, "replay_execution_id")
