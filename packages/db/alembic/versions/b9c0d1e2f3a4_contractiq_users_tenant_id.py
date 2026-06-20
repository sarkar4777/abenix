"""Add tenant_id column to contractiq_users.

The /me endpoint and the recommendations engine both need a tenant_id. Older
rows are backfilled to their own user id so each existing account is its own
tenant; new rows pick up the same default at registration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "contractiq_users" not in insp.get_table_names():
        # Fresh DBs may run this before the ContractIQ tables are created by
        # i9d0e1f2g3h4. Skip cleanly — the column ships in the model so the
        # later create_all path will include it.
        return
    cols = {c["name"] for c in insp.get_columns("contractiq_users")}
    if "tenant_id" not in cols:
        op.add_column(
            "contractiq_users",
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
        )
    existing_indexes = {i["name"] for i in insp.get_indexes("contractiq_users")}
    if "ix_contractiq_users_tenant_id" not in existing_indexes:
        op.create_index(
            "ix_contractiq_users_tenant_id",
            "contractiq_users",
            ["tenant_id"],
        )
    # Backfill: each pre-existing user is its own tenant.
    op.execute(
        "UPDATE contractiq_users SET tenant_id = id::text "
        "WHERE tenant_id IS NULL OR tenant_id = ''"
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "contractiq_users" not in insp.get_table_names():
        return
    existing_indexes = {i["name"] for i in insp.get_indexes("contractiq_users")}
    if "ix_contractiq_users_tenant_id" in existing_indexes:
        op.drop_index("ix_contractiq_users_tenant_id", table_name="contractiq_users")
    cols = {c["name"] for c in insp.get_columns("contractiq_users")}
    if "tenant_id" in cols:
        op.drop_column("contractiq_users", "tenant_id")
