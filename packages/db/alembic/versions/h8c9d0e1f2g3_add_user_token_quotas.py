"""Add per-user token quotas and API key usage limits."""

from alembic import op
import sqlalchemy as sa

revision = "h8c9d0e1f2g3"
down_revision = "g7b8c9d0e1f2"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return insp.has_table(name)


def _col_exists(table: str, col: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _add_col_if_missing(table: str, col: sa.Column) -> None:
    if not _col_exists(table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    # User token quotas
    _add_col_if_missing(
        "users", sa.Column("token_monthly_allowance", sa.Integer(), nullable=True)
    )
    _add_col_if_missing(
        "users",
        sa.Column(
            "tokens_used_this_month", sa.Integer(), server_default="0", nullable=False
        ),
    )
    _add_col_if_missing(
        "users", sa.Column("cost_monthly_limit", sa.Numeric(10, 2), nullable=True)
    )
    _add_col_if_missing(
        "users",
        sa.Column(
            "cost_used_this_month",
            sa.Numeric(10, 4),
            server_default="0",
            nullable=False,
        ),
    )
    _add_col_if_missing(
        "users", sa.Column("quota_reset_at", sa.DateTime(timezone=True), nullable=True)
    )

    if not _table_exists("api_keys"):
        op.create_table(
            "api_keys",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("key_hash", sa.String(255), nullable=False),
            sa.Column("key_prefix", sa.String(20), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "is_active", sa.Boolean(), server_default=sa.true(), nullable=False
            ),
            sa.Column("scopes", sa.dialects.postgresql.JSONB(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    _add_col_if_missing(
        "api_keys", sa.Column("max_monthly_tokens", sa.Integer(), nullable=True)
    )
    _add_col_if_missing(
        "api_keys",
        sa.Column("tokens_used", sa.Integer(), server_default="0", nullable=False),
    )
    _add_col_if_missing(
        "api_keys", sa.Column("max_monthly_cost", sa.Numeric(10, 2), nullable=True)
    )
    _add_col_if_missing(
        "api_keys",
        sa.Column("cost_used", sa.Numeric(10, 4), server_default="0", nullable=False),
    )


def downgrade() -> None:
    if _col_exists("api_keys", "cost_used"):
        op.drop_column("api_keys", "cost_used")
    if _col_exists("api_keys", "max_monthly_cost"):
        op.drop_column("api_keys", "max_monthly_cost")
    if _col_exists("api_keys", "tokens_used"):
        op.drop_column("api_keys", "tokens_used")
    if _col_exists("api_keys", "max_monthly_tokens"):
        op.drop_column("api_keys", "max_monthly_tokens")
    if _col_exists("users", "quota_reset_at"):
        op.drop_column("users", "quota_reset_at")
    if _col_exists("users", "cost_used_this_month"):
        op.drop_column("users", "cost_used_this_month")
    if _col_exists("users", "cost_monthly_limit"):
        op.drop_column("users", "cost_monthly_limit")
    if _col_exists("users", "tokens_used_this_month"):
        op.drop_column("users", "tokens_used_this_month")
    if _col_exists("users", "token_monthly_allowance"):
        op.drop_column("users", "token_monthly_allowance")
