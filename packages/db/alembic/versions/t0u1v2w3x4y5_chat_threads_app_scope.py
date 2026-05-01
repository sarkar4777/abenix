"""scope conversations per app + subject so multi-app + multi-tenant chat is isolat"""

from alembic import op
import sqlalchemy as sa

revision = "t0u1v2w3x4y5"
down_revision = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("app_slug", sa.String(64), nullable=True))
    op.add_column(
        "conversations", sa.Column("subject_type", sa.String(40), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("subject_id", sa.String(128), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("agent_slug", sa.String(128), nullable=True)
    )
    # last_message_preview lets the sidebar render thread previews without
    # joining the messages table — just like ChatGPT shows the first turn.
    op.add_column(
        "conversations", sa.Column("last_message_preview", sa.Text, nullable=True)
    )

    op.create_index(
        "ix_conversations_app_subject",
        "conversations",
        ["app_slug", "subject_type", "subject_id", "updated_at"],
    )
    op.create_index("ix_conversations_agent_slug", "conversations", ["agent_slug"])


def downgrade() -> None:
    op.drop_index("ix_conversations_agent_slug", table_name="conversations")
    op.drop_index("ix_conversations_app_subject", table_name="conversations")
    op.drop_column("conversations", "last_message_preview")
    op.drop_column("conversations", "agent_slug")
    op.drop_column("conversations", "subject_id")
    op.drop_column("conversations", "subject_type")
    op.drop_column("conversations", "app_slug")
