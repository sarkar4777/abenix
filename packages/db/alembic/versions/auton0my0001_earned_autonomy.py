"""Earned autonomy: action types, grants, level changes and the action ledger.

Revision ID: auton0my0001
Revises: p3rs0na0vec1
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "auton0my0001"
down_revision = "p3rs0na0vec1"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build these tables first, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _create_table(name: str, *cols, **kw) -> None:
    if not _insp().has_table(name):
        op.create_table(name, *cols, **kw)


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def _ts(name: str, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False)


def upgrade() -> None:
    _create_table(
        "action_types",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("match", _JSONB, nullable=True),
        sa.Column("effect", _JSONB, nullable=True),
        sa.Column("world_model", _JSONB, nullable=True),
        sa.Column("outcome_probe", _JSONB, nullable=True),
        sa.Column("limits_decision_key", sa.String(160), nullable=True),
        sa.Column("max_band_width", sa.Float(), nullable=True),
        sa.Column(
            "reversible", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("ceiling", sa.Integer(), nullable=True),
        sa.Column("policy", _JSONB, nullable=True),
        sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_action_type_key"),
    )
    _create_index("ix_action_types_tenant_id", "action_types", ["tenant_id"])
    _create_index("ix_action_types_tool_name", "action_types", ["tool_name"])

    _create_table(
        "autonomy_grants",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "agent_id",
            _UUID,
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "action_type_id",
            _UUID,
            sa.ForeignKey("action_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope", _JSONB, nullable=True),
        sa.Column("scope_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ceiling", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        _ts("level_since"),
        sa.Column("approval_id", _UUID, nullable=True),
        sa.Column(
            "granted_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("agent_config_hash", sa.String(64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("attention", sa.Text(), nullable=True),
        sa.Column("recommended_level", sa.Integer(), nullable=True),
        _ts("review_notified_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "tenant_id",
            "agent_id",
            "action_type_id",
            "scope_hash",
            name="uq_autonomy_grant_scope",
        ),
    )
    _create_index("ix_autonomy_grants_tenant_id", "autonomy_grants", ["tenant_id"])
    _create_index("ix_autonomy_grants_agent_id", "autonomy_grants", ["agent_id"])
    _create_index(
        "ix_autonomy_grants_action_type_id", "autonomy_grants", ["action_type_id"]
    )

    _create_table(
        "autonomy_changes",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "grant_id",
            _UUID,
            sa.ForeignKey("autonomy_grants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", _UUID, nullable=True),
        sa.Column("from_level", sa.Integer(), nullable=False),
        sa.Column("to_level", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="system"),
        sa.Column("actor_id", _UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("evidence", _JSONB, nullable=True),
        _ts("created_at"),
    )
    _create_index(
        "ix_autonomy_changes_grant", "autonomy_changes", ["grant_id", "created_at"]
    )
    _create_index("ix_autonomy_changes_tenant_id", "autonomy_changes", ["tenant_id"])

    _create_table(
        "agent_actions",
        sa.Column(
            "id",
            _UUID,
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        _tenant(),
        sa.Column("execution_id", _UUID, nullable=True),
        sa.Column("tool_call_id", sa.String(120), nullable=True),
        sa.Column("agent_id", _UUID, nullable=True),
        sa.Column("agent_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("agent_config_hash", sa.String(64), nullable=True),
        sa.Column("user_id", _UUID, nullable=True),
        sa.Column("action_type_id", _UUID, nullable=True),
        sa.Column("grant_id", _UUID, nullable=True),
        sa.Column("tool_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("level_at_time", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="unmanaged"),
        sa.Column("target", sa.String(500), nullable=True),
        sa.Column("arguments", _JSONB, nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("prediction", _JSONB, nullable=True),
        sa.Column("limits_result", _JSONB, nullable=True),
        sa.Column("approval_id", _UUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="recorded"),
        sa.Column("decided_by", _UUID, nullable=True),
        _ts("decided_at", nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        _ts("executed_at", nullable=True),
        sa.Column("result_preview", sa.Text(), nullable=True),
        sa.Column("reviewer_answer", sa.String(16), nullable=True),
        sa.Column("reviewer_alternative", sa.Text(), nullable=True),
        sa.Column("outcome", _JSONB, nullable=True),
        _ts("outcome_due_at", nullable=True),
        sa.Column(
            "outcome_status", sa.String(16), nullable=False, server_default="none"
        ),
        sa.Column("outcome_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", _JSONB, nullable=True),
        sa.Column("harm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("harm_note", sa.Text(), nullable=True),
        sa.Column("events_sent", sa.String(40), nullable=False, server_default=""),
        _ts("created_at"),
    )
    _create_index("ix_agent_actions_tenant_id", "agent_actions", ["tenant_id"])
    _create_index("ix_agent_actions_agent_id", "agent_actions", ["agent_id"])
    _create_index(
        "uq_agent_actions_call",
        "agent_actions",
        ["execution_id", "tool_call_id"],
        unique=True,
        postgresql_where=sa.text(
            "execution_id IS NOT NULL AND tool_call_id IS NOT NULL"
        ),
    )
    _create_index(
        "ix_agent_actions_grant",
        "agent_actions",
        ["tenant_id", "grant_id", "created_at"],
    )
    _create_index("ix_agent_actions_status", "agent_actions", ["tenant_id", "status"])
    _create_index(
        "ix_agent_actions_outcome_due",
        "agent_actions",
        ["outcome_status", "outcome_due_at"],
    )


def downgrade() -> None:
    op.drop_table("agent_actions")
    op.drop_table("autonomy_changes")
    op.drop_table("autonomy_grants")
    op.drop_table("action_types")
