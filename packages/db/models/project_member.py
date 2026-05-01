"""Per-project membership."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class ProjectRole(str, enum.Enum):
    VIEW = "VIEW"
    EDIT = "EDIT"
    ADMIN = "ADMIN"


PROJECT_ROLE_RANK = {
    ProjectRole.VIEW: 0,
    ProjectRole.EDIT: 1,
    ProjectRole.ADMIN: 2,
}


class ProjectMember(UUIDMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "user_id",
            name="uq_project_member",
        ),
        Index("ix_project_members_project", "project_id"),
        Index("ix_project_members_user", "user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_projects.id", ondelete="CASCADE"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(
            ProjectRole,
            name="project_role",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ProjectRole.VIEW,
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
