"""Agent Trigger model — event-based and scheduled triggers for agents/pipelines."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class AgentTrigger(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "agent_triggers"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    trigger_type: Mapped[str] = mapped_column(String(20))  # "webhook" or "schedule"
    name: Mapped[str] = mapped_column(String(255))

    # Webhook triggers
    webhook_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )

    # Schedule triggers (cron)
    cron_expression: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # "*/5 * * * *"
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Common
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    default_context: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # Default input variables
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "completed", "failed"
