import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class RecordType(str, enum.Enum):
    EXECUTION = "execution"
    TOKEN = "token"
    STORAGE = "storage"


class UsageRecord(UUIDMixin, TenantMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_user_type", "user_id", "record_type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    record_type: Mapped[RecordType] = mapped_column(
        Enum(RecordType, name="record_type")
    )
    quantity: Mapped[float] = mapped_column(Numeric(16, 4))
    unit: Mapped[str] = mapped_column(String(50))
    cost: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
