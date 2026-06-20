"""Add tenant_id column to contractiq_contracts.

MUST-FIX #1 — CIQ contracts router had an admin-role tenant bypass: every
`SELECT FROM contractiq_contracts` only filtered by `user_id == user.id` for
non-admins, so an admin in tenant B could read tenant A's contracts, clauses,
extractions, deal-clusters, timelines, taxonomy. Router-side fix needs a
canonical tenant_id column on contractiq_contracts to filter on.

Mirrors `c0d1e2f3a4b5_contractiq_counterparties_tenant_id` for
contractiq_counterparties — same resolver ladder, same NOT NULL flip, same
index name shape so dashboards + indexed queries stay consistent.

Migration steps:
  1. ADD COLUMN tenant_id VARCHAR(64) NULL.
  2. Backfill nulls in two passes:
       a) JOIN contractiq_users so each contract inherits its owner's
          tenant_id — the natural answer when the owning user has one.
       b) Anything still NULL (orphan rows, owner without tenant_id) drops
          through the resolver ladder: demo tenant -> mode of CIQ users ->
          mode of Abenix users -> oldest tenant -> freshly minted demo.
  3. ALTER COLUMN tenant_id SET NOT NULL.
  4. CREATE INDEX ix_contractiq_contracts_tenant_id.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def _resolve_tenant_id(bind) -> str:
    """Pick a non-NULL tenant_id for the backfill on ANY cluster topology.

    Same ladder as c0d1e2f3a4b5 — kept in sync so contracts + counterparties
    land on the same fallback tenant when the cluster is otherwise empty.
    """
    for stmt in (
        "SELECT id::text FROM tenants WHERE name = 'demo' LIMIT 1",
        "SELECT tenant_id FROM contractiq_users WHERE tenant_id IS NOT NULL "
        "GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 1",
        "SELECT tenant_id::text FROM users WHERE tenant_id IS NOT NULL "
        "GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 1",
        "SELECT id::text FROM tenants ORDER BY created_at NULLS LAST LIMIT 1",
    ):
        try:
            result = bind.execute(sa.text(stmt)).scalar()
            if result:
                return str(result)
        except Exception:
            # Some tables may not exist on a truly fresh DB. Fall through.
            continue

    new_id = bind.execute(
        sa.text(
            "INSERT INTO tenants (id, name, plan, created_at) "
            "VALUES (gen_random_uuid(), 'demo', 'free', now()) RETURNING id::text"
        )
    ).scalar()
    return str(new_id)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "contractiq_contracts" not in insp.get_table_names():
        # Fresh DB — create_all picks up the column from the model.
        return

    cols = {c["name"] for c in insp.get_columns("contractiq_contracts")}
    if "tenant_id" not in cols:
        op.add_column(
            "contractiq_contracts",
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
        )

    # Step 2a — inherit each contract's tenant from its owning CIQ user.
    op.execute(
        sa.text(
            """
            UPDATE contractiq_contracts c
            SET tenant_id = u.tenant_id
            FROM contractiq_users u
            WHERE c.user_id = u.id
              AND (c.tenant_id IS NULL OR c.tenant_id = '')
              AND u.tenant_id IS NOT NULL
              AND u.tenant_id <> ''
            """
        )
    )

    # Step 2b — anything still null falls through the resolver ladder.
    remaining = (
        bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM contractiq_contracts "
                "WHERE tenant_id IS NULL OR tenant_id = ''"
            )
        ).scalar()
        or 0
    )
    if remaining:
        tenant_id = _resolve_tenant_id(bind)
        op.execute(
            sa.text(
                """
                UPDATE contractiq_contracts
                SET tenant_id = :tid
                WHERE tenant_id IS NULL OR tenant_id = ''
                """
            ).bindparams(tid=tenant_id)
        )

    op.alter_column(
        "contractiq_contracts",
        "tenant_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    existing_indexes = {i["name"] for i in insp.get_indexes("contractiq_contracts")}
    if "ix_contractiq_contracts_tenant_id" not in existing_indexes:
        op.create_index(
            "ix_contractiq_contracts_tenant_id",
            "contractiq_contracts",
            ["tenant_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "contractiq_contracts" not in insp.get_table_names():
        return
    existing_indexes = {i["name"] for i in insp.get_indexes("contractiq_contracts")}
    if "ix_contractiq_contracts_tenant_id" in existing_indexes:
        op.drop_index(
            "ix_contractiq_contracts_tenant_id",
            table_name="contractiq_contracts",
        )
    cols = {c["name"] for c in insp.get_columns("contractiq_contracts")}
    if "tenant_id" in cols:
        op.drop_column("contractiq_contracts", "tenant_id")
