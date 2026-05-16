"""KB v2 deviation fix — project_members for per-project ACLs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM(
        "VIEW",
        "EDIT",
        "ADMIN",
        name="project_role",
        create_type=False,
    ).create(bind, checkfirst=True)

    op.create_table(
        "project_members",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "VIEW", "EDIT", "ADMIN", name="project_role", create_type=False
            ),
            nullable=False,
            server_default="VIEW",
        ),
        sa.Column(
            "granted_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )
    op.create_index(
        "ix_project_members_project",
        "project_members",
        ["project_id"],
    )
    op.create_index(
        "ix_project_members_user",
        "project_members",
        ["user_id"],
    )

    # Backfill: every project's creator becomes its first ADMIN. This
    # preserves access for users who created projects before the
    # membership gate existed.
    op.execute("""
        INSERT INTO project_members
            (id, project_id, user_id, role, granted_by)
        SELECT gen_random_uuid(), p.id, p.created_by, 'ADMIN', p.created_by
        FROM knowledge_projects p
        WHERE p.created_by IS NOT NULL
        ON CONFLICT (project_id, user_id) DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index("ix_project_members_user", table_name="project_members")
    op.drop_index("ix_project_members_project", table_name="project_members")
    op.drop_table("project_members")
    op.execute("DROP TYPE IF EXISTS project_role;")
