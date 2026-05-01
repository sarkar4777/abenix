"""Add agent_memories table and cost_guardrails columns."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create memory_type enum via raw SQL to avoid SQLAlchemy double-creation
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'memory_type') THEN "
        "CREATE TYPE memory_type AS ENUM ('FACTUAL', 'PROCEDURAL', 'EPISODIC'); "
        "END IF; "
        "END $$;"
    )

    # Create agent_memories table — use raw SQL for the enum column to avoid
    # SQLAlchemy trying to CREATE TYPE again
    op.create_table(
        "agent_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("key", sa.String(500), nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("memory_type", ENUM("FACTUAL", "PROCEDURAL", "EPISODIC", name="memory_type", create_type=False), nullable=False, server_default="FACTUAL"),
        sa.Column("importance", sa.Integer, nullable=False, server_default="5"),
        sa.Column("access_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agent_memories_agent_key", "agent_memories", ["agent_id", "key"])
    op.create_index("ix_agent_memories_agent_type", "agent_memories", ["agent_id", "memory_type"])
    op.create_index("ix_agent_memories_tenant_agent", "agent_memories", ["tenant_id", "agent_id"])

    # Add notification_settings to users (was missing from initial migration)
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_settings JSONB DEFAULT NULL"
    )

    # Add version and traffic_weight columns to agents for A/B testing
    op.add_column("agents", sa.Column("version_tag", sa.String(50), nullable=True))
    op.add_column("agents", sa.Column("traffic_weight", sa.Numeric(5, 2), nullable=True, server_default="100"))
    op.add_column("agents", sa.Column("parent_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=True))

    # Add confidence_score and execution_trace to executions
    op.add_column("executions", sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True))
    op.add_column("executions", sa.Column("execution_trace", JSONB, nullable=True))
    op.add_column("executions", sa.Column("parent_execution_id", UUID(as_uuid=True), nullable=True))
    op.add_column("executions", sa.Column("retry_count", sa.Integer, nullable=True, server_default="0"))

    # Add cost guardrail columns to tenants
    op.add_column("tenants", sa.Column("daily_cost_limit", sa.Numeric(10, 2), nullable=True))
    op.add_column("tenants", sa.Column("monthly_cost_limit", sa.Numeric(10, 2), nullable=True))

    # Add per-agent cost limit
    op.add_column("agents", sa.Column("per_execution_cost_limit", sa.Numeric(10, 4), nullable=True))
    op.add_column("agents", sa.Column("daily_cost_limit", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "daily_cost_limit")
    op.drop_column("agents", "per_execution_cost_limit")
    op.drop_column("tenants", "monthly_cost_limit")
    op.drop_column("tenants", "daily_cost_limit")
    op.drop_column("executions", "retry_count")
    op.drop_column("executions", "parent_execution_id")
    op.drop_column("executions", "execution_trace")
    op.drop_column("executions", "confidence_score")
    op.drop_column("agents", "parent_agent_id")
    op.drop_column("agents", "traffic_weight")
    op.drop_column("agents", "version_tag")
    op.drop_index("ix_agent_memories_tenant_agent", "agent_memories")
    op.drop_index("ix_agent_memories_agent_type", "agent_memories")
    op.drop_index("ix_agent_memories_agent_key", "agent_memories")
    op.drop_table("agent_memories")
    sa.Enum(name="memory_type").drop(op.get_bind(), checkfirst=True)
