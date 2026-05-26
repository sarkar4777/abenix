"""v2.0 — knowledge / atlas / persona uplift.

Adds the columns and tables that back the 16 enterprise gaps closed in
v2.0:

  - document-level ACL (document_grants)
  - document versioning (parent_document_id, version_number, is_current,
    superseded_by)
  - incremental cognify (documents.cognified_at, .last_cognify_job_id)
  - cognify config + conflict tracking (cognify_configs, cognify_conflicts)
  - GDPR cascade (deleted_at / deleted_by on persona_items + memories,
    gdpr_purge_log)
  - persona encryption flag (persona_items.value_encrypted,
    .key_version)
  - bi-temporal atlas (valid_from / valid_to / recorded_at /
    source_anchor on atlas_nodes + atlas_edges)
  - ocr metadata on documents (extraction_method, extraction_quality)

Revision ID: b8c9d0e1f2g3
Revises: a7b8c9d0e1f2
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "b8c9d0e1f2g3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # documents — versioning + incremental cognify + ocr metadata
    op.add_column(
        "documents",
        sa.Column(
            "parent_document_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "documents",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "documents",
        sa.Column(
            "superseded_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "documents",
        sa.Column("cognified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "last_cognify_job_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("extraction_method", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("extraction_quality", sa.Float(), nullable=True),
    )
    op.create_index("ix_documents_is_current", "documents", ["is_current"])
    op.create_index(
        "ix_documents_kb_cognified",
        "documents",
        ["kb_id", "cognified_at"],
    )

    # document_grants — per-document ACL
    op.create_table(
        "document_grants",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column(
            "subject_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "permission", sa.String(length=16), nullable=False, server_default="read"
        ),
        sa.Column(
            "granted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_id",
            "permission",
            name="uq_document_grant",
        ),
    )
    op.create_index(
        "ix_document_grants_subject", "document_grants", ["subject_type", "subject_id"]
    )
    op.create_index("ix_document_grants_tenant", "document_grants", ["tenant_id"])

    # cognify_configs — per-tenant
    op.create_table(
        "cognify_configs",
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "auto_accept_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.85",
        ),
        sa.Column(
            "conflict_action",
            sa.String(length=16),
            nullable=False,
            server_default="flag",
        ),
        sa.Column(
            "max_parallel_docs",
            sa.Integer(),
            nullable=False,
            server_default="8",
        ),
        sa.Column(
            "daily_budget_usd",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # cognify_conflicts — surfaces source disagreements
    op.create_table(
        "cognify_conflicts",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "knowledge_base_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("entity_canonical_name", sa.String(length=512), nullable=False),
        sa.Column("property_name", sa.String(length=128), nullable=False),
        sa.Column(
            "source_a_doc_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_a_value", sa.Text(), nullable=False),
        sa.Column("source_a_confidence", sa.Float(), nullable=False),
        sa.Column(
            "source_b_doc_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_b_value", sa.Text(), nullable=False),
        sa.Column("source_b_confidence", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="open"
        ),
        sa.Column("resolved_value", sa.Text(), nullable=True),
        sa.Column(
            "resolved_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_cognify_conflicts_open",
        "cognify_conflicts",
        ["tenant_id", "status"],
    )

    # gdpr_purge_log — every step of a cascade delete is auditable
    op.create_table(
        "gdpr_purge_log",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "subject_user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "requested_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("store", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_gdpr_purge_subject",
        "gdpr_purge_log",
        ["subject_user_id", "store"],
    )

    # persona_items — soft-delete + encryption metadata
    op.add_column(
        "persona_items",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "persona_items",
        sa.Column(
            "deleted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "persona_items",
        sa.Column("encrypted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "persona_items",
        sa.Column("key_version", sa.Integer(), nullable=True),
    )
    op.create_index("ix_persona_items_not_deleted", "persona_items", ["deleted_at"])

    # agent_memories — soft-delete
    op.add_column(
        "agent_memories",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_memories",
        sa.Column(
            "deleted_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
        ),
    )

    # atlas_nodes — bi-temporal + provenance
    op.add_column(
        "atlas_nodes",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "atlas_nodes",
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "atlas_nodes",
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "atlas_nodes",
        sa.Column("source_anchors", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_atlas_nodes_validity",
        "atlas_nodes",
        ["valid_from", "valid_to"],
    )

    # atlas_edges — bi-temporal + provenance
    op.add_column(
        "atlas_edges",
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "atlas_edges",
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "atlas_edges",
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "atlas_edges",
        sa.Column("source_anchors", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_atlas_edges_validity",
        "atlas_edges",
        ["valid_from", "valid_to"],
    )


def downgrade() -> None:
    op.drop_index("ix_atlas_edges_validity", table_name="atlas_edges")
    op.drop_column("atlas_edges", "source_anchors")
    op.drop_column("atlas_edges", "recorded_at")
    op.drop_column("atlas_edges", "valid_to")
    op.drop_column("atlas_edges", "valid_from")
    op.drop_index("ix_atlas_nodes_validity", table_name="atlas_nodes")
    op.drop_column("atlas_nodes", "source_anchors")
    op.drop_column("atlas_nodes", "recorded_at")
    op.drop_column("atlas_nodes", "valid_to")
    op.drop_column("atlas_nodes", "valid_from")
    op.drop_column("agent_memories", "deleted_by")
    op.drop_column("agent_memories", "deleted_at")
    op.drop_index("ix_persona_items_not_deleted", table_name="persona_items")
    op.drop_column("persona_items", "key_version")
    op.drop_column("persona_items", "encrypted")
    op.drop_column("persona_items", "deleted_by")
    op.drop_column("persona_items", "deleted_at")
    op.drop_index("ix_gdpr_purge_subject", table_name="gdpr_purge_log")
    op.drop_table("gdpr_purge_log")
    op.drop_index("ix_cognify_conflicts_open", table_name="cognify_conflicts")
    op.drop_table("cognify_conflicts")
    op.drop_table("cognify_configs")
    op.drop_index("ix_document_grants_tenant", table_name="document_grants")
    op.drop_index("ix_document_grants_subject", table_name="document_grants")
    op.drop_table("document_grants")
    op.drop_index("ix_documents_kb_cognified", table_name="documents")
    op.drop_index("ix_documents_is_current", table_name="documents")
    op.drop_column("documents", "extraction_quality")
    op.drop_column("documents", "extraction_method")
    op.drop_column("documents", "last_cognify_job_id")
    op.drop_column("documents", "cognified_at")
    op.drop_column("documents", "superseded_by")
    op.drop_column("documents", "is_current")
    op.drop_column("documents", "version_number")
    op.drop_column("documents", "parent_document_id")
