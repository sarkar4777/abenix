"""One agent per slug in a workspace.

Renames any existing duplicates with -2, -3 and so on, keeping the oldest on the
plain slug, then adds a unique index on (tenant_id, slug).

Revision ID: agt258a01
Revises: tel258a05
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "agt258a01"
down_revision = "tel258a05"
branch_labels = None
depends_on = None

INDEX = "uq_agents_tenant_slug"


def upgrade() -> None:
    bind = op.get_bind()
    if INDEX in {ix["name"] for ix in sa.inspect(bind).get_indexes("agents")}:
        return
    dups = bind.execute(
        sa.text(
            """
            SELECT id, tenant_id, slug FROM (
                SELECT id, tenant_id, slug,
                       row_number() OVER (
                           PARTITION BY tenant_id, slug ORDER BY created_at, id
                       ) AS rn
                FROM agents
            ) ranked
            WHERE rn > 1
            ORDER BY tenant_id, slug
            """
        )
    ).fetchall()
    for agent_id, tenant_id, slug in dups:
        taken = {
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT slug FROM agents WHERE tenant_id = :t AND slug LIKE :p"
                ),
                {"t": tenant_id, "p": f"{slug}-%"},
            )
        }
        n = 2
        while f"{slug[:240]}-{n}" in taken:
            n += 1
        bind.execute(
            sa.text("UPDATE agents SET slug = :s WHERE id = :id"),
            {"s": f"{slug[:240]}-{n}", "id": agent_id},
        )
    op.create_index(INDEX, "agents", ["tenant_id", "slug"], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="agents")
