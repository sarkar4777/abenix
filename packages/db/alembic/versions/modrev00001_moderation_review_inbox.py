"""Moderation hold for review: review inbox, hold timeouts and retention indexes.

Revision ID: modrev00001
Revises: trig0prov01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "modrev00001"
down_revision = "trig0prov01"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build the table first, so every step tolerates it.
def _insp():
    return sa.inspect(op.get_bind())


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in _insp().get_columns(table)}


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    op.execute("ALTER TYPE moderation_action ADD VALUE IF NOT EXISTS 'hold'")
    op.execute("ALTER TYPE moderation_event_outcome ADD VALUE IF NOT EXISTS 'held'")

    if not _has_column("moderation_policies", "hold_timeout_minutes"):
        op.add_column(
            "moderation_policies",
            sa.Column(
                "hold_timeout_minutes",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("60"),
            ),
        )
    if not _has_column("moderation_policies", "hold_timeout_action"):
        op.add_column(
            "moderation_policies",
            sa.Column(
                "hold_timeout_action",
                sa.String(16),
                nullable=False,
                server_default="reject",
            ),
        )

    if not _insp().has_table("moderation_reviews"):
        op.create_table(
            "moderation_reviews",
            sa.Column("id", _UUID, primary_key=True),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "policy_id",
                _UUID,
                sa.ForeignKey("moderation_policies.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("event_id", _UUID, nullable=True),
            sa.Column("user_id", _UUID, nullable=True),
            sa.Column("execution_id", _UUID, nullable=True),
            sa.Column("agent_id", _UUID, nullable=True),
            sa.Column("conversation_id", _UUID, nullable=True),
            sa.Column("message_id", _UUID, nullable=True),
            sa.Column(
                "source", sa.String(40), nullable=False, server_default="pre_llm"
            ),
            sa.Column(
                "status", sa.String(24), nullable=False, server_default="pending"
            ),
            sa.Column(
                "priority",
                sa.SmallInteger(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("categories", _JSONB, nullable=False, server_default="[]"),
            sa.Column("category_scores", _JSONB, nullable=False, server_default="{}"),
            sa.Column("spans", _JSONB, nullable=False, server_default="[]"),
            sa.Column("held_content", sa.Text(), nullable=True),
            sa.Column("released_content", sa.Text(), nullable=True),
            sa.Column("content_sha256", sa.String(64), nullable=True),
            sa.Column(
                "content_length", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("masked_content", sa.Text(), nullable=True),
            sa.Column(
                "redaction_mask", sa.String(40), nullable=False, server_default="█████"
            ),
            sa.Column("content_purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "timeout_action", sa.String(16), nullable=False, server_default="reject"
            ),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("assigned_to", _UUID, nullable=True),
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_by", _UUID, nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_reason", sa.Text(), nullable=True),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("history", _JSONB, nullable=False, server_default="[]"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    _create_index(
        "ix_moderation_reviews_tenant_id", "moderation_reviews", ["tenant_id"]
    )
    _create_index(
        "ix_moderation_reviews_queue",
        "moderation_reviews",
        ["tenant_id", "status", "priority", "created_at"],
    )
    _create_index(
        "ix_moderation_reviews_due", "moderation_reviews", ["status", "expires_at"]
    )
    _create_index(
        "ix_moderation_reviews_tenant_decided",
        "moderation_reviews",
        ["tenant_id", "decided_at"],
    )
    _create_index(
        "ix_moderation_reviews_user", "moderation_reviews", ["user_id", "status"]
    )
    _create_index(
        "ix_moderation_reviews_execution", "moderation_reviews", ["execution_id"]
    )
    # the announce sweep and the preview expiry only ever touch these rows
    _create_index(
        "ix_moderation_reviews_unannounced",
        "moderation_reviews",
        ["created_at"],
        postgresql_where=sa.text("notified_at IS NULL AND status = 'pending'"),
    )
    _create_index(
        "ix_moderation_events_preview_age",
        "moderation_events",
        ["created_at"],
        postgresql_where=sa.text("content_preview IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_moderation_events_preview_age", table_name="moderation_events")
    op.drop_table("moderation_reviews")
    op.drop_column("moderation_policies", "hold_timeout_action")
    op.drop_column("moderation_policies", "hold_timeout_minutes")
    # enum values stay, postgres cannot drop them
