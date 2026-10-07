"""Persona chunks in Postgres, plus the item columns re-indexing needs.

Revision ID: p3rs0na0vec1
Revises: 09519dee709f
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "p3rs0na0vec1"
down_revision = "09519dee709f"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("persona_items")
    for name, typ in (
        ("content", sa.Text()),
        ("last_error", sa.Text()),
        ("embedding_model", sa.String(100)),
    ):
        if name not in have:
            op.add_column("persona_items", sa.Column(name, typ, nullable=True))

    # the API's startup create_all may have built the table already
    if not sa.inspect(op.get_bind()).has_table("persona_chunks"):
        op.create_table(
            "persona_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "item_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("persona_items.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("persona_scope", sa.String(80), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", postgresql.ARRAY(postgresql.REAL()), nullable=False),
            sa.Column("embedding_model", sa.String(100), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_persona_chunks_owner_scope "
        "ON persona_chunks (tenant_id, user_id, persona_scope)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_persona_chunks_item ON persona_chunks (item_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS persona_chunks")
    have = _cols("persona_items")
    for name in ("embedding_model", "last_error", "content"):
        if name in have:
            op.drop_column("persona_items", name)
