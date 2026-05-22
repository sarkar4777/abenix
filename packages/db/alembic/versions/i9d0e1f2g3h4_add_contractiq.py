"""Add ContractIQ tables for PPA & Gas Contract Intelligence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "i9d0e1f2g3h4"
down_revision = "h8c9d0e1f2g3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    contractiq_user_role = sa.Enum(
        "admin", "analyst", "viewer", name="contractiq_user_role"
    )
    contract_type = sa.Enum("ppa", "gas", "tolling", "vppa", name="contract_type")
    contract_status = sa.Enum(
        "uploaded", "extracting", "analyzed", "error", name="contract_status"
    )
    clause_type = sa.Enum(
        "termination",
        "force_majeure",
        "pricing",
        "payment",
        "performance_guarantee",
        "curtailment",
        "change_of_law",
        "insurance",
        "indemnity",
        "dispute_resolution",
        "assignment",
        "confidentiality",
        "other",
        name="clause_type",
    )
    risk_level = sa.Enum("low", "medium", "high", "critical", name="risk_level")

    # Users
    op.create_table(
        "contractiq_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("organization", sa.String(255), nullable=True),
        sa.Column("role", contractiq_user_role, default="analyst"),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("api_key_hash", sa.String(255), nullable=True),
        sa.Column("api_key_prefix", sa.String(20), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Contracts
    op.create_table(
        "contractiq_contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_users.id"),
            nullable=False,
        ),
        sa.Column("contract_type", contract_type, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("counterparty_a", sa.String(255), nullable=True),
        sa.Column("counterparty_b", sa.String(255), nullable=True),
        sa.Column("execution_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", contract_status, default="uploaded"),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("file_uri", sa.String(1000), nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("extraction_summary", JSONB, nullable=True),
        sa.Column("risk_score", sa.Float, nullable=True),
        sa.Column("total_capacity_mw", sa.Float, nullable=True),
        sa.Column("contract_value", sa.Numeric(15, 2), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_contractiq_contracts_user", "contractiq_contracts", ["user_id"])
    op.create_index(
        "ix_contractiq_contracts_type", "contractiq_contracts", ["contract_type"]
    )

    # Extracted Data
    op.create_table(
        "contractiq_extracted_data",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section", sa.String(100), nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("field_value", sa.Text, nullable=False),
        sa.Column("field_type", sa.String(50), default="string"),
        sa.Column("confidence_score", sa.Float, nullable=True),
        sa.Column("page_reference", sa.String(50), nullable=True),
        sa.Column("extraction_pass", sa.Integer, default=1),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_contractiq_extracted_contract",
        "contractiq_extracted_data",
        ["contract_id", "section"],
    )

    # Clauses
    op.create_table(
        "contractiq_clauses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clause_number", sa.String(50), nullable=True),
        sa.Column("clause_title", sa.String(500), nullable=False),
        sa.Column("clause_text", sa.Text, nullable=False),
        sa.Column("clause_type", clause_type, default="other"),
        sa.Column("risk_level", risk_level, default="low"),
        sa.Column("risk_notes", sa.Text, nullable=True),
        sa.Column("key_dates", JSONB, nullable=True),
        sa.Column("key_amounts", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_contractiq_clauses_contract", "contractiq_clauses", ["contract_id"]
    )
    op.create_index("ix_contractiq_clauses_type", "contractiq_clauses", ["clause_type"])

    # Assets
    op.create_table(
        "contractiq_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_name", sa.String(500), nullable=False),
        sa.Column("asset_type", sa.String(100), nullable=False),
        sa.Column("capacity_mw", sa.Float, nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("coordinates", sa.String(100), nullable=True),
        sa.Column("cod_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("technology", sa.String(255), nullable=True),
        sa.Column("degradation_rate", sa.Float, nullable=True),
        sa.Column("interconnection_point", sa.String(255), nullable=True),
        sa.Column("metering_point", sa.String(255), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Events
    op.create_table(
        "contractiq_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("is_recurring", sa.Boolean, default=False),
        sa.Column("notification_days_before", sa.Integer, nullable=True),
        sa.Column("status", sa.String(50), default="upcoming"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Risk Analyses
    op.create_table(
        "contractiq_risk_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "contract_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_contracts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("risk_category", sa.String(100), nullable=False),
        sa.Column("risk_score", sa.Float, default=0),
        sa.Column("risk_description", sa.Text, nullable=False),
        sa.Column("mitigation_suggestion", sa.Text, nullable=True),
        sa.Column("market_data_used", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # Comparisons
    op.create_table(
        "contractiq_comparisons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("contractiq_users.id"),
            nullable=False,
        ),
        sa.Column("contract_ids", JSONB, nullable=False),
        sa.Column("comparison_type", sa.String(50), nullable=False),
        sa.Column("results", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("contractiq_comparisons")
    op.drop_table("contractiq_risk_analyses")
    op.drop_table("contractiq_events")
    op.drop_table("contractiq_assets")
    op.drop_table("contractiq_clauses")
    op.drop_table("contractiq_extracted_data")
    op.drop_table("contractiq_contracts")
    op.drop_table("contractiq_users")
    op.execute("DROP TYPE IF EXISTS contractiq_user_role")
    op.execute("DROP TYPE IF EXISTS contract_type")
    op.execute("DROP TYPE IF EXISTS contract_status")
    op.execute("DROP TYPE IF EXISTS clause_type")
    op.execute("DROP TYPE IF EXISTS risk_level")
