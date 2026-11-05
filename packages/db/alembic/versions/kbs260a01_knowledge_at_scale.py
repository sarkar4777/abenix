"""Resumable ingest, dedupe and per collection search settings, existing collections keep english.

Revision ID: kbs260a01
Revises: kbops260a01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "kbs260a01"
down_revision = "kbops260a01"
branch_labels = None
depends_on = None


def _insp():
    return sa.inspect(op.get_bind())


def _add_column(table: str, col: sa.Column) -> bool:
    if col.name in {c["name"] for c in _insp().get_columns(table)}:
        return False
    op.add_column(table, col)
    return True


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    _add_column("documents", sa.Column("content_sha256", sa.String(64), nullable=True))
    _add_column(
        "documents",
        sa.Column(
            "ingest_checkpoint", sa.Integer(), server_default="0", nullable=False
        ),
    )
    _add_column(
        "documents",
        sa.Column("ingest_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    _add_column(
        "documents", sa.Column("ingest_fingerprint", sa.String(200), nullable=True)
    )
    # 2 GB is past a 32 bit column, and the upload limit is now well above that
    op.execute(
        "DO $$ BEGIN IF (SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'documents' "
        "AND column_name = 'file_size') <> 'bigint' THEN "
        "ALTER TABLE documents ALTER COLUMN file_size TYPE BIGINT; END IF; END $$"
    )
    _create_index("ix_documents_kb_created", "documents", ["kb_id", "created_at"])
    _create_index(
        "ix_documents_kb_superseded",
        "documents",
        ["kb_id"],
        postgresql_where=sa.text("is_current IS FALSE"),
    )
    _create_index(
        "ux_documents_kb_sha256",
        "documents",
        ["kb_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text("content_sha256 IS NOT NULL AND is_current IS TRUE"),
    )

    _add_column(
        "knowledge_collections",
        sa.Column("index_mode", sa.String(20), server_default="shared", nullable=False),
    )
    _add_column(
        "knowledge_collections",
        sa.Column("rerank_mode", sa.String(10), server_default="auto", nullable=False),
    )
    if _add_column(
        "knowledge_collections",
        sa.Column(
            "search_language", sa.String(32), server_default="simple", nullable=False
        ),
    ):
        op.execute("UPDATE knowledge_collections SET search_language = 'english'")

    # the API creates chunks on start, so on some upgrades it does not exist yet
    op.execute(
        "DO $$ BEGIN IF to_regclass('chunks') IS NOT NULL THEN "
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS "
        "dedicated_index BOOLEAN NOT NULL DEFAULT FALSE; END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF to_regclass('chunks') IS NOT NULL AND EXISTS (SELECT 1 FROM "
        "pg_class WHERE oid = to_regclass('chunks') AND relkind = 'r') THEN "
        "ALTER TABLE chunks DROP COLUMN IF EXISTS dedicated_index; END IF; END $$"
    )
    for name in ("ux_documents_kb_sha256", "ix_documents_kb_superseded"):
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("DROP INDEX IF EXISTS ix_documents_kb_created")
    for col in ("index_mode", "search_language", "rerank_mode"):
        op.execute(f"ALTER TABLE knowledge_collections DROP COLUMN IF EXISTS {col}")
    for col in (
        "content_sha256",
        "ingest_checkpoint",
        "ingest_attempts",
        "ingest_fingerprint",
    ):
        op.execute(f"ALTER TABLE documents DROP COLUMN IF EXISTS {col}")
