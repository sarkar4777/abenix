"""Source Watch: authoritative sources a tenant monitors, their immutable snapshots, and detected changes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

SOURCE_KINDS = ("html", "pdf", "xlsx", "csv", "json", "rss")


class WatchSource(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "watch_sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_watch_source_name"),
        Index(
            "ix_watch_sources_due",
            "next_check_at",
            postgresql_where=text("active"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16), default="html")
    cadence_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # a tenant tool credential key, sent as Authorization or as "Header: value"
    credentials_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    headers: Mapped[dict] = mapped_column(JSONB, default=dict)
    # CSS selector for html, JSON pointer for json, sheet name for xlsx
    selector: Mapped[str | None] = mapped_column(Text, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    risk_tier: Mapped[str] = mapped_column(String(16), default="low")
    ingest_to_kb: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    kb_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # changed | unchanged | not_modified | baseline | error | stopped
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    etag: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(128), nullable=True)
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    check_count: Mapped[int] = mapped_column(Integer, default=0)


class SourceSnapshot(UUIDMixin, TenantMixin, Base):
    """Immutable. A database trigger refuses updates."""

    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", "content_sha256", name="uq_source_snapshot_sha"),
        Index("ix_source_snapshots_source_fetched", "source_id", "fetched_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watch_sources.id", ondelete="CASCADE")
    )
    url: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    content_sha256: Mapped[str] = mapped_column(String(64))
    text_sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(255), default="")
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    http_status: Mapped[int] = mapped_column(Integer, default=200)
    http_headers: Mapped[dict] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    parser_version: Mapped[str] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_text: Mapped[str] = mapped_column(Text, default="")
    normalized_text_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    text_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    # rows for csv, xlsx and rss, so the next change can be diffed row by row
    tables: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[list] = mapped_column(JSONB, default=list)


class SourceChange(UUIDMixin, TenantMixin, Base):
    __tablename__ = "source_changes"
    __table_args__ = (
        Index("ix_source_changes_source_detected", "source_id", "detected_at"),
        Index("ix_source_changes_tenant_detected", "tenant_id", "detected_at"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("watch_sources.id", ondelete="CASCADE")
    )
    from_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_snapshots.id", ondelete="CASCADE")
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[dict] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    materiality_hint: Mapped[str] = mapped_column(String(16), default="low")
