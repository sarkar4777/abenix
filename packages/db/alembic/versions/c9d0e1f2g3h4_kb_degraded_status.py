"""Add DEGRADED to kb_status + document_status, and documents.error_message.

Closes BLOCKER #2 — silent data-loss when the embedding provider was
unavailable. Documents were being flagged status=READY with
chunk_count>0 even though zero vectors made it to the store, so KBs
showed a green checkmark but returned nothing from semantic search.

After this migration:
  - kb_status / document_status both have a DEGRADED value
  - documents.error_message stores the human-readable reason
  - the worker writes DEGRADED + error_message on embedding failure
  - the API exposes degraded_doc_count and rolls DEGRADED up to the KB

Revision ID: c9d0e1f2g3h4
Revises: g5c6d7e8f9a0
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2g3h4"
down_revision = "g5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE kb_status ADD VALUE IF NOT EXISTS 'DEGRADED'")
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'DEGRADED'")
    op.add_column(
        "documents",
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Postgres has no DROP VALUE on an enum — leaving the labels in
    # place is safe; the application stops writing them after a
    # downgrade. Only the column rolls back.
    op.drop_column("documents", "error_message")
