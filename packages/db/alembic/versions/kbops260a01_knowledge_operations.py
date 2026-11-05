"""Knowledge operations, tombstones, generations, quotas and connectors.

Revision ID: kbops260a01
Revises: fix259a01
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "kbops260a01"
down_revision = "fix259a01"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()
_TZ = sa.DateTime(timezone=True)


# The API's startup create_all can build new tables before this runs, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _plain_chunks() -> bool:
    """A partitioned chunks table was built with these columns and its own keys."""
    kind = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relkind::text FROM pg_class WHERE oid = to_regclass('chunks')"
            )
        )
        .scalar()
    )
    return kind == "r"


def _create_table(name: str, *cols, **kw) -> None:
    if not _insp().has_table(name):
        op.create_table(name, *cols, **kw)


def _add_column(table: str, col: sa.Column) -> None:
    if col.name not in {c["name"] for c in _insp().get_columns(table)}:
        op.add_column(table, col)


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", _TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TZ, server_default=sa.func.now(), nullable=False),
    ]


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False)


def _count(name: str, kind: sa.types.TypeEngine = sa.BigInteger()) -> sa.Column:
    return sa.Column(name, kind, nullable=False, server_default="0")


def upgrade() -> None:
    _add_column("knowledge_collections", sa.Column("deleted_at", _TZ, nullable=True))
    _add_column(
        "knowledge_collections",
        sa.Column(
            "embedding_generation", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    _add_column("documents", sa.Column("uploaded_by", _UUID, nullable=True))
    _create_index("ix_documents_uploaded_by", "documents", ["uploaded_by"])

    _create_table(
        "kb_reembed_jobs",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "kb_id",
            _UUID,
            sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_model", sa.String(120), nullable=True),
        sa.Column("to_model", sa.String(120), nullable=False),
        sa.Column("backend", sa.String(20), nullable=False),
        sa.Column("from_generation", sa.Integer(), nullable=False),
        sa.Column("target_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        _count("documents_total", sa.Integer()),
        _count("documents_done", sa.Integer()),
        _count("chunks_done"),
        _count("from_file", sa.Integer()),
        _count("from_indexed_text", sa.Integer()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", _UUID, nullable=True),
        sa.Column("heartbeat_at", _TZ, nullable=True),
        sa.Column("started_at", _TZ, nullable=True),
        sa.Column("flipped_at", _TZ, nullable=True),
        sa.Column("finished_at", _TZ, nullable=True),
        *_stamps(),
    )
    _create_index("ix_kb_reembed_jobs_tenant_id", "kb_reembed_jobs", ["tenant_id"])
    _create_index("ix_kb_reembed_jobs_kb_id", "kb_reembed_jobs", ["kb_id"])
    _create_index("ix_kb_reembed_jobs_status", "kb_reembed_jobs", ["status"])
    _create_index(
        "uq_kb_reembed_live",
        "kb_reembed_jobs",
        ["kb_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('queued','running','pausing','paused','flipping','cleaning')"
        ),
    )
    _create_table(
        "kb_reembed_documents",
        sa.Column(
            "job_id",
            _UUID,
            sa.ForeignKey("kb_reembed_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            _UUID,
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _count("chunk_count", sa.Integer()),
        sa.Column("source", sa.String(16), nullable=False, server_default="file"),
        sa.Column("done_at", _TZ, server_default=sa.func.now(), nullable=False),
    )
    _create_table(
        "kb_delete_jobs",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column("kb_id", _UUID, nullable=False),
        sa.Column("kb_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False, server_default="queued"),
        _count("documents_deleted", sa.Integer()),
        _count("chunks_deleted"),
        _count("files_deleted", sa.Integer()),
        _count("entities_deleted", sa.Integer()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("requested_by", _UUID, nullable=True),
        sa.Column("heartbeat_at", _TZ, nullable=True),
        sa.Column("finished_at", _TZ, nullable=True),
        *_stamps(),
    )
    _create_index("ix_kb_delete_jobs_tenant_id", "kb_delete_jobs", ["tenant_id"])
    _create_index("ix_kb_delete_jobs_kb_id", "kb_delete_jobs", ["kb_id"])
    _create_index("ix_kb_delete_jobs_status", "kb_delete_jobs", ["status"])
    _create_table(
        "tenant_knowledge_quotas",
        sa.Column(
            "tenant_id",
            _UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("max_documents", sa.BigInteger(), nullable=True),
        sa.Column("max_chunks", sa.BigInteger(), nullable=True),
        sa.Column("max_storage_bytes", sa.BigInteger(), nullable=True),
        sa.Column("monthly_embedding_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("monthly_cognify_usd", sa.Numeric(12, 4), nullable=True),
        sa.Column("updated_at", _TZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", _UUID, nullable=True),
    )
    _create_table(
        "knowledge_spend",
        sa.Column(
            "tenant_id",
            _UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("period", _TZ, primary_key=True),
        _count("embedding_usd", sa.Numeric(14, 6)),
        _count("embedding_tokens"),
        _count("cognify_usd", sa.Numeric(14, 6)),
        sa.Column("updated_at", _TZ, server_default=sa.func.now(), nullable=False),
    )
    _create_table(
        "kb_connector_sources",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "kb_id",
            _UUID,
            sa.ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config", _JSONB, nullable=False, server_default="{}"),
        sa.Column("credential_key", sa.String(128), nullable=True),
        sa.Column(
            "cadence_minutes", sa.Integer(), nullable=False, server_default="1440"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(24), nullable=False, server_default="idle"),
        sa.Column("run_id", _UUID, nullable=True),
        sa.Column("page_cursor", _JSONB, nullable=True),
        sa.Column("sync_cursor", _JSONB, nullable=True),
        sa.Column("next_sync_at", _TZ, nullable=True),
        sa.Column("last_started_at", _TZ, nullable=True),
        sa.Column("last_finished_at", _TZ, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        _count("consecutive_failures", sa.Integer()),
        sa.Column("heartbeat_at", _TZ, nullable=True),
        _count("items_seen"),
        _count("items_ingested"),
        _count("items_updated"),
        _count("items_deleted"),
        _count("items_failed"),
        _count("items_skipped"),
        sa.Column(
            "confirm_deletes", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("created_by", _UUID, nullable=True),
        *_stamps(),
    )
    _create_index(
        "ix_kb_connector_sources_tenant_id", "kb_connector_sources", ["tenant_id"]
    )
    _create_index("ix_kb_connector_sources_kb_id", "kb_connector_sources", ["kb_id"])
    _create_index(
        "ix_kb_connector_due", "kb_connector_sources", ["active", "next_sync_at"]
    )
    _create_table(
        "kb_connector_items",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "source_id",
            _UUID,
            sa.ForeignKey("kb_connector_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.String(500), nullable=False, server_default=""),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column(
            "document_id",
            _UUID,
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("modified_at", _TZ, nullable=True),
        sa.Column("acl", _JSONB, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        _count("failures", sa.Integer()),
        sa.Column("last_seen_run", _UUID, nullable=True),
        sa.Column("updated_at", _TZ, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_kb_connector_item"),
    )
    _create_index(
        "ix_kb_connector_items_run",
        "kb_connector_items",
        ["source_id", "last_seen_run"],
    )
    _create_index(
        "ix_kb_connector_items_document", "kb_connector_items", ["document_id"]
    )

    # chunks is raw SQL and may not exist yet, API startup builds it with these columns
    if _plain_chunks():
        op.execute(
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
            "embedding_generation INTEGER NOT NULL DEFAULT 0"
        )
        # concurrent so ingest keeps running while a large table builds them
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                "uq_chunks_doc_index_generation "
                "ON chunks (document_id, chunk_index, embedding_generation)"
            )
            op.execute(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "ix_chunks_collection_generation "
                "ON chunks (collection_id, embedding_generation)"
            )
        op.execute(
            "ALTER TABLE chunks DROP CONSTRAINT IF EXISTS "
            "chunks_document_id_chunk_index_key"
        )


def downgrade() -> None:
    if _plain_chunks():
        # old generations are not kept, the old unique key cannot hold them
        op.execute(
            "DELETE FROM chunks c USING knowledge_collections k "
            "WHERE k.id = c.collection_id "
            "AND c.embedding_generation <> k.embedding_generation"
        )
        op.execute(
            "ALTER TABLE chunks ADD CONSTRAINT chunks_document_id_chunk_index_key "
            "UNIQUE (document_id, chunk_index)"
        )
        op.execute("DROP INDEX IF EXISTS uq_chunks_doc_index_generation")
        op.execute("DROP INDEX IF EXISTS ix_chunks_collection_generation")
        op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding_generation")
    for table in (
        "kb_connector_items",
        "kb_connector_sources",
        "knowledge_spend",
        "tenant_knowledge_quotas",
        "kb_delete_jobs",
        "kb_reembed_documents",
        "kb_reembed_jobs",
    ):
        op.drop_table(table)
    op.drop_index("ix_documents_uploaded_by", table_name="documents")
    op.drop_column("documents", "uploaded_by")
    op.drop_column("knowledge_collections", "embedding_generation")
    op.drop_column("knowledge_collections", "deleted_at")
