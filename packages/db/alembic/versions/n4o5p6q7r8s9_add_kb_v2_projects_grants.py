"""KB v2 — projects + collection grants + per-collection ontology hooks."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "private", "project", "tenant",
        name="collection_visibility", create_type=False,
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        "READ", "WRITE", "ADMIN",
        name="collection_permission", create_type=False,
    ).create(bind, checkfirst=True)

    op.create_table(
        "knowledge_projects",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("ontology_schema_id",
                  sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_kproj_tenant_slug"),
    )
    op.create_index(
        "ix_kproj_tenant_created", "knowledge_projects",
        ["tenant_id", "created_at"],
    )

    op.add_column(
        "knowledge_bases",
        sa.Column("project_id",
                  sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_projects.id"), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "default_visibility",
            postgresql.ENUM("private", "project", "tenant",
                            name="collection_visibility",
                            create_type=False),
            nullable=False, server_default="project",
        ),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("vector_backend", sa.String(20),
                  nullable=False, server_default="pinecone"),
    )
    op.create_index("ix_kb_project", "knowledge_bases", ["project_id"])

    op.create_table(
        "agent_collection_grants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("agent_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("collection_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column(
            "permission",
            postgresql.ENUM("READ", "WRITE", "ADMIN",
                            name="collection_permission", create_type=False),
            nullable=False, server_default="READ",
        ),
        sa.Column("granted_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "collection_id",
                            name="uq_agent_collection_grant"),
    )
    op.create_index(
        "ix_agent_collection_grants_agent", "agent_collection_grants",
        ["agent_id"],
    )
    op.create_index(
        "ix_agent_collection_grants_collection", "agent_collection_grants",
        ["collection_id"],
    )

    op.create_table(
        "user_collection_grants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("collection_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column(
            "permission",
            postgresql.ENUM("READ", "WRITE", "ADMIN",
                            name="collection_permission", create_type=False),
            nullable=False, server_default="READ",
        ),
        sa.Column("granted_by", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "collection_id",
                            name="uq_user_collection_grant"),
    )
    op.create_index(
        "ix_user_collection_grants_user", "user_collection_grants", ["user_id"],
    )
    op.create_index(
        "ix_user_collection_grants_collection", "user_collection_grants",
        ["collection_id"],
    )

    # 1) One "Default" KnowledgeProject per tenant that already has KBs.
    #    Pick the oldest tenant admin as created_by; fall back to any
    #    user in the tenant. If neither exists, the tenant has no KBs
    #    so we skip it (handled by the WHERE EXISTS clause below).
    op.execute("""
        INSERT INTO knowledge_projects
            (id, tenant_id, name, slug, description, created_by)
        SELECT
            gen_random_uuid(),
            t.id,
            'Default',
            'default',
            'Auto-created during KB v2 migration; holds collections that pre-date the project hierarchy.',
            COALESCE(
                (SELECT u.id FROM users u
                 WHERE u.tenant_id = t.id AND LOWER(u.role::text) = 'admin'
                 ORDER BY u.created_at LIMIT 1),
                (SELECT u.id FROM users u
                 WHERE u.tenant_id = t.id
                 ORDER BY u.created_at LIMIT 1)
            )
        FROM tenants t
        WHERE EXISTS (
            SELECT 1 FROM knowledge_bases kb WHERE kb.tenant_id = t.id
        )
        AND NOT EXISTS (
            SELECT 1 FROM knowledge_projects p
            WHERE p.tenant_id = t.id AND p.slug = 'default'
        );
    """)

    # 2) Every legacy KB gets project_id set to its tenant's Default.
    op.execute("""
        UPDATE knowledge_bases kb
        SET project_id = (
            SELECT id FROM knowledge_projects p
            WHERE p.tenant_id = kb.tenant_id AND p.slug = 'default'
            LIMIT 1
        )
        WHERE kb.project_id IS NULL;
    """)

    # 3) Every KB with agent_id gets one AgentCollectionGrant. The
    #    runtime resolver unions this set with any explicit grants —
    #    so legacy attachments keep working unchanged.
    op.execute("""
        INSERT INTO agent_collection_grants
            (id, agent_id, collection_id, permission, granted_by)
        SELECT
            gen_random_uuid(), kb.agent_id, kb.id, 'READ', NULL
        FROM knowledge_bases kb
        WHERE kb.agent_id IS NOT NULL
        ON CONFLICT (agent_id, collection_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index("ix_user_collection_grants_collection",
                  table_name="user_collection_grants")
    op.drop_index("ix_user_collection_grants_user",
                  table_name="user_collection_grants")
    op.drop_table("user_collection_grants")

    op.drop_index("ix_agent_collection_grants_collection",
                  table_name="agent_collection_grants")
    op.drop_index("ix_agent_collection_grants_agent",
                  table_name="agent_collection_grants")
    op.drop_table("agent_collection_grants")

    op.drop_index("ix_kb_project", table_name="knowledge_bases")
    op.drop_column("knowledge_bases", "vector_backend")
    op.drop_column("knowledge_bases", "created_by")
    op.drop_column("knowledge_bases", "default_visibility")
    op.drop_column("knowledge_bases", "project_id")

    op.drop_index("ix_kproj_tenant_created", table_name="knowledge_projects")
    op.drop_table("knowledge_projects")

    op.execute("DROP TYPE IF EXISTS collection_permission;")
    op.execute("DROP TYPE IF EXISTS collection_visibility;")
