"""Agent evaluation suites: suites, golden cases, scored runs and per-case results.

Revision ID: 9465d37a97f1
Revises: 25f2dd065d53
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "9465d37a97f1"
down_revision = "25f2dd065d53"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build new tables before this runs, so every step tolerates them.
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


def upgrade() -> None:
    _create_table(
        "eval_suites",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "agent_id",
            _UUID,
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gating", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pass_threshold", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("schedule_cron", sa.String(120), nullable=True),
        _ts("next_run_at", nullable=True),
        sa.Column(
            "rerun_on_model_change",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("judge_model", sa.String(100), nullable=True),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("created_at"),
        _ts("updated_at"),
    )
    _create_index(
        "ix_eval_suites_tenant_agent", "eval_suites", ["tenant_id", "agent_id"]
    )
    _create_index(
        "ix_eval_suites_due",
        "eval_suites",
        ["next_run_at"],
        postgresql_where=sa.text("schedule_cron IS NOT NULL"),
    )

    _create_table(
        "eval_cases",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column(
            "suite_id",
            _UUID,
            sa.ForeignKey("eval_suites.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("input_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("context", _JSONB, nullable=False, server_default="{}"),
        sa.Column("assertions", _JSONB, nullable=False, server_default="[]"),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("tags", _JSONB, nullable=False, server_default="[]"),
        sa.Column("source_execution_id", _UUID, nullable=True),
        sa.Column("reference_output", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )

    _create_table(
        "eval_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column(
            "suite_id",
            _UUID,
            sa.ForeignKey("eval_suites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", _UUID, nullable=True),
        sa.Column("config_hash", sa.String(64), nullable=True),
        sa.Column("agent_revision", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "model_override", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.9"),
        sa.Column("threshold_met", sa.Boolean(), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "triggered_by", sa.String(16), nullable=False, server_default="manual"
        ),
        sa.Column(
            "triggered_by_user",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("started_at", nullable=True),
        _ts("completed_at", nullable=True),
    )
    _create_index("ix_eval_runs_suite_created", "eval_runs", ["suite_id", "created_at"])
    _create_index("ix_eval_runs_config", "eval_runs", ["agent_id", "config_hash"])
    _create_index(
        "ix_eval_runs_active",
        "eval_runs",
        ["created_at"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    _create_table(
        "eval_results",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column(
            "run_id",
            _UUID,
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "case_id",
            _UUID,
            sa.ForeignKey("eval_cases.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("case_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("execution_id", _UUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="completed"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("assertion_results", _JSONB, nullable=False, server_default="[]"),
        sa.Column("output_excerpt", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        _ts("created_at"),
    )


def downgrade() -> None:
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_active", table_name="eval_runs")
    op.drop_index("ix_eval_runs_config", table_name="eval_runs")
    op.drop_index("ix_eval_runs_suite_created", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_index("ix_eval_suites_due", table_name="eval_suites")
    op.drop_index("ix_eval_suites_tenant_agent", table_name="eval_suites")
    op.drop_table("eval_suites")
