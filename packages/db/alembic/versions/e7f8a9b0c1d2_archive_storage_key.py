"""Archive runs point at object storage and remember their restore.

storage_key is the object key (archives/{tenant}/{run}.jsonl.gz), storage_backend
the backend it was written to. restored_at, restored_rows and restore_error
record the last POST /api/admin/archives/{id}/restore.

Revision ID: e7f8a9b0c1d2
Revises: c5d6e7f8a9b0
"""

from __future__ import annotations

from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE archive_runs ADD COLUMN IF NOT EXISTS storage_key TEXT")
    op.execute(
        "ALTER TABLE archive_runs ADD COLUMN IF NOT EXISTS storage_backend VARCHAR(16)"
    )
    op.execute(
        "ALTER TABLE archive_runs ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE archive_runs ADD COLUMN IF NOT EXISTS restored_rows INTEGER "
        "NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE archive_runs ADD COLUMN IF NOT EXISTS restore_error TEXT")


def downgrade() -> None:
    for col in (
        "restore_error",
        "restored_rows",
        "restored_at",
        "storage_backend",
        "storage_key",
    ):
        op.execute(f"ALTER TABLE archive_runs DROP COLUMN IF EXISTS {col}")
