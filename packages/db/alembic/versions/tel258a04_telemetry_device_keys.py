"""Telemetry 2.5.8 T9: per-device and gateway keys for HTTP push sources.

Revision ID: tel258a04
Revises: tel258a02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tel258a04"
down_revision = "tel258a02"
branch_labels = None
depends_on = None

TABLE = "telemetry_device_keys"


def upgrade() -> None:
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("telemetry_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False, server_default="device"),
        sa.Column("device_id", sa.String(255), nullable=False),
        sa.Column("group", sa.String(255), nullable=True),
        sa.Column(
            "allowed_nodes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("label", sa.String(255), nullable=False, server_default=""),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False),
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
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash", name="uq_telemetry_device_key_hash"),
    )
    op.create_index("ix_telemetry_device_keys_tenant_id", TABLE, ["tenant_id"])
    op.create_index(
        "ix_telemetry_device_keys_connection", TABLE, ["connection_id", "device_id"]
    )


def downgrade() -> None:
    if TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(TABLE)
