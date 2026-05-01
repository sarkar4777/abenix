from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class NotificationType(str, enum.Enum):
    EXECUTION_COMPLETE = "execution_complete"
    EXECUTION_FAILED = "execution_failed"
    NEW_SUBSCRIBER = "new_subscriber"
    USAGE_WARNING = "usage_warning"
    SYSTEM_ALERT = "system_alert"


class Notification(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
