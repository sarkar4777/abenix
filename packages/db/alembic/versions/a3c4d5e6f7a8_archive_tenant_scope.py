"""Tenant-scope the archive tables and widen the tenant Slack webhook column.

archive_runs and retention_policies had no tenant_id, so any tenant admin
could archive, delete and download every tenant's rows. retention_policies
moves to a (tenant_id, source_table) primary key. Existing global policy
rows are reassigned to the oldest tenant, or dropped when there is none.

tenants.slack_webhook_url becomes TEXT so the encrypted form fits.

Both tables were historically created by Base.metadata.create_all at API
startup, so they are materialised here when absent.

Revision ID: a3c4d5e6f7a8
Revises: f2a3b4c5d6e7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "a3c4d5e6f7a8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    op.execute("ALTER TABLE tenants ALTER COLUMN slack_webhook_url TYPE TEXT")

    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE archive_run_status AS ENUM "
        "('PENDING', 'RUNNING', 'COMPLETED', 'FAILED'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    if not insp.has_table("archive_runs"):
        op.create_table(
            "archive_runs",
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
                nullable=True,
            ),
            sa.Column("source_table", sa.String(64), nullable=False),
            sa.Column(
                "triggered_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
            ),
            sa.Column(
                "is_manual", sa.Boolean, nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "PENDING",
                    "RUNNING",
                    "COMPLETED",
                    "FAILED",
                    name="archive_run_status",
                    create_type=False,
                ),
                nullable=True,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rows_archived", sa.Integer, nullable=False, server_default="0"),
            sa.Column("rows_deleted", sa.Integer, nullable=False, server_default="0"),
            sa.Column("file_uri", sa.Text, nullable=True),
            sa.Column(
                "file_size_bytes", sa.BigInteger, nullable=True, server_default="0"
            ),
            sa.Column("file_sha256", sa.String(64), nullable=True),
            sa.Column("oldest_row_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("newest_row_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text, nullable=True),
            sa.Column("notes", sa.dialects.postgresql.JSONB, nullable=True),
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
        op.create_index(
            "ix_archive_runs_source_table", "archive_runs", ["source_table"]
        )
        op.create_index(
            "ix_archive_runs_source_started",
            "archive_runs",
            ["source_table", "started_at"],
        )
    elif not _has_column("archive_runs", "tenant_id"):
        op.add_column(
            "archive_runs",
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_archive_runs_tenant_id "
        "ON archive_runs (tenant_id)"
    )

    if not insp.has_table("retention_policies"):
        op.create_table(
            "retention_policies",
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("source_table", sa.String(64), primary_key=True),
            sa.Column(
                "retention_days", sa.Integer, nullable=False, server_default="30"
            ),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "updated_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True
            ),
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
    elif not _has_column("retention_policies", "tenant_id"):
        op.add_column(
            "retention_policies",
            sa.Column(
                "tenant_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.execute(
            "UPDATE retention_policies SET tenant_id = "
            "(SELECT id FROM tenants ORDER BY created_at ASC LIMIT 1) "
            "WHERE tenant_id IS NULL"
        )
        op.execute("DELETE FROM retention_policies WHERE tenant_id IS NULL")
        op.execute("ALTER TABLE retention_policies ALTER COLUMN tenant_id SET NOT NULL")
        op.execute(
            "ALTER TABLE retention_policies DROP CONSTRAINT IF EXISTS retention_policies_pkey"
        )
        op.execute(
            "ALTER TABLE retention_policies ADD PRIMARY KEY (tenant_id, source_table)"
        )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE retention_policies DROP CONSTRAINT IF EXISTS retention_policies_pkey"
    )
    op.execute(
        "DELETE FROM retention_policies a USING retention_policies b "
        "WHERE a.source_table = b.source_table AND a.tenant_id > b.tenant_id"
    )
    op.execute("ALTER TABLE retention_policies ADD PRIMARY KEY (source_table)")
    op.execute("ALTER TABLE retention_policies DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP INDEX IF EXISTS ix_archive_runs_tenant_id")
    op.execute("ALTER TABLE archive_runs DROP COLUMN IF EXISTS tenant_id")
    op.execute("ALTER TABLE tenants ALTER COLUMN slack_webhook_url TYPE VARCHAR(500)")
