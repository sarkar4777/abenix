"""KB v2 phase 3 — ontology_schemas table."""
from alembic import op
import sqlalchemy as sa


revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ontology_schemas",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("project_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(2000),
                  nullable=False, server_default=""),
        sa.Column("entity_types",
                  sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("relationship_types",
                  sa.dialects.postgresql.JSONB(), nullable=False,
                  server_default="[]"),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "version",
                            name="uq_ontology_proj_version"),
    )
    op.create_index(
        "ix_ontology_schemas_project", "ontology_schemas", ["project_id"],
    )

    # Now that the FK target table exists, retro-add the FK constraint
    # on the project's pointer column. Phase 1 created the column
    # ontology_schema_id but couldn't add the FK because the target
    # table didn't exist yet. Wrap in try/IF NOT EXISTS for re-runs.
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE knowledge_projects
            ADD CONSTRAINT fk_kproj_ontology_schema
            FOREIGN KEY (ontology_schema_id)
            REFERENCES ontology_schemas(id) ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_projects "
        "DROP CONSTRAINT IF EXISTS fk_kproj_ontology_schema;"
    )
    op.drop_index("ix_ontology_schemas_project", table_name="ontology_schemas")
    op.drop_table("ontology_schemas")
