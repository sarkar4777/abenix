"""Add moderation_policies + moderation_events tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "l2m3n4o5p6q7"
down_revision = "k1f2g3h4i5j6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "moderation_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("pre_llm", sa.Boolean, server_default="true", nullable=False),
        sa.Column("post_llm", sa.Boolean, server_default="true", nullable=False),
        sa.Column("on_tool_output", sa.Boolean, server_default="false", nullable=False),
        sa.Column("provider", sa.String(40), server_default="openai", nullable=False),
        sa.Column("provider_model", sa.String(80),
                  server_default="omni-moderation-latest", nullable=False),
        sa.Column("thresholds", JSONB, server_default="{}", nullable=False),
        sa.Column("default_threshold", sa.Float, server_default="0.5", nullable=False),
        sa.Column("category_actions", JSONB, server_default="{}", nullable=False),
        sa.Column(
            "default_action",
            sa.Enum("allow", "flag", "redact", "block",
                    name="moderation_action", native_enum=True),
            server_default="block", nullable=False,
        ),
        sa.Column("custom_patterns", JSONB, server_default="[]", nullable=False),
        sa.Column("redaction_mask", sa.String(40), server_default="█████", nullable=False),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_moderation_policies_tenant_active",
        "moderation_policies", ["tenant_id", "is_active"],
    )

    op.create_table(
        "moderation_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("policy_id", UUID(as_uuid=True),
                  sa.ForeignKey("moderation_policies.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("user_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("execution_id", UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(40), server_default="api_vet", nullable=False),
        sa.Column(
            "outcome",
            sa.Enum("allowed", "flagged", "redacted", "blocked", "error",
                    name="moderation_event_outcome", native_enum=True),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.Column("content_preview", sa.String(500), nullable=True),
        sa.Column("provider_response", JSONB, server_default="{}", nullable=False),
        sa.Column("acted_categories", JSONB, server_default="[]", nullable=False),
        sa.Column("latency_ms", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_moderation_events_tenant_created",
        "moderation_events", ["tenant_id", "created_at"],
    )
    op.create_index("ix_moderation_events_outcome", "moderation_events", ["outcome"])
    op.create_index("ix_moderation_events_execution", "moderation_events", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_moderation_events_execution", table_name="moderation_events")
    op.drop_index("ix_moderation_events_outcome", table_name="moderation_events")
    op.drop_index("ix_moderation_events_tenant_created", table_name="moderation_events")
    op.drop_table("moderation_events")
    op.execute("DROP TYPE IF EXISTS moderation_event_outcome")

    op.drop_index("ix_moderation_policies_tenant_active",
                  table_name="moderation_policies")
    op.drop_table("moderation_policies")
    op.execute("DROP TYPE IF EXISTS moderation_action")
