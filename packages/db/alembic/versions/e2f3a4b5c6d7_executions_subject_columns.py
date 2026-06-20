"""Add subject_id + subject_type columns to executions.

actAs delegation gap — when the Python SDK was called with
`act_as=ActingSubject(...)`, the abenix-side execution row still recorded only
the API-key holder (the standalone-app service account) as `user_id`. The
end-user who actually triggered the call had no row presence at all, so the
standalone-side `_execution_belongs_to()` could never match ownership for
the legitimate caller — `/api/contractiq/executions/{id}` returned 404 to
the user who just created the execution.

This migration:
  1. ADD COLUMN subject_id VARCHAR(128) NULL — opaque string (often a UUID
     stringified by the standalone, but kept loose so non-UUID subject ids
     from third-party IdPs work).
  2. ADD COLUMN subject_type VARCHAR(64) NULL — e.g. 'contractiq',
     'wingman', 'tourism'. Standalone-side ownership matchers gate on the
     pair so a CIQ subject cannot pose as a Wingman one.
  3. CREATE INDEX ix_executions_subject_id ON executions (subject_id) —
     /api/contractiq/executions/{id} list filters go through it.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "executions" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("executions")}
    if "subject_id" not in cols:
        op.add_column(
            "executions",
            sa.Column("subject_id", sa.String(length=128), nullable=True),
        )
    if "subject_type" not in cols:
        op.add_column(
            "executions",
            sa.Column("subject_type", sa.String(length=64), nullable=True),
        )
    existing_indexes = {i["name"] for i in insp.get_indexes("executions")}
    if "ix_executions_subject_id" not in existing_indexes:
        op.create_index(
            "ix_executions_subject_id",
            "executions",
            ["subject_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "executions" not in insp.get_table_names():
        return
    existing_indexes = {i["name"] for i in insp.get_indexes("executions")}
    if "ix_executions_subject_id" in existing_indexes:
        op.drop_index("ix_executions_subject_id", table_name="executions")
    cols = {c["name"] for c in insp.get_columns("executions")}
    if "subject_type" in cols:
        op.drop_column("executions", "subject_type")
    if "subject_id" in cols:
        op.drop_column("executions", "subject_id")
