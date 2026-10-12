"""Indexes for the system_alert retention sweep and per-person cap.

Built concurrently and best effort: during an alert storm the table is busy, so a
build that cannot get its lock is skipped and the hourly alert clean-up builds it.

Revision ID: fix259a01
Revises: agt258a01
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from alembic import op

revision = "fix259a01"
down_revision = "agt258a01"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

INDEXES = {
    "ix_notifications_type_created": "(type, created_at)",
    "ix_notifications_user_type_created": "(user_id, type, created_at)",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        bind.exec_driver_sql("SET lock_timeout = '10s'")
        for name, cols in INDEXES.items():
            try:
                bind.exec_driver_sql(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON notifications {cols}"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("%s skipped, the alert clean-up builds it: %s", name, exc)
                try:
                    # a failed concurrent build leaves an invalid index behind
                    bind.exec_driver_sql(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
                except Exception as drop_exc:  # noqa: BLE001
                    log.warning("%s left for the clean-up: %s", name, drop_exc)
        bind.exec_driver_sql("SET lock_timeout = '60s'")


def downgrade() -> None:
    have = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes("notifications")}
    for name in INDEXES:
        if name in have:
            op.drop_index(name, table_name="notifications")
