from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class ActivityLog(UUIDMixin, TenantMixin, Base):
    __tablename__ = "activity_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
