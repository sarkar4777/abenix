"""Governed self-improvement: feedback, lessons, clusters, proposals, case and revision sources.

Revision ID: selfimp0001
Revises: modrev00001
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "selfimp0001"
down_revision = "modrev00001"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build the tables first, so every step tolerates it.
def _insp():
    return sa.inspect(op.get_bind())


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in _insp().get_columns(table)}


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def _id() -> sa.Column:
    return sa.Column(
        "id", _UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    # lessons is a plain table, a create_all build cannot make a partitioned one
    if not _insp().has_table("feedback"):
        op.create_table(
            "feedback",
            _id(),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("user_id", _UUID, nullable=True),
            sa.Column("execution_id", _UUID, nullable=True),
            sa.Column("conversation_id", _UUID, nullable=True),
            sa.Column("message_id", _UUID, nullable=True),
            sa.Column("agent_id", _UUID, nullable=True),
            sa.Column("rating", sa.SmallInteger(), nullable=False),
            sa.Column("correction", sa.Text(), nullable=True),
            _ts("created_at"),
        )
    _create_index(
        "ix_feedback_tenant_agent_created",
        "feedback",
        ["tenant_id", "agent_id", "created_at"],
    )
    _create_index("ix_feedback_tenant_created", "feedback", ["tenant_id", "created_at"])
    _create_index("ix_feedback_user", "feedback", ["user_id"])

    if not _insp().has_table("lesson_clusters"):
        op.create_table(
            "lesson_clusters",
            _id(),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "agent_id",
                _UUID,
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(300), nullable=False, server_default=""),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("signature", sa.String(64), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "negative_count", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("severity", sa.String(16), nullable=False, server_default="low"),
            sa.Column("trend", _JSONB, nullable=False, server_default="[]"),
            sa.Column("state", sa.String(16), nullable=False, server_default="open"),
            sa.Column("meta", _JSONB, nullable=False, server_default="{}"),
            sa.Column("last_lesson_at", sa.DateTime(timezone=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
    _create_index(
        "uq_lesson_clusters_signature",
        "lesson_clusters",
        ["tenant_id", "agent_id", "signature"],
        unique=True,
    )
    _create_index(
        "ix_lesson_clusters_tenant_state",
        "lesson_clusters",
        ["tenant_id", "state", "last_lesson_at"],
    )

    if not _insp().has_table("lessons"):
        op.create_table(
            "lessons",
            _id(),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("agent_id", _UUID, nullable=False),
            sa.Column("agent_config_hash", sa.String(64), nullable=True),
            sa.Column("execution_id", _UUID, nullable=True),
            sa.Column(
                "cluster_id",
                _UUID,
                sa.ForeignKey("lesson_clusters.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("case_id", _UUID, nullable=True),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column(
                "polarity", sa.String(16), nullable=False, server_default="negative"
            ),
            sa.Column("input_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("output_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("expected", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("failure_code", sa.String(64), nullable=True),
            sa.Column("tool_name", sa.String(160), nullable=True),
            sa.Column("capture_key", sa.String(200), nullable=True),
            sa.Column("by_user", _UUID, nullable=True),
            sa.Column("meta", _JSONB, nullable=False, server_default="{}"),
            _ts("created_at"),
        )
    _create_index(
        "uq_lessons_capture", "lessons", ["source", "capture_key"], unique=True
    )
    _create_index("ix_lessons_tenant_created", "lessons", ["tenant_id", "created_at"])
    _create_index(
        "ix_lessons_agent_created", "lessons", ["tenant_id", "agent_id", "created_at"]
    )
    _create_index("ix_lessons_cluster", "lessons", ["cluster_id", "created_at"])
    _create_index("ix_lessons_execution", "lessons", ["execution_id"])
    _create_index("ix_lessons_by_user", "lessons", ["by_user"])
    # the clustering job only ever reads lessons nobody has grouped yet
    _create_index(
        "ix_lessons_unclustered",
        "lessons",
        ["created_at"],
        postgresql_where=sa.text("cluster_id IS NULL"),
    )

    if not _insp().has_table("improvement_proposals"):
        op.create_table(
            "improvement_proposals",
            _id(),
            sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column(
                "agent_id",
                _UUID,
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "cluster_id",
                _UUID,
                sa.ForeignKey("lesson_clusters.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("base_config_hash", sa.String(64), nullable=True),
            sa.Column("change_kind", sa.String(32), nullable=False),
            sa.Column("diff", _JSONB, nullable=False, server_default="{}"),
            sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
            sa.Column("risk", sa.String(16), nullable=False, server_default="low"),
            sa.Column(
                "state", sa.String(24), nullable=False, server_default="drafting"
            ),
            sa.Column("progress", _JSONB, nullable=False, server_default="[]"),
            sa.Column("proof", _JSONB, nullable=True),
            sa.Column("approval_id", _UUID, nullable=True),
            sa.Column("released_revision_id", _UUID, nullable=True),
            sa.Column("watch_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "watch_runs_target", sa.Integer(), nullable=False, server_default="200"
            ),
            sa.Column("watch_result", _JSONB, nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_by", _UUID, nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
    _create_index(
        "ix_improvement_proposals_agent",
        "improvement_proposals",
        ["tenant_id", "agent_id", "created_at"],
    )
    _create_index(
        "ix_improvement_proposals_state",
        "improvement_proposals",
        ["tenant_id", "state"],
    )
    _create_index(
        "ix_improvement_proposals_cluster", "improvement_proposals", ["cluster_id"]
    )

    if not _has_column("eval_cases", "state"):
        op.add_column(
            "eval_cases",
            sa.Column(
                "state", sa.String(16), nullable=False, server_default="accepted"
            ),
        )
    if not _has_column("eval_cases", "source_lesson_id"):
        op.add_column("eval_cases", sa.Column("source_lesson_id", _UUID, nullable=True))
    _create_index("ix_eval_cases_suite_state", "eval_cases", ["suite_id", "state"])

    if not _has_column("agent_revisions", "source"):
        op.add_column(
            "agent_revisions",
            sa.Column("source", sa.String(20), nullable=False, server_default="edit"),
        )
    if not _has_column("agent_revisions", "proposal_id"):
        op.add_column("agent_revisions", sa.Column("proposal_id", _UUID, nullable=True))

    # the lesson harvest reads recent failures, drift and eval results by time
    _create_index("ix_pipeline_run_diffs_created", "pipeline_run_diffs", ["created_at"])
    _create_index("ix_drift_alerts_created", "drift_alerts", ["created_at"])
    _create_index("ix_eval_results_created", "eval_results", ["created_at"])
    _create_index(
        "ix_executions_failed_completed",
        "executions",
        ["completed_at"],
        postgresql_where=sa.text("status = 'FAILED'"),
    )


def downgrade() -> None:
    op.drop_index("ix_executions_failed_completed", table_name="executions")
    op.drop_index("ix_eval_results_created", table_name="eval_results")
    op.drop_index("ix_drift_alerts_created", table_name="drift_alerts")
    op.drop_index("ix_pipeline_run_diffs_created", table_name="pipeline_run_diffs")
    op.drop_column("agent_revisions", "proposal_id")
    op.drop_column("agent_revisions", "source")
    op.drop_index("ix_eval_cases_suite_state", table_name="eval_cases")
    op.drop_column("eval_cases", "source_lesson_id")
    op.drop_column("eval_cases", "state")
    op.drop_table("improvement_proposals")
    op.drop_table("lessons")
    op.drop_table("lesson_clusters")
    op.drop_table("feedback")
