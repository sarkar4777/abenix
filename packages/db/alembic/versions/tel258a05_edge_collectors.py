"""Telemetry 2.5.8 T9: Abenix Edge gateways that collect, with enrolment, config and health.

Revision ID: tel258a05
Revises: tel258a03
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tel258a05"
down_revision = "tel258a03"
branch_labels = None
depends_on = None

TABLE = "edge_gateways"


def _cols() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    if TABLE not in sa.inspect(op.get_bind()).get_table_names():
        return
    have = _cols()
    jsonb = postgresql.JSONB()
    uid = postgresql.UUID(as_uuid=True)
    tz = sa.DateTime(timezone=True)
    add = [
        ("roles", jsonb, sa.text("'[\"agents\"]'::jsonb"), False),
        ("collectors", jsonb, sa.text("'[]'::jsonb"), False),
        ("settings", jsonb, sa.text("'{}'::jsonb"), False),
        ("health", jsonb, sa.text("'{}'::jsonb"), False),
        ("config_version", sa.Integer(), sa.text("1"), False),
        ("applied_version", sa.Integer(), sa.text("0"), False),
        ("description", sa.Text(), sa.text("''"), False),
        ("version", sa.String(64), None, True),
        ("platform", sa.String(128), None, True),
        ("hostname", sa.String(255), None, True),
        ("enroll_token_hash", sa.String(128), None, True),
        ("enroll_expires_at", tz, None, True),
        ("enrolled_at", tz, None, True),
        ("revoked_at", tz, None, True),
        ("first_data_at", tz, None, True),
        ("telemetry_connection_id", uid, None, True),
        ("key_id", uid, None, True),
        ("created_by", uid, None, True),
    ]
    for name, typ, default, nullable in add:
        if name in have:
            continue
        op.add_column(
            TABLE,
            sa.Column(name, typ, nullable=nullable, server_default=default),
        )
    idx = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(TABLE)}
    if "ix_edge_gateways_enroll_token_hash" not in idx:
        op.create_index(
            "ix_edge_gateways_enroll_token_hash", TABLE, ["enroll_token_hash"]
        )
    if "ix_edge_gateways_key_id" not in idx:
        op.create_index("ix_edge_gateways_key_id", TABLE, ["key_id"])


def downgrade() -> None:
    have = _cols()
    for name in ("ix_edge_gateways_enroll_token_hash", "ix_edge_gateways_key_id"):
        try:
            op.drop_index(name, table_name=TABLE)
        except Exception:  # noqa: BLE001
            pass
    for name in (
        "roles",
        "collectors",
        "settings",
        "health",
        "config_version",
        "applied_version",
        "description",
        "version",
        "platform",
        "hostname",
        "enroll_token_hash",
        "enroll_expires_at",
        "enrolled_at",
        "revoked_at",
        "first_data_at",
        "telemetry_connection_id",
        "key_id",
        "created_by",
    ):
        if name in have:
            op.drop_column(TABLE, name)
