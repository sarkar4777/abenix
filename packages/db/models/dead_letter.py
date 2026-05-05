"""Dead-letter executions — records of executions stuck in STALE_SWEEP/failed states for replay."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class DeadLetterExecution(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "dead_letter_executions"

    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    failure_code: Mapped[str] = mapped_column(String(80), default="UNKNOWN")
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    original_input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    replay_count: Mapped[int] = mapped_column(default=0)
    last_replay_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
