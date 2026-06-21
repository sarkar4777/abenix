"""Widen api_keys.max_monthly_cost to numeric(10, 4).

The column was numeric(10, 2) which silently rounded sub-cent inputs
to 0.00. The deps.py guard then read 0.00 as falsy and disabled the
quota entirely, so a customer asking for a 0.005 USD cap got an
unbounded key. The companion code fix changes the guard to compare
against `is not None` so 0 means 0; this migration matches the
storage precision to `cost_used` (already numeric(10, 4)) so a 0.001
cap survives the column write.

Revision ID: g5c6d7e8f9a0
Revises: f4b5c6d7e8f9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g5c6d7e8f9a0"
down_revision = "f4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "api_keys" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("api_keys")}
    if "max_monthly_cost" not in cols:
        return
    op.alter_column(
        "api_keys",
        "max_monthly_cost",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Numeric(10, 4),
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "api_keys" not in insp.get_table_names():
        return
    cols = {c["name"]: c for c in insp.get_columns("api_keys")}
    if "max_monthly_cost" not in cols:
        return
    op.alter_column(
        "api_keys",
        "max_monthly_cost",
        existing_type=sa.Numeric(10, 4),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
    )
