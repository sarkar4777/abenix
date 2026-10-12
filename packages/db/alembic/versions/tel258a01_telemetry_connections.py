"""Telemetry 2.5.8: broker connections and the seeded Machine operators set.

Revision ID: tel258a01
Revises: dec257a02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tel258a01"
down_revision = "dec257a02"
branch_labels = None
depends_on = None

OPERATORS = "Machine operators"
OPERATORS_DESC = (
    "People in this set can send commands to machines over telemetry, such as a "
    "safety hold or a new task. Every command is logged with who sent it and why."
)


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table("telemetry_connections"):
        op.create_table(
            "telemetry_connections",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("broker_url", sa.Text(), nullable=False),
            sa.Column(
                "topics",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[\"spBv1.0/#\"]'::jsonb"),
            ),
            sa.Column(
                "raw_topics",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("username", sa.String(255), nullable=True),
            sa.Column("password", sa.Text(), nullable=True),
            sa.Column(
                "protocol",
                sa.String(32),
                nullable=False,
                server_default="sparkplug_b",
            ),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
            sa.Column(
                "shared_subscription",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "team_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("permission_sets.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_by",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "tenant_id", "name", name="uq_telemetry_connection_name"
            ),
        )
        op.create_index(
            "ix_telemetry_connections_tenant_id", "telemetry_connections", ["tenant_id"]
        )
        op.create_index(
            "ix_telemetry_connections_team_id", "telemetry_connections", ["team_id"]
        )
        op.create_index(
            "ix_telemetry_connections_enabled", "telemetry_connections", ["enabled"]
        )

    op.execute(
        sa.text(
            "UPDATE permission_sets SET builtin_key = 'machine_operators' "
            "WHERE name = :name AND builtin_key IS NULL"
        ).bindparams(name=OPERATORS)
    )
    op.execute(
        sa.text(
            "INSERT INTO permission_sets (id, tenant_id, name, description, capabilities, "
            "builtin_key, created_at, updated_at) "
            "SELECT gen_random_uuid(), t.id, :name, :desc, "
            'CAST(\'["telemetry.view", "telemetry.command"]\' AS jsonb), '
            "'machine_operators', now(), now() FROM tenants t "
            "WHERE NOT EXISTS (SELECT 1 FROM permission_sets p WHERE p.tenant_id = t.id "
            "AND (p.builtin_key = 'machine_operators' OR p.name = :name))"
        ).bindparams(name=OPERATORS, desc=OPERATORS_DESC)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM permission_sets WHERE builtin_key = 'machine_operators' "
            "AND NOT EXISTS (SELECT 1 FROM permission_assignments a "
            "WHERE a.permission_set_id = permission_sets.id)"
        )
    )
    if _has_table("telemetry_connections"):
        op.drop_table("telemetry_connections")
