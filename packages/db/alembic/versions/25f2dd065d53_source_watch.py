"""Source Watch: watched sources, immutable snapshots and detected changes.

Revision ID: 25f2dd065d53
Revises: 20a44346bdda
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "25f2dd065d53"
down_revision = "20a44346bdda"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


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


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
    )


def upgrade() -> None:
    _create_table(
        "watch_sources",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="html"),
        sa.Column(
            "cadence_minutes", sa.Integer(), nullable=False, server_default="1440"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("credentials_key", sa.String(128), nullable=True),
        sa.Column("headers", _JSONB, nullable=False, server_default="{}"),
        sa.Column("selector", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(64), nullable=True),
        sa.Column("tags", _JSONB, nullable=False, server_default="[]"),
        sa.Column("risk_tier", sa.String(16), nullable=False, server_default="low"),
        sa.Column(
            "ingest_to_kb",
            _UUID,
            sa.ForeignKey("knowledge_collections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kb_document_id", _UUID, nullable=True),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("next_check_at", nullable=True),
        _ts("last_checked_at", nullable=True),
        _ts("last_changed_at", nullable=True),
        sa.Column("last_status", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("etag", sa.String(512), nullable=True),
        sa.Column("last_modified", sa.String(128), nullable=True),
        sa.Column("current_snapshot_id", _UUID, nullable=True),
        sa.Column("check_count", sa.Integer(), nullable=False, server_default="0"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_watch_source_name"),
    )
    _create_index(
        "ix_watch_sources_due",
        "watch_sources",
        ["next_check_at"],
        postgresql_where=sa.text("active"),
    )

    _create_table(
        "source_snapshots",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "source_id",
            _UUID,
            sa.ForeignKey("watch_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False, server_default=""),
        sa.Column("bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("http_status", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("http_headers", _JSONB, nullable=False, server_default="{}"),
        _ts("fetched_at"),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("normalized_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("normalized_text_key", sa.String(512), nullable=True),
        sa.Column(
            "text_truncated", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("tables", _JSONB, nullable=True),
        sa.Column("notes", _JSONB, nullable=False, server_default="[]"),
        sa.UniqueConstraint(
            "source_id", "content_sha256", name="uq_source_snapshot_sha"
        ),
    )
    _create_index(
        "ix_source_snapshots_source_fetched",
        "source_snapshots",
        ["source_id", "fetched_at"],
    )

    _create_table(
        "source_changes",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "source_id",
            _UUID,
            sa.ForeignKey("watch_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_snapshot_id",
            _UUID,
            sa.ForeignKey("source_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_snapshot_id",
            _UUID,
            sa.ForeignKey("source_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _ts("detected_at"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("diff", _JSONB, nullable=False, server_default="{}"),
        sa.Column("stats", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "materiality_hint", sa.String(16), nullable=False, server_default="low"
        ),
    )
    _create_index(
        "ix_source_changes_source_detected",
        "source_changes",
        ["source_id", "detected_at"],
    )
    _create_index(
        "ix_source_changes_tenant_detected",
        "source_changes",
        ["tenant_id", "detected_at"],
    )

    # snapshots are evidence, so a stored one never changes
    op.execute(
        """
        CREATE OR REPLACE FUNCTION source_snapshots_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'source snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS source_snapshots_immutable ON source_snapshots")
    op.execute(
        "CREATE TRIGGER source_snapshots_immutable BEFORE UPDATE ON source_snapshots "
        "FOR EACH ROW EXECUTE FUNCTION source_snapshots_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS source_snapshots_immutable ON source_snapshots")
    op.execute("DROP FUNCTION IF EXISTS source_snapshots_immutable()")
    op.drop_table("source_changes")
    op.drop_table("source_snapshots")
    op.drop_table("watch_sources")
