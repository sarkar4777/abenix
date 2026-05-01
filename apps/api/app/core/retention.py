"""Data Retention Policies — tenant-configurable data lifecycle management."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RetentionPolicy:
    """Retention configuration for a tenant."""
    execution_retention_days: int = 90
    message_retention_days: int = 365
    audit_log_retention_days: int = 730  # 2 years minimum for compliance
    knowledge_retention_days: int = 365


def parse_retention_settings(settings: dict[str, Any] | None) -> RetentionPolicy:
    """Parse retention settings from tenant JSONB config."""
    if not settings:
        return RetentionPolicy()
    return RetentionPolicy(
        execution_retention_days=max(settings.get("execution_retention_days", 90), 7),
        message_retention_days=max(settings.get("message_retention_days", 365), 30),
        audit_log_retention_days=max(settings.get("audit_log_retention_days", 730), 365),
        knowledge_retention_days=max(settings.get("knowledge_retention_days", 365), 30),
    )


async def enforce_retention(db: AsyncSession, tenant_id: Any, policy: RetentionPolicy) -> dict[str, int]:
    """Delete data older than retention policy allows. Returns counts of deleted rows."""
    import uuid as _uuid
    from models.execution import Execution
    from models.conversation import Conversation
    from models.activity_log import ActivityLog
    from models.user import User

    tid = _uuid.UUID(str(tenant_id)) if not isinstance(tenant_id, _uuid.UUID) else tenant_id
    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}

    # Delete old executions
    cutoff = now - timedelta(days=policy.execution_retention_days)
    result = await db.execute(
        delete(Execution).where(
            Execution.tenant_id == tid,
            Execution.created_at < cutoff,
        )
    )
    counts["executions_deleted"] = result.rowcount

    # Delete old conversations
    cutoff = now - timedelta(days=policy.message_retention_days)
    result = await db.execute(
        delete(Conversation).where(
            Conversation.user_id.in_(
                select(User.id).where(User.tenant_id == tid)
            ),
            Conversation.created_at < cutoff,
        )
    )
    counts["conversations_deleted"] = result.rowcount

    # Delete old audit logs (keep minimum 1 year)
    cutoff = now - timedelta(days=policy.audit_log_retention_days)
    result = await db.execute(
        delete(ActivityLog).where(
            ActivityLog.tenant_id == tid,
            ActivityLog.created_at < cutoff,
        )
    )
    counts["audit_logs_deleted"] = result.rowcount

    await db.commit()
    logger.info("Retention enforcement for tenant %s: %s", tenant_id, counts)
    return counts


async def apply_retention(db: AsyncSession, tenant_id: str, policy: RetentionPolicy) -> dict[str, int]:
    """Apply retention policy — delete records older than configured periods.

    Returns counts of deleted records per table.
    """
    import uuid
    tid = uuid.UUID(tenant_id)
    now = datetime.now(timezone.utc)
    deleted = {}

    try:
        # Executions
        from models.execution import Execution
        cutoff = now - timedelta(days=policy.execution_retention_days)
        result = await db.execute(
            delete(Execution).where(
                and_(Execution.tenant_id == tid, Execution.created_at < cutoff)
            )
        )
        deleted["executions"] = result.rowcount

        # Messages
        from models.conversation import Message
        cutoff = now - timedelta(days=policy.message_retention_days)
        result = await db.execute(
            delete(Message).where(Message.created_at < cutoff)
        )
        deleted["messages"] = result.rowcount

        await db.commit()
        logger.info("Retention applied for tenant %s: %s", tenant_id, deleted)

    except Exception as e:
        logger.error("Retention cleanup failed for tenant %s: %s", tenant_id, e)
        await db.rollback()

    return deleted
