"""Outbound events: transactional outbox, subscriptions with targets and filters, delivery states.

Revision ID: fe18a43f0be1
Revises: 30c306d107f4
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "fe18a43f0be1"
down_revision = "30c306d107f4"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build new tables before this runs, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _add_column(table: str, col: sa.Column) -> None:
    if col.name not in {c["name"] for c in _insp().get_columns(table)}:
        op.add_column(table, col)


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def upgrade() -> None:
    if not _insp().has_table("event_outbox"):
        op.create_table(
            "event_outbox",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", _UUID, nullable=False, index=True),
            sa.Column("event_type", sa.String(100), nullable=False),
            sa.Column("payload", _JSONB, nullable=False, server_default="{}"),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        )
    _create_index(
        "ix_event_outbox_pending",
        "event_outbox",
        ["id"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
    )

    _add_column(
        "webhooks", sa.Column("name", sa.String(255), nullable=False, server_default="")
    )
    _add_column(
        "webhooks",
        sa.Column(
            "target_type", sa.String(16), nullable=False, server_default="webhook"
        ),
    )
    _add_column("webhooks", sa.Column("target", _JSONB, nullable=True))
    _add_column("webhooks", sa.Column("filter", _JSONB, nullable=True))
    _add_column(
        "webhooks",
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    _add_column("webhooks", sa.Column("disabled_reason", sa.Text(), nullable=True))
    _add_column("webhooks", sa.Column("created_by", _UUID, nullable=True))
    op.alter_column("webhooks", "url", existing_type=sa.String(1000), nullable=True)

    _add_column(
        "webhook_deliveries", sa.Column("event_id", sa.BigInteger(), nullable=True)
    )
    _add_column(
        "webhook_deliveries",
        sa.Column("status", sa.String(16), nullable=False, server_default="delivered"),
    )
    _add_column(
        "webhook_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column("webhook_deliveries", sa.Column("execution_id", _UUID, nullable=True))
    _create_index(
        "ix_webhook_deliveries_due",
        "webhook_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )

    # every way a run can finish emits its event, without each code path remembering to
    op.execute(
        """
        CREATE OR REPLACE FUNCTION executions_emit_event() RETURNS trigger AS $$
        BEGIN
          IF NEW.status IS DISTINCT FROM OLD.status
             AND NEW.status::text IN ('COMPLETED', 'FAILED', 'completed', 'failed') THEN
            INSERT INTO event_outbox (tenant_id, event_type, payload)
            VALUES (
              NEW.tenant_id,
              CASE WHEN lower(NEW.status::text) = 'completed' THEN 'execution.completed' ELSE 'execution.failed' END,
              jsonb_build_object(
                'execution_id', NEW.id,
                'agent_id', NEW.agent_id,
                'status', lower(NEW.status::text),
                'failure_code', NEW.failure_code,
                'duration_ms', NEW.duration_ms,
                'cost', NEW.cost,
                'risk_tier', NEW.risk_tier,
                'parent_execution_id', NEW.parent_execution_id
              )
            );
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS executions_emit_event ON executions")
    op.execute(
        "CREATE TRIGGER executions_emit_event AFTER UPDATE OF status ON executions "
        "FOR EACH ROW EXECUTE FUNCTION executions_emit_event()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS executions_emit_event ON executions")
    op.execute("DROP FUNCTION IF EXISTS executions_emit_event()")
    op.drop_index("ix_webhook_deliveries_due", table_name="webhook_deliveries")
    for c in ("execution_id", "next_attempt_at", "status", "event_id"):
        op.drop_column("webhook_deliveries", c)
    for c in (
        "created_by",
        "disabled_reason",
        "consecutive_failures",
        "filter",
        "target",
        "target_type",
        "name",
    ):
        op.drop_column("webhooks", c)
    op.drop_index("ix_event_outbox_pending", table_name="event_outbox")
    op.drop_table("event_outbox")
