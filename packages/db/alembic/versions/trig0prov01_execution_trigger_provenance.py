"""Record which trigger started each run.

Revision ID: trig0prov01
Revises: auton0my0001
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "trig0prov01"
down_revision = "auton0my0001"
branch_labels = None
depends_on = None

_FK = "fk_executions_trigger_id_agent_triggers"


# The API's startup create_all can add these first, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in _insp().get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {i["name"] for i in _insp().get_indexes(table)}


def _trigger_fks() -> list[str]:
    return [
        fk["name"]
        for fk in _insp().get_foreign_keys("executions")
        if fk.get("referred_table") == "agent_triggers"
        and fk.get("constrained_columns") == ["trigger_id"]
    ]


def upgrade() -> None:
    if not _has_column("executions", "trigger_id"):
        op.add_column(
            "executions",
            sa.Column("trigger_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    if not _trigger_fks():
        op.create_foreign_key(
            _FK,
            "executions",
            "agent_triggers",
            ["trigger_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _has_column("executions", "trigger_kind"):
        op.add_column(
            "executions", sa.Column("trigger_kind", sa.String(32), nullable=True)
        )
    if not _has_column("executions", "trigger_name"):
        op.add_column(
            "executions", sa.Column("trigger_name", sa.String(255), nullable=True)
        )
    if not _has_index("executions", "ix_executions_trigger_id"):
        op.create_index("ix_executions_trigger_id", "executions", ["trigger_id"])
    if not _has_index("executions", "ix_executions_trigger_kind"):
        op.create_index("ix_executions_trigger_kind", "executions", ["trigger_kind"])


def downgrade() -> None:
    for name in ("ix_executions_trigger_kind", "ix_executions_trigger_id"):
        if _has_index("executions", name):
            op.drop_index(name, table_name="executions")
    for name in _trigger_fks():
        if name:
            op.drop_constraint(name, "executions", type_="foreignkey")
    for col in ("trigger_name", "trigger_kind", "trigger_id"):
        if _has_column("executions", col):
            op.drop_column("executions", col)
