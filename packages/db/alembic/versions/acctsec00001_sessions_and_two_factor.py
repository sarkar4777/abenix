"""Revocable sign-in sessions and two-step sign-in.

Revision ID: acctsec00001
Revises: selfimp0001
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "acctsec00001"
down_revision = "selfimp0001"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


def _insp():
    return sa.inspect(op.get_bind())


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in _insp().get_columns(table)}


def upgrade() -> None:
    # the API's startup create_all may have built the table already
    if "user_sessions" not in _insp().get_table_names():
        op.create_table(
            "user_sessions",
            sa.Column(
                "id",
                _UUID,
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "user_id",
                _UUID,
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "method", sa.String(32), nullable=False, server_default="password"
            ),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_reason", sa.String(64), nullable=True),
        )
    have = {i["name"] for i in _insp().get_indexes("user_sessions")}
    for col in ("tenant_id", "user_id"):
        name = f"ix_user_sessions_{col}"
        if name not in have:
            op.create_index(name, "user_sessions", [col])

    for name, col in (
        ("totp_secret", sa.Column("totp_secret", sa.Text(), nullable=True)),
        (
            "totp_enabled_at",
            sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True),
        ),
        ("totp_last_step", sa.Column("totp_last_step", sa.BigInteger(), nullable=True)),
        (
            "totp_recovery_codes",
            sa.Column("totp_recovery_codes", postgresql.JSONB(), nullable=True),
        ),
    ):
        if not _has_column("users", name):
            op.add_column("users", col)


def downgrade() -> None:
    for name in (
        "totp_recovery_codes",
        "totp_last_step",
        "totp_enabled_at",
        "totp_secret",
    ):
        if _has_column("users", name):
            op.drop_column("users", name)
    if "user_sessions" in _insp().get_table_names():
        op.drop_table("user_sessions")
