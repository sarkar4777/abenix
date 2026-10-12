"""Telemetry 2.5.8 T9: asset registry, signal rules and their firings.

Revision ID: tel258a03
Revises: tel258a04
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tel258a03"
down_revision = "tel258a04"
branch_labels = None
depends_on = None


def _uuid(name: str, *args, **kw) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), *args, **kw)


def _jsonb(name: str, default: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.JSONB(),
        nullable=nullable,
        server_default=None if nullable else sa.text(f"'{default}'::jsonb"),
    )


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else sa.func.now(),
    )


def upgrade() -> None:
    have = set(sa.inspect(op.get_bind()).get_table_names())
    if "telemetry_assets" not in have:
        op.create_table(
            "telemetry_assets",
            _uuid("id", primary_key=True),
            _uuid("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("grp", sa.String(255), nullable=False),
            sa.Column("node", sa.String(255), nullable=False),
            sa.Column("device", sa.String(255), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(120), nullable=True),
            sa.Column("asset_type", sa.String(16), nullable=True),
            _jsonb("tags", "[]"),
            _uuid(
                "team_id",
                sa.ForeignKey("permission_sets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _jsonb("location", "", nullable=True),
            _jsonb("fields", "{}"),
            _uuid(
                "created_by",
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "grp", "node", "device", name="uq_telemetry_asset_key"
            ),
        )
        op.create_index(
            "ix_telemetry_assets_tenant_id", "telemetry_assets", ["tenant_id"]
        )
        op.create_index("ix_telemetry_assets_team_id", "telemetry_assets", ["team_id"])
        op.create_index(
            "ix_telemetry_assets_type", "telemetry_assets", ["tenant_id", "asset_type"]
        )
    if "telemetry_rules" not in have:
        op.create_table(
            "telemetry_rules",
            _uuid("id", primary_key=True),
            _uuid("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "severity", sa.String(16), nullable=False, server_default="warning"
            ),
            _jsonb("scope", "{}"),
            _jsonb("condition", "{}"),
            sa.Column("cooldown_s", sa.Integer(), nullable=False, server_default="60"),
            _jsonb("actions", "[]"),
            _uuid(
                "team_id",
                sa.ForeignKey("permission_sets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _uuid(
                "created_by",
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _uuid(
                "updated_by",
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            _ts("last_fired_at", nullable=True),
            sa.Column("fire_count", sa.Integer(), nullable=False, server_default="0"),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_telemetry_rule_name"),
        )
        op.create_index(
            "ix_telemetry_rules_tenant_id", "telemetry_rules", ["tenant_id"]
        )
        op.create_index("ix_telemetry_rules_team_id", "telemetry_rules", ["team_id"])
        op.create_index("ix_telemetry_rules_enabled", "telemetry_rules", ["enabled"])
    if "telemetry_rule_firings" not in have:
        op.create_table(
            "telemetry_rule_firings",
            _uuid("id", primary_key=True),
            _uuid("tenant_id", sa.ForeignKey("tenants.id"), nullable=False),
            _uuid(
                "rule_id",
                sa.ForeignKey("telemetry_rules.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("rule_name", sa.String(160), nullable=False),
            _ts("fired_at"),
            _ts("cleared_at", nullable=True),
            sa.Column("grp", sa.String(255), nullable=False),
            sa.Column("node", sa.String(255), nullable=False),
            sa.Column("device", sa.String(255), nullable=False, server_default=""),
            sa.Column("signal", sa.String(255), nullable=True),
            _jsonb("value", "", nullable=True),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="firing"),
            _jsonb("actions", "[]"),
            _jsonb("context", "{}"),
            sa.Column("connection_id", sa.String(64), nullable=True),
        )
        op.create_index(
            "ix_telemetry_rule_firings_tenant_id",
            "telemetry_rule_firings",
            ["tenant_id"],
        )
        op.create_index(
            "ix_telemetry_rule_firings_rule",
            "telemetry_rule_firings",
            ["tenant_id", "rule_id", "fired_at"],
        )
        op.create_index(
            "ix_telemetry_rule_firings_open",
            "telemetry_rule_firings",
            ["rule_id", "grp", "node", "device", "cleared_at"],
        )


def downgrade() -> None:
    op.drop_table("telemetry_rule_firings")
    op.drop_table("telemetry_rules")
    op.drop_table("telemetry_assets")
