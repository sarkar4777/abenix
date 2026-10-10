"""Decisions 2.5.7 wave 2: the seeded Decision reviewers set, and invites that grant it.

Revision ID: dec257a02
Revises: dec257a01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "dec257a02"
down_revision = "dec257a01"
branch_labels = None
depends_on = None

REVIEWERS = "Decision reviewers"
REVIEWERS_DESC = (
    "People in this set can approve decisions: publishing a version, lowering a risk "
    "tier, a review after a raise, and retiring, archiving or restoring at high risk."
)


def _has_column(table: str, col: str) -> bool:
    return col in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("team_invites", "can_approve_decisions"):
        op.add_column(
            "team_invites",
            sa.Column(
                "can_approve_decisions",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )
    if not _has_column("permission_sets", "builtin_key"):
        op.add_column(
            "permission_sets",
            sa.Column("builtin_key", sa.String(64), nullable=True),
        )
    # a set an admin already named this way is adopted rather than duplicated
    op.execute(
        sa.text(
            "UPDATE permission_sets SET builtin_key = 'decision_reviewers' "
            "WHERE name = :name AND builtin_key IS NULL"
        ).bindparams(name=REVIEWERS)
    )
    op.execute(
        sa.text(
            "INSERT INTO permission_sets (id, tenant_id, name, description, capabilities, "
            "builtin_key, created_at, updated_at) "
            "SELECT gen_random_uuid(), t.id, :name, :desc, "
            'CAST(\'["approvals.sign", "decisions.review"]\' AS jsonb), '
            "'decision_reviewers', now(), now() FROM tenants t "
            "WHERE NOT EXISTS (SELECT 1 FROM permission_sets p WHERE p.tenant_id = t.id "
            "AND (p.builtin_key = 'decision_reviewers' OR p.name = :name))"
        ).bindparams(name=REVIEWERS, desc=REVIEWERS_DESC)
    )


def downgrade() -> None:
    if _has_column("permission_sets", "builtin_key"):
        op.drop_column("permission_sets", "builtin_key")
    if _has_column("team_invites", "can_approve_decisions"):
        op.drop_column("team_invites", "can_approve_decisions")
