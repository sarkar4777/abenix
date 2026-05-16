"""Add tenants.slack_webhook_url + agent_shares.permission column."""

from alembic import op
import sqlalchemy as sa

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not any(c["name"] == "slack_webhook_url" for c in insp.get_columns("tenants")):
        op.add_column(
            "tenants",
            sa.Column("slack_webhook_url", sa.String(length=500), nullable=True),
        )

    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE share_permission AS ENUM ('VIEW', 'EXECUTE', 'EDIT'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    # agent_shares is declared in models/agent_share.py but historically only
    # got created by Base.metadata.create_all at API startup, leaving migrations
    # that ALTER it brittle on fresh installs.  Materialise it here if absent.
    if not insp.has_table("agent_shares"):
        op.create_table(
            "agent_shares",
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
                nullable=False,
                index=True,
            ),
            sa.Column(
                "agent_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "created_by",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=True,
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
    op.execute(
        "ALTER TABLE agent_shares "
        "ADD COLUMN IF NOT EXISTS permission share_permission "
        "NOT NULL DEFAULT 'VIEW';"
    )

    # ON DELETE SET NULL on moderation_events.policy_id so admins can
    # delete a policy without first hand-clearing the audit history.
    if insp.has_table("moderation_events"):
        op.execute(
            "ALTER TABLE moderation_events "
            "DROP CONSTRAINT IF EXISTS moderation_events_policy_id_fkey;"
        )
        op.execute(
            "ALTER TABLE moderation_events "
            "ADD CONSTRAINT moderation_events_policy_id_fkey "
            "FOREIGN KEY (policy_id) REFERENCES moderation_policies(id) "
            "ON DELETE SET NULL;"
        )


def downgrade() -> None:
    op.drop_column("tenants", "slack_webhook_url")
    op.execute("ALTER TABLE agent_shares DROP COLUMN IF EXISTS permission;")
    op.execute("DROP TYPE IF EXISTS share_permission;")
    op.execute(
        "ALTER TABLE moderation_events "
        "DROP CONSTRAINT IF EXISTS moderation_events_policy_id_fkey;"
    )
    op.execute(
        "ALTER TABLE moderation_events "
        "ADD CONSTRAINT moderation_events_policy_id_fkey "
        "FOREIGN KEY (policy_id) REFERENCES moderation_policies(id);"
    )
