"""Add UNIQUE constraint on agent_collection_grants(agent_id, collection_id).

The grant relationship between an agent and a knowledge-base collection is
logically 1:1 — an agent either has READ/WRITE/ADMIN on a collection, or
not. Without a unique constraint, `seed_kb.py` and any future idempotent
seeder cannot use `INSERT ... ON CONFLICT (agent_id, collection_id)` and
instead has to do a SELECT-then-INSERT dance that's racy under concurrent
deploys + autoflushes.

This migration:
  1. Drops duplicate rows for any (agent_id, collection_id) pair, keeping
     the oldest (lowest granted_at — first grant wins). Defensive — there
     should be none today, but seed runs across versions may have created
     stragglers.
  2. Adds the UNIQUE constraint.

Idempotent: if the constraint already exists, the ALTER is a no-op (we
guard with information_schema). Safe to re-run.

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "y5z6a7b8c9d0"
down_revision = "x4y5z6a7b8c9"
branch_labels = None
depends_on = None


def _constraint_exists(name: str, table: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :n AND table_name = :t"
        ),
        {"n": name, "t": table},
    ).first()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()
    # 1. De-dupe defensively, keep oldest by granted_at (then by id as tiebreak).
    bind.execute(text("""
            DELETE FROM agent_collection_grants a
            USING agent_collection_grants b
            WHERE a.agent_id = b.agent_id
              AND a.collection_id = b.collection_id
              AND (
                a.granted_at > b.granted_at
                OR (a.granted_at = b.granted_at AND a.id > b.id)
              )
            """))

    # 2. Add the unique constraint if missing.
    if not _constraint_exists("uq_agent_collection_grant", "agent_collection_grants"):
        op.create_unique_constraint(
            "uq_agent_collection_grant",
            "agent_collection_grants",
            ["agent_id", "collection_id"],
        )


def downgrade() -> None:
    if _constraint_exists("uq_agent_collection_grant", "agent_collection_grants"):
        op.drop_constraint(
            "uq_agent_collection_grant",
            "agent_collection_grants",
            type_="unique",
        )
