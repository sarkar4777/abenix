"""Add tenant_id to 12 ContractIQ insights tables.

BLOCKER must_fix #2 — the insights tables (briefings, renewal packets, FM
notices, reconciliations, contract families, clause anomalies, version diffs,
stress tests, hedge recommendations, credit risks, market alerts, risk
analyses) had no tenant column and routers filter only on user_id. That
defeats the multi-tenant boundary: any user in tenant B who joins tenant A
later (or shares an id) sees tenant A's data, and any cross-user-but-same-
tenant UX (`my team's briefings`) is impossible.

Migration steps:
  1. For each of the 12 tables ADD COLUMN tenant_id varchar(64) NULL — mirrors
     contractiq_users.tenant_id so router-side filters compare text-to-text
     without casts. Idempotent via inspector guards.
  2. Backfill via the same resolver ladder as c0d1e2f3a4b5
     (demo tenant -> mode(contractiq_users) -> mode(users) -> oldest tenant ->
     mint fresh demo). For tables that carry a contract_id we prefer the
     parent contract's owning user's tenant — that keeps per-row provenance
     intact instead of slamming every row onto one tenant.
  3. ALTER COLUMN tenant_id SET NOT NULL.
  4. CREATE INDEX ix_<table>_tenant_id on (tenant_id).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


# (table_name, has_contract_id_link, has_user_id_link)
# contract_id-backfill is preferred where present because the parent contract
# already has a resolved owning user (and through them a tenant) — preserves
# per-row provenance.
TABLES: tuple[tuple[str, bool, bool], ...] = (
    ("contractiq_risk_analyses", True, False),
    ("contractiq_market_alerts", True, False),
    ("contractiq_briefings", False, True),
    ("contractiq_renewal_packets", True, True),
    ("contractiq_fm_notices", True, True),
    ("contractiq_reconciliations", True, True),
    ("contractiq_contract_families", False, True),
    ("contractiq_clause_anomalies", True, True),
    (
        "contractiq_version_diffs",
        False,
        True,
    ),  # has base_/new_contract_id, not contract_id
    ("contractiq_stress_tests", True, True),
    ("contractiq_hedge_recommendations", True, True),
    ("contractiq_credit_risks", False, True),
)


def _resolve_tenant_id(bind) -> str:
    """Pick a non-NULL tenant_id for the backfill on ANY cluster topology.

    Mirrors c0d1e2f3a4b5._resolve_tenant_id so insights and counterparties
    pick the same fallback tenant on a fresh cluster.
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
            continue

    new_id = bind.execute(
        sa.text(
            "INSERT INTO tenants (id, name, plan, created_at) "
            "VALUES (gen_random_uuid(), 'demo', 'free', now()) RETURNING id::text"
        )
    ).scalar()
    return str(new_id)


def _backfill_from_contract(bind, table: str) -> None:
    """Backfill child.tenant_id from parent contract's owning user.

    Resolves per-row: child -> contractiq_contracts.user_id ->
    contractiq_users.tenant_id. Falls back to str(user.id) when tenant_id is
    blank — matches `tenant_id_for(user)` in app/routers/auth.py.
    """
    op.execute(
        sa.text(
            f"""
            UPDATE {table} AS c
            SET tenant_id = COALESCE(u.tenant_id, u.id::text)
            FROM contractiq_contracts AS ct
            JOIN contractiq_users AS u ON u.id = ct.user_id
            WHERE c.contract_id = ct.id
              AND (c.tenant_id IS NULL OR c.tenant_id = '')
            """
        )
    )


def _backfill_from_user(bind, table: str) -> None:
    """Backfill child.tenant_id from the row's owning contractiq_user."""
    op.execute(
        sa.text(
            f"""
            UPDATE {table} AS c
            SET tenant_id = COALESCE(u.tenant_id, u.id::text)
            FROM contractiq_users AS u
            WHERE c.user_id = u.id
              AND (c.tenant_id IS NULL OR c.tenant_id = '')
            """
        )
    )


def _backfill_from_version_diff_contract(bind) -> None:
    """ContractIQVersionDiff doesn't have contract_id — link via base_contract_id."""
    op.execute(
        sa.text(
            """
            UPDATE contractiq_version_diffs AS c
            SET tenant_id = COALESCE(u.tenant_id, u.id::text)
            FROM contractiq_contracts AS ct
            JOIN contractiq_users AS u ON u.id = ct.user_id
            WHERE c.base_contract_id = ct.id
              AND (c.tenant_id IS NULL OR c.tenant_id = '')
            """
        )
    )


def _backfill_fallback(bind, table: str, tenant_id: str) -> None:
    """Sweep any rows still NULL onto the resolved fallback tenant."""
    op.execute(
        sa.text(
            f"""
            UPDATE {table}
            SET tenant_id = :tid
            WHERE tenant_id IS NULL OR tenant_id = ''
            """
        ).bindparams(tid=tenant_id)
    )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    tenant_id = _resolve_tenant_id(bind)

    for table, has_contract_id, has_user_id in TABLES:
        if table not in existing_tables:
            # Fresh DBs may run this migration before the table is created;
            # the column lives in the model so create_all paths get it.
            continue

        cols = {c["name"] for c in insp.get_columns(table)}
        if "tenant_id" not in cols:
            op.add_column(
                table,
                sa.Column("tenant_id", sa.String(length=64), nullable=True),
            )

        # Prefer parent-contract backfill where the child has contract_id —
        # preserves per-row provenance instead of collapsing onto one tenant.
        if (
            has_contract_id
            and "contractiq_contracts" in existing_tables
            and "contractiq_users" in existing_tables
        ):
            _backfill_from_contract(bind, table)
        elif (
            table == "contractiq_version_diffs"
            and "contractiq_contracts" in existing_tables
            and "contractiq_users" in existing_tables
        ):
            _backfill_from_version_diff_contract(bind)

        # For tables without contract_id (or rows whose parent FK was already
        # nulled by SET NULL cascades) fall through to user_id resolution.
        if has_user_id and "contractiq_users" in existing_tables:
            _backfill_from_user(bind, table)

        # Anything still NULL lands on the resolver-ladder fallback.
        _backfill_fallback(bind, table, tenant_id)

        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )

        existing_indexes = {i["name"] for i in insp.get_indexes(table)}
        idx_name = f"ix_{table}_tenant_id"
        if idx_name not in existing_indexes:
            op.create_index(idx_name, table, ["tenant_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for table, _has_contract_id, _has_user_id in TABLES:
        if table not in existing_tables:
            continue
        existing_indexes = {i["name"] for i in insp.get_indexes(table)}
        idx_name = f"ix_{table}_tenant_id"
        if idx_name in existing_indexes:
            op.drop_index(idx_name, table_name=table)
        cols = {c["name"] for c in insp.get_columns(table)}
        if "tenant_id" in cols:
            op.drop_column(table, "tenant_id")
