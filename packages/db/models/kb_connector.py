"""Incremental connectors that keep a knowledge collection in step with a source."""

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class KBConnectorSource(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "kb_connector_sources"
    __table_args__ = (Index("ix_kb_connector_due", "active", "next_sync_at"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    # never holds a secret, those sit encrypted in tenant_tool_credentials
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    credential_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cadence_minutes: Mapped[int] = mapped_column(
        Integer, default=1440, server_default="1440"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(
        String(24), default="idle", server_default="idle"
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # where the running pass has got to, resumes after a crash
    page_cursor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # what the next pass starts from, a delta token or a watermark
    sync_cursor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    items_seen: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    items_ingested: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    items_updated: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    items_deleted: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    items_failed: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    items_skipped: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    confirm_deletes: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class KBConnectorItem(UUIDMixin, Base):
    __tablename__ = "kb_connector_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_kb_connector_item"),
        Index("ix_kb_connector_items_run", "source_id", "last_seen_run"),
        Index("ix_kb_connector_items_document", "document_id"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kb_connector_sources.id", ondelete="CASCADE"),
    )
    external_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(500), default="", server_default="")
    version: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acl: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok", server_default="ok")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_seen_run: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
