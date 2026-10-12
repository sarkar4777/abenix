"""Telemetry 2.5.8 T8: any transport and payload format on telemetry_connections.

Existing rows become mqtt with the sparkplug_b decoder. broker_url, topics and
raw_topics stay as they are, and raw topics are read with the can_frames decoder.

Revision ID: tel258a02
Revises: tel258a01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tel258a02"
down_revision = "tel258a01"
branch_labels = None
depends_on = None

TABLE = "telemetry_connections"


def _cols() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade() -> None:
    have = _cols()
    jsonb = postgresql.JSONB()
    add = [
        ("transport", sa.String(32), sa.text("'mqtt'")),
        ("config", jsonb, sa.text("'{}'::jsonb")),
        ("secrets", jsonb, sa.text("'{}'::jsonb")),
        ("decoder", sa.String(32), sa.text("'sparkplug_b'")),
        ("decoder_config", jsonb, sa.text("'{}'::jsonb")),
        ("mapping", jsonb, sa.text("'{}'::jsonb")),
        ("strict", sa.Boolean(), sa.text("false")),
    ]
    for name, typ, default in add:
        if name not in have:
            op.add_column(
                TABLE, sa.Column(name, typ, nullable=False, server_default=default)
            )
    if "ingest_token_hash" not in have:
        op.add_column(
            TABLE, sa.Column("ingest_token_hash", sa.String(128), nullable=True)
        )
    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET transport = 'mqtt', decoder = 'sparkplug_b' "
            "WHERE transport IS NULL OR transport = ''"
        )
    )
    # the mqtt password moves next to the other secrets, the column stays readable
    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET secrets = jsonb_build_object('password', password) "
            "WHERE password IS NOT NULL AND password <> '' AND secrets = '{}'::jsonb"
        )
    )
    op.create_index(
        "ix_telemetry_connections_transport", TABLE, ["transport"], if_not_exists=True
    )


def downgrade() -> None:
    have = _cols()
    op.drop_index("ix_telemetry_connections_transport", TABLE, if_exists=True)
    for name in (
        "transport",
        "config",
        "secrets",
        "decoder",
        "decoder_config",
        "mapping",
        "ingest_token_hash",
        "strict",
    ):
        if name in have:
            op.drop_column(TABLE, name)
