"""Add fail_closed flag to moderation_policies.

Closes the silent fail-open BLOCKER — when the OpenAI moderation API
returned 429 (quota exhausted), every /vet call resolved as
outcome=error action=allow and violent / sexual / self-harm content
flowed straight through. The gate already supports a `fail_closed`
config knob (engine.moderation_gate.GateConfig); this migration gives
the per-tenant policy a column to carry the operator's choice.

Idempotent — checks information_schema before adding the column so
re-running against a partially-migrated DB is safe.

Revision ID: d0e1f2g3h4i5
Revises: c9d0e1f2g3h4
"""

from __future__ import annotations

from alembic import op


revision = "d0e1f2g3h4i5"
down_revision = "c9d0e1f2g3h4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.exec_driver_sql(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'moderation_policies'
           AND column_name = 'fail_closed'
        """
    ).first()
    if exists:
        return
    op.execute(
        "ALTER TABLE moderation_policies "
        "ADD COLUMN fail_closed BOOLEAN NOT NULL DEFAULT false"
    )
    # Data backfill: tenants that received the auto-seeded "Default Policy"
    # row (from register / SSO / lazy-seed paths) should now fail closed.
    # Tenants who built a custom policy keep the migration default (false)
    # so they have to opt in deliberately. The seeded row is identified by
    # the exact name + description string used in the three seed sites.
    op.execute(
        """
        UPDATE moderation_policies
           SET fail_closed = true
         WHERE name = 'Default Policy'
           AND (
                description ILIKE 'Auto-seeded%'
                OR description IS NULL
           )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.exec_driver_sql(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'moderation_policies'
           AND column_name = 'fail_closed'
        """
    ).first()
    if not exists:
        return
    op.execute("ALTER TABLE moderation_policies DROP COLUMN fail_closed")
