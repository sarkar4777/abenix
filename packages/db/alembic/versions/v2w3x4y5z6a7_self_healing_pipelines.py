"""Self-healing pipelines — failure-diff capture + patch proposals."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "v2w3x4y5z6a7"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    postgresql.ENUM(
        "pending", "accepted", "rejected", "superseded",
        name="pipeline_patch_status", create_type=False,
    ).create(bind, checkfirst=True)

    op.create_table(
        "pipeline_run_diffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("executions.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # Which node failed
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_kind", sa.String(64), nullable=False),     # tool|agent|http|switch|map|reduce
        sa.Column("node_target", sa.String(255), nullable=True),    # tool name or agent id
        # What went wrong
        sa.Column("error_class", sa.String(128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_traceback", sa.Text(), nullable=True),
        # Structured payloads
        sa.Column("expected_shape", postgresql.JSONB(), nullable=True),  # JSONSchema-like, derived from past successes
        sa.Column("observed_shape", postgresql.JSONB(), nullable=True),  # actual response shape that broke
        sa.Column("expected_sample", postgresql.JSONB(), nullable=True), # example output from a recent success
        sa.Column("observed_sample", postgresql.JSONB(), nullable=True), # the failing output
        sa.Column("upstream_inputs", postgresql.JSONB(), nullable=True), # inputs the node received
        # Telemetry
        sa.Column("recent_success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recent_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_prd_pipeline_created", "pipeline_run_diffs",
                    ["pipeline_id", "created_at"])
    op.create_index("ix_prd_node_error", "pipeline_run_diffs",
                    ["pipeline_id", "node_id", "error_class"])

    op.create_table(
        "pipeline_patch_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("triggering_diff_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("pipeline_run_diffs.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("triggering_execution_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("executions.id", ondelete="SET NULL"),
                  nullable=True),
        # Authored by the Pipeline Surgeon agent — record which one for audit
        sa.Column("author_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False, server_default="0.50"),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="low"),  # low|medium|high
        # Snapshots: full DSL before, JSON-Patch ops, full DSL after.
        # Storing all three gives the UI a clean diff view AND a safe rollback target.
        sa.Column("dsl_before", postgresql.JSONB(), nullable=False),
        sa.Column("json_patch", postgresql.JSONB(), nullable=False),
        sa.Column("dsl_after", postgresql.JSONB(), nullable=False),
        sa.Column("status",
                  postgresql.ENUM("pending", "accepted", "rejected", "superseded",
                                  name="pipeline_patch_status", create_type=False),
                  nullable=False, server_default="pending"),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ppp_pipeline_status", "pipeline_patch_proposals",
                    ["pipeline_id", "status"])
    op.create_index("ix_ppp_tenant_created", "pipeline_patch_proposals",
                    ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ppp_tenant_created", table_name="pipeline_patch_proposals")
    op.drop_index("ix_ppp_pipeline_status", table_name="pipeline_patch_proposals")
    op.drop_table("pipeline_patch_proposals")
    op.drop_index("ix_prd_node_error", table_name="pipeline_run_diffs")
    op.drop_index("ix_prd_pipeline_created", table_name="pipeline_run_diffs")
    op.drop_table("pipeline_run_diffs")
    op.execute("DROP TYPE IF EXISTS pipeline_patch_status;")
