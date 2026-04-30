"""Add meetings, meeting_deferrals, persona_items tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "k1f2g3h4i5j6"
down_revision = "j0e1f2g3h4i5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Voice-clone columns on users
    op.add_column("users", sa.Column("voice_id", sa.String(120), nullable=True))
    op.add_column("users", sa.Column("voice_provider", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("voice_consent_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "meetings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=True, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("provider", sa.String(20), server_default="livekit", nullable=False),
        sa.Column("room", sa.String(500), nullable=False),
        sa.Column("join_url", sa.String(1000), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), server_default="scheduled", nullable=False, index=True),
        sa.Column("scope_allow", ARRAY(sa.Text), nullable=True),
        sa.Column("scope_defer", ARRAY(sa.Text), nullable=True),
        sa.Column("persona_scopes", ARRAY(sa.Text), nullable=True),
        sa.Column("display_name", sa.String(200), server_default="Abenix Assistant", nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("transcript_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("decision_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("deferral_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("notes", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meetings_user_status", "meetings", ["user_id", "status"])
    op.create_index("ix_meetings_scheduled", "meetings", ["scheduled_at"])

    op.create_table(
        "meeting_deferrals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("meeting_id", UUID(as_uuid=True), sa.ForeignKey("meetings.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("context", sa.Text, nullable=True),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meeting_deferrals_meeting", "meeting_deferrals", ["meeting_id", "created_at"])

    op.create_table(
        "persona_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id"), nullable=True, index=True),
        sa.Column("persona_scope", sa.String(80), server_default="self", nullable=False, index=True),
        sa.Column("kind", sa.String(30), server_default="note", nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("byte_size", sa.Integer, server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("pinecone_ids", ARRAY(sa.Text), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_persona_items_user_scope", "persona_items", ["user_id", "persona_scope"])


def downgrade() -> None:
    op.drop_column("users", "voice_consent_at")
    op.drop_column("users", "voice_provider")
    op.drop_column("users", "voice_id")
    op.drop_index("ix_persona_items_user_scope", table_name="persona_items")
    op.drop_table("persona_items")
    op.drop_index("ix_meeting_deferrals_meeting", table_name="meeting_deferrals")
    op.drop_table("meeting_deferrals")
    op.drop_index("ix_meetings_scheduled", table_name="meetings")
    op.drop_index("ix_meetings_user_status", table_name="meetings")
    op.drop_table("meetings")
