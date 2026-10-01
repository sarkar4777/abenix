from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class ArchiveRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ArchiveRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "archive_runs"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    source_table: Mapped[str] = mapped_column(String(64), index=True)
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    status: Mapped[ArchiveRunStatus] = mapped_column(
        Enum(ArchiveRunStatus, name="archive_run_status"),
        default=ArchiveRunStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cutoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rows_archived: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_deleted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    file_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    oldest_row_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    newest_row_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_archive_runs_source_started", "source_table", "started_at"),
    )


class RetentionPolicy(Base, TimestampMixin):
    __tablename__ = "retention_policies"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_table: Mapped[str] = mapped_column(String(64), primary_key=True)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
