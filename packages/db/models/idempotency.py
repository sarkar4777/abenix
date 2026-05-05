"""Idempotency model — caches /api/agents/{id}/execute responses by Idempotency-Key header."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class ExecutionIdempotency(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "execution_idempotency"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
    )

    key: Mapped[str] = mapped_column(String(255), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), default="pending")
    cached_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
