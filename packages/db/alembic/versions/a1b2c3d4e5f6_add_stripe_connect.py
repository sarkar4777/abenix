"""add stripe connect and revenue sharing"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a1b2c3d4e5f6"
down_revision = "05ce612575be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'PENDING_REVIEW'")
    op.execute("ALTER TYPE agent_status ADD VALUE IF NOT EXISTS 'REJECTED'")

    op.add_column(
        "users", sa.Column("stripe_connect_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "stripe_connect_onboarded",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )

    op.add_column("agents", sa.Column("rejection_reason", sa.Text(), nullable=True))

    op.add_column(
        "subscriptions",
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
    )

    op.create_table(
        "payouts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "creator_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("stripe_transfer_id", sa.String(255), nullable=True),
        sa.Column("stripe_charge_id", sa.String(255), nullable=True),
        sa.Column("amount_total", sa.Numeric(10, 2), nullable=False),
        sa.Column("platform_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("creator_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="usd", nullable=False),
        sa.Column("status", sa.String(50), server_default="pending", nullable=False),
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
    op.create_index("ix_payouts_creator", "payouts", ["creator_id", "created_at"])
    op.create_index("ix_payouts_subscription", "payouts", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_payouts_subscription", table_name="payouts")
    op.drop_index("ix_payouts_creator", table_name="payouts")
    op.drop_table("payouts")

    op.drop_column("subscriptions", "stripe_payment_intent_id")
    op.drop_column("agents", "rejection_reason")
    op.drop_column("users", "stripe_connect_onboarded")
    op.drop_column("users", "stripe_connect_id")
