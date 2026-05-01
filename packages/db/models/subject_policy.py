"""Subject Policy — RBAC delegation policies for acting subjects."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class SubjectPolicy(UUIDMixin, TimestampMixin, Base):
    """RBAC policy for an acting subject under a specific API key."""

    __tablename__ = "subject_policies"
    __table_args__ = (
        Index("ix_subject_policies_lookup", "api_key_id", "subject_type", "subject_id"),
    )

    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), index=True
    )
    subject_type: Mapped[str] = mapped_column(String(50), index=True)
    # subject_id can be a specific ID or "*" for wildcard (applies to all subjects)
    subject_id: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    rules: Mapped[dict] = mapped_column(JSONB, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
