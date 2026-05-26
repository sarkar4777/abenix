import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class DocumentGrantSubject(str, enum.Enum):
    USER = "user"
    AGENT = "agent"
    TEAM = "team"
    ROLE = "role"


class DocumentGrantPermission(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class DocumentGrant(UUIDMixin, Base):
    __tablename__ = "document_grants"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "subject_type",
            "subject_id",
            "permission",
            name="uq_document_grant",
        ),
        Index("ix_document_grants_subject", "subject_type", "subject_id"),
        Index("ix_document_grants_tenant", "tenant_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
