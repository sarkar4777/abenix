"""Edge runtime gateways — registry of remote pods that pull `.agent` bundles."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "1100_e_edge"
down_revision = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table("edge_gateways"):
        return

    op.create_table(
        "edge_gateways",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("gateway_id", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "endpoint_url",
            sa.String(500),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="online",
        ),
        sa.Column(
            "deployed_agents",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_edge_gateways_tenant",
        "edge_gateways",
        ["tenant_id", "registered_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_edge_gateways_tenant", table_name="edge_gateways")
    op.drop_table("edge_gateways")
