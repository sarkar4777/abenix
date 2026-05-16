"""Add GDPR columns: consent_given_at, privacy_policy_version, deleted_at."""

from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GDPR consent tracking
    op.add_column(
        "users",
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users", sa.Column("privacy_policy_version", sa.String(20), nullable=True)
    )
    # Soft delete support
    op.add_column(
        "users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "agents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "deleted_at")
    op.drop_column("agents", "deleted_at")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "privacy_policy_version")
    op.drop_column("users", "consent_given_at")
