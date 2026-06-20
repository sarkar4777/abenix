"""Add tenant_id column to contractiq_counterparties.

BLOCKER A1 — counterparties had no tenant column so every CIQ tenant saw every
other tenant's counterparty list, financials, permits, and compliance alerts.

Migration steps:
  1. ADD COLUMN tenant_id VARCHAR(64) NULL — mirrors contractiq_users.tenant_id
     so router-side filters compare text-to-text without casts.
  2. Backfill nulls to a deterministic tenant chosen via a fallback ladder:
        a) the Abenix `demo` tenant when it exists
        b) the most-common tenant_id across existing contractiq_users
        c) the most-common tenant_id across abenix users
        d) the first tenant in the tenants table
        e) a freshly-minted 'demo' tenant we insert here
     This makes the migration safe on any cluster topology — fresh seed,
     single-tenant customer, multi-tenant customer, or empty DB.
  3. ALTER COLUMN tenant_id SET NOT NULL.
  4. CREATE INDEX ix_contractiq_counterparties_tenant_id ON
     contractiq_counterparties (tenant_id) — every router query goes through
     this index.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def _resolve_tenant_id(bind) -> str:
    """Pick a non-NULL tenant_id for the backfill on ANY cluster topology.

    Order of preference (every step is a single SELECT — no side effects until
    the last step where we may INSERT a fresh demo tenant):
      1. tenants.name = 'demo'  (default seed name)
      2. mode(contractiq_users.tenant_id)  (most-common CIQ tenant)
      3. mode(users.tenant_id)             (most-common Abenix tenant)
      4. tenants.id ORDER BY created_at LIMIT 1  (oldest tenant — usually the seed)
      5. INSERT a fresh 'demo' tenant and return its id  (truly empty cluster)
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
            # Some tables (contractiq_users / users) may not exist yet on a
            # truly fresh DB. Fall through to the next strategy.
            continue

    # Truly empty cluster — mint a fresh 'demo' tenant so seed users +
    # counterparties have something coherent to point at.
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
    if "contractiq_counterparties" not in insp.get_table_names():
        # Fresh DBs may run this migration before the ContractIQ tables are
        # created. The column is in the model so create_all picks it up later.
        return

    cols = {c["name"] for c in insp.get_columns("contractiq_counterparties")}
    if "tenant_id" not in cols:
        op.add_column(
            "contractiq_counterparties",
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
        )

    # Backfill via the resolver ladder so the NOT NULL flip below works on
    # any cluster topology. Counterparties land on whichever tenant the
    # resolver picked — operators can re-home later by updating tenant_id.
    tenant_id = _resolve_tenant_id(bind)
    op.execute(
        sa.text(
            """
            UPDATE contractiq_counterparties
            SET tenant_id = :tid
            WHERE tenant_id IS NULL OR tenant_id = ''
            """
        ).bindparams(tid=tenant_id)
    )

    op.alter_column(
        "contractiq_counterparties",
        "tenant_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )

    existing_indexes = {
        i["name"] for i in insp.get_indexes("contractiq_counterparties")
    }
    if "ix_contractiq_counterparties_tenant_id" not in existing_indexes:
        op.create_index(
            "ix_contractiq_counterparties_tenant_id",
            "contractiq_counterparties",
            ["tenant_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "contractiq_counterparties" not in insp.get_table_names():
        return
    existing_indexes = {
        i["name"] for i in insp.get_indexes("contractiq_counterparties")
    }
    if "ix_contractiq_counterparties_tenant_id" in existing_indexes:
        op.drop_index(
            "ix_contractiq_counterparties_tenant_id",
            table_name="contractiq_counterparties",
        )
    cols = {c["name"] for c in insp.get_columns("contractiq_counterparties")}
    if "tenant_id" in cols:
        op.drop_column("contractiq_counterparties", "tenant_id")
