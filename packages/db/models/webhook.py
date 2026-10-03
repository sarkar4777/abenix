"""Webhook configuration model — tenant-scoped webhook URLs for event delivery."""

from __future__ import annotations

from datetime import datetime

import uuid

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class Webhook(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "webhooks"

    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    # webhook | agent | pipeline
    target_type: Mapped[str] = mapped_column(String(16), default="webhook")
    target: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    filter: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    signing_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    events: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # ["execution.completed", "execution.failed", ...]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
