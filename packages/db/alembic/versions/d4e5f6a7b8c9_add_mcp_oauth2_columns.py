"""add oauth2 columns to user_mcp_connections"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_mcp_connections",
        sa.Column("oauth2_client_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "user_mcp_connections",
        sa.Column("oauth2_authorization_url", sa.String(1000), nullable=True),
    )
    op.add_column(
        "user_mcp_connections",
        sa.Column("oauth2_token_url", sa.String(1000), nullable=True),
    )
    op.add_column(
        "user_mcp_connections",
        sa.Column("oauth2_access_token_enc", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_mcp_connections",
        sa.Column("oauth2_refresh_token_enc", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_mcp_connections",
        sa.Column(
            "oauth2_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_mcp_connections", "oauth2_token_expires_at")
    op.drop_column("user_mcp_connections", "oauth2_refresh_token_enc")
    op.drop_column("user_mcp_connections", "oauth2_access_token_enc")
    op.drop_column("user_mcp_connections", "oauth2_token_url")
    op.drop_column("user_mcp_connections", "oauth2_authorization_url")
    op.drop_column("user_mcp_connections", "oauth2_client_id")
