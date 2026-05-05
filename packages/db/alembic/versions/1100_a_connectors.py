"""Add connectors table.

The connector framework is the storage primitive behind the v1.1.0
connector_call tool — agents pick a registered connector by ID, and the
tool routes through the connector's preset operation set (CMMS, HRIS,
telematics, standards, custom). Secrets stay in the platform's secret
store; only a `secret_ref` UUID lives in this row.

Idempotent: every CREATE is information_schema-guarded so a second
`alembic upgrade head` is a no-op.

Revision ID: 1100_a_connectors
Revises: 1100_e_edge
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "1100_a_connectors"
down_revision = "1100_e_edge"
branch_labels = None
depends_on = None

# Keep these aligned with packages/db/models/connector.py — the model
# is the source of truth, the enum here just mirrors it.
_KINDS = ("cmms", "hris", "telematics", "standards", "weather", "cost_data", "custom")
_AUTH_TYPES = ("none", "api_key", "bearer", "basic", "oauth2")


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :n AND table_schema = current_schema()"
        ),
        {"n": name},
    ).first()
    return row is not None


def _enum_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _enum_exists("connector_kind"):
        op.execute(
            "CREATE TYPE connector_kind AS ENUM "
            "(" + ", ".join(f"'{k}'" for k in _KINDS) + ")"
        )
    if not _enum_exists("connector_auth_type"):
        op.execute(
            "CREATE TYPE connector_auth_type AS ENUM "
            "(" + ", ".join(f"'{k}'" for k in _AUTH_TYPES) + ")"
        )

    if _table_exists("connectors"):
        return

    op.create_table(
        "connectors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                *_KINDS, name="connector_kind", native_enum=True, create_type=False
            ),
            nullable=False,
        ),
        sa.Column("preset_key", sa.String(128), nullable=True),
        sa.Column("base_url", sa.String(1000), nullable=False),
        sa.Column(
            "auth_type",
            sa.Enum(
                *_AUTH_TYPES,
                name="connector_auth_type",
                native_enum=True,
                create_type=False,
            ),
            nullable=False,
            server_default="none",
        ),
        # Pointer at the platform secret store row. Plain UUID; not a FK
        # because the secret table lives elsewhere in some deployments.
        sa.Column("secret_ref", UUID(as_uuid=True), nullable=True),
        sa.Column("config", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean, nullable=True),
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
    op.create_index("ix_connectors_kind", "connectors", ["kind"])
    op.create_index(
        "ix_connectors_tenant_name",
        "connectors",
        ["tenant_id", "name"],
        unique=True,
    )


def downgrade() -> None:
    if _table_exists("connectors"):
        op.drop_index("ix_connectors_tenant_name", table_name="connectors")
        op.drop_index("ix_connectors_kind", table_name="connectors")
        op.drop_table("connectors")
    op.execute("DROP TYPE IF EXISTS connector_auth_type")
    op.execute("DROP TYPE IF EXISTS connector_kind")
