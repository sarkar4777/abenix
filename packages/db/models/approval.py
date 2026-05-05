"""Approval model — backend-enforced multi-step sign-off for agent actions."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
    expired = "expired"


class Approval(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "approvals"

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    agent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="")
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    required_signoffs: Mapped[int] = mapped_column(Integer, default=1)
    signoffs: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.pending,
        index=True,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
