"""Add MemPalace hierarchical memory tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM

revision = "g7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create hall_type enum
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hall_type') THEN "
        "CREATE TYPE hall_type AS ENUM ('FACTUAL', 'PROCEDURAL', 'EPISODIC', 'EMOTIONAL', 'DECISION'); "
        "END IF; "
        "END $$;"
    )

    # memory_wings — top-level grouping (person, project, topic)
    op.create_table(
        "memory_wings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_wings_agent", "memory_wings", ["agent_id", "tenant_id"])
    op.create_index("ix_memory_wings_agent_id", "memory_wings", ["agent_id"])
    op.create_index("ix_memory_wings_tenant_id", "memory_wings", ["tenant_id"])

    # memory_halls — category within a wing
    op.create_table(
        "memory_halls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wing_id", UUID(as_uuid=True), sa.ForeignKey("memory_wings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hall_type", ENUM("FACTUAL", "PROCEDURAL", "EPISODIC", "EMOTIONAL", "DECISION", name="hall_type", create_type=False), nullable=False, server_default="FACTUAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # memory_rooms — specific memory unit
    op.create_table(
        "memory_rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("hall_id", UUID(as_uuid=True), sa.ForeignKey("memory_halls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("summary_aaak", sa.Text, nullable=True),
        sa.Column("full_content", sa.Text, nullable=False),
        sa.Column("importance", sa.Integer, nullable=False, server_default="5"),
        sa.Column("access_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("embedding_id", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_rooms_hall", "memory_rooms", ["hall_id"])

    # memory_drawers — verbatim content
    op.create_table(
        "memory_drawers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", UUID(as_uuid=True), sa.ForeignKey("memory_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # memory_entities — knowledge graph nodes
    op.create_table(
        "memory_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("properties", JSONB, nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_entities_agent", "memory_entities", ["agent_id", "name"])
    op.create_index("ix_memory_entities_agent_id", "memory_entities", ["agent_id"])

    # memory_relations — knowledge graph edges
    op.create_table(
        "memory_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("from_entity_id", UUID(as_uuid=True), sa.ForeignKey("memory_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_entity_id", UUID(as_uuid=True), sa.ForeignKey("memory_entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(100), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("properties", JSONB, nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("memory_relations")
    op.drop_index("ix_memory_entities_agent_id", "memory_entities")
    op.drop_index("ix_memory_entities_agent", "memory_entities")
    op.drop_table("memory_entities")
    op.drop_table("memory_drawers")
    op.drop_index("ix_memory_rooms_hall", "memory_rooms")
    op.drop_table("memory_rooms")
    op.drop_table("memory_halls")
    op.drop_index("ix_memory_wings_tenant_id", "memory_wings")
    op.drop_index("ix_memory_wings_agent_id", "memory_wings")
    op.drop_index("ix_memory_wings_agent", "memory_wings")
    op.drop_table("memory_wings")
    sa.Enum(name="hall_type").drop(op.get_bind(), checkfirst=True)
