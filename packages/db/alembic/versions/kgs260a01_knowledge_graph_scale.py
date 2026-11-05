"""Cognify progress tables, Atlas diff snapshots, graph mirror uniqueness.

Revision ID: kgs260a01
Revises: kbs260a01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "kgs260a01"
down_revision = "kbs260a01"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


# The API's startup create_all can build new tables before this runs, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _create_table(name: str, *cols, **kw) -> None:
    if not _insp().has_table(name):
        op.create_table(name, *cols, **kw)


def _add_column(table: str, col: sa.Column) -> None:
    if col.name not in {c["name"] for c in _insp().get_columns(table)}:
        op.add_column(table, col)


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE cognify_status ADD VALUE IF NOT EXISTS 'STOPPED'")

    for name in (
        "documents_total",
        "chunks_total",
        "chunks_processed",
        "chunks_skipped",
        "chunks_failed",
        "entities_written",
        "entities_failed",
        "relationships_written",
        "relationships_failed",
        "off_ontology_dropped",
    ):
        _add_column(
            "cognify_jobs",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    _add_column("cognify_jobs", sa.Column("budget_usd", sa.Numeric(12, 4)))
    _add_column(
        "cognify_jobs",
        sa.Column(
            "stop_requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    _add_column("cognify_jobs", sa.Column("stop_reason", sa.String(40)))
    _add_column("cognify_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    _add_column("cognify_jobs", sa.Column("details", postgresql.JSONB()))

    _create_table(
        "cognify_job_documents",
        sa.Column(
            "job_id",
            _UUID,
            sa.ForeignKey("cognify_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document_id", _UUID, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("chunks_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chunks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _create_index(
        "ix_cognify_job_documents_status",
        "cognify_job_documents",
        ["job_id", "status"],
    )

    _create_table(
        "cognify_chunks",
        sa.Column(
            "kb_id",
            _UUID,
            sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document_id", _UUID, primary_key=True),
        sa.Column("chunk_hash", sa.String(64), primary_key=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="done"),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("job_id", _UUID),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _create_index(
        "ix_cognify_chunks_pending",
        "cognify_chunks",
        ["kb_id", "document_id"],
        postgresql_where=sa.text("status = 'extracted'"),
    )

    _add_column("graph_entities", sa.Column("atlas_concept_id", _UUID))
    _add_column("graph_entities", sa.Column("atlas_graph_id", _UUID))
    _add_column("graph_relationships", sa.Column("atlas_edge_id", _UUID))
    _create_index(
        "ix_graph_entities_kb_concept",
        "graph_entities",
        ["kb_id", "atlas_concept_id"],
    )
    # reruns used to add a row per run, the newest row wins and the rest go
    op.execute(
        """
        DELETE FROM graph_relationships a USING graph_relationships b
        WHERE a.kb_id = b.kb_id
          AND a.source_entity_id = b.source_entity_id
          AND a.target_entity_id = b.target_entity_id
          AND a.relationship_type = b.relationship_type
          AND a.ctid < b.ctid
        """
    )
    _create_index(
        "uq_graph_rels_triple",
        "graph_relationships",
        ["kb_id", "source_entity_id", "target_entity_id", "relationship_type"],
        unique=True,
    )

    _create_index(
        "ix_atlas_nodes_graph_position",
        "atlas_nodes",
        ["graph_id", "position_x", "position_y"],
    )
    _create_index(
        "ix_atlas_nodes_graph_updated", "atlas_nodes", ["graph_id", "updated_at"]
    )
    _create_index(
        "ix_atlas_nodes_graph_document", "atlas_nodes", ["graph_id", "document_id"]
    )
    _create_index(
        "ix_atlas_nodes_graph_created", "atlas_nodes", ["graph_id", "created_at", "id"]
    )
    _create_index(
        "ix_atlas_edges_graph_updated", "atlas_edges", ["graph_id", "updated_at"]
    )
    _create_table(
        "atlas_snapshot_rows",
        sa.Column(
            "graph_id",
            _UUID,
            sa.ForeignKey("atlas_graphs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(1), primary_key=True),
        sa.Column("row_id", _UUID, primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload", postgresql.JSONB()),
    )

    # best effort, a role that may not create extensions keeps a slower search
    bind = op.get_bind()
    try:
        with bind.begin_nested():
            bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            bind.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_atlas_nodes_label_trgm ON atlas_nodes "
                "USING gin (lower(label) gin_trgm_ops)"
            )
    except Exception:  # noqa: BLE001
        pass


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_atlas_nodes_label_trgm")
    op.drop_table("atlas_snapshot_rows")
    op.drop_index("uq_graph_rels_triple", table_name="graph_relationships")
    op.drop_index("ix_graph_entities_kb_concept", table_name="graph_entities")
    op.drop_column("graph_relationships", "atlas_edge_id")
    op.drop_column("graph_entities", "atlas_graph_id")
    op.drop_column("graph_entities", "atlas_concept_id")
    op.drop_table("cognify_chunks")
    op.drop_table("cognify_job_documents")
    for name in (
        "details",
        "heartbeat_at",
        "stop_reason",
        "stop_requested",
        "budget_usd",
        "off_ontology_dropped",
        "relationships_failed",
        "relationships_written",
        "entities_failed",
        "entities_written",
        "chunks_failed",
        "chunks_skipped",
        "chunks_processed",
        "chunks_total",
        "documents_total",
    ):
        op.drop_column("cognify_jobs", name)
