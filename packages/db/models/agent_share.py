"""Agent Share model — granular sharing of agents with specific users.

Permission levels: view (read-only), execute (run), edit (modify).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class SharePermission(str, enum.Enum):
    VIEW = "view"
    EXECUTE = "execute"
    EDIT = "edit"


class AgentShare(UUIDMixin, Base):
    __tablename__ = "agent_shares"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    shared_with_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    shared_with_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    permission: Mapped[SharePermission] = mapped_column(
        Enum(SharePermission, name="share_permission", create_type=False),
        default=SharePermission.VIEW,
    )
    shared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
