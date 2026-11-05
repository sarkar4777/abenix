"""Long running knowledge operations, their receipts and the tenant limits."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin

REEMBED_LIVE = ("queued", "running", "pausing", "paused", "flipping", "cleaning")


class KBReembedJob(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "kb_reembed_jobs"
    __table_args__ = (
        Index(
            "uq_kb_reembed_live",
            "kb_id",
            unique=True,
            postgresql_where=text(
                "status IN ('queued','running','pausing','paused','flipping','cleaning')"
            ),
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        index=True,
    )
    from_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    to_model: Mapped[str] = mapped_column(String(120))
    backend: Mapped[str] = mapped_column(String(20), default="pgvector")
    from_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    target_generation: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    documents_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    documents_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunks_done: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    from_file: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    from_indexed_text: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    flipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KBReembedDocument(Base):
    __tablename__ = "kb_reembed_documents"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kb_reembed_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    source: Mapped[str] = mapped_column(
        String(16), default="file", server_default="file"
    )
    done_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KBDeleteJob(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """The receipt of a collection delete, it outlives the collection on purpose."""

    __tablename__ = "kb_delete_jobs"

    kb_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    kb_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    phase: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued"
    )
    documents_deleted: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    chunks_deleted: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    files_deleted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    entities_deleted: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TenantKnowledgeQuota(Base):
    """An empty limit means no limit, zero means nothing more is allowed."""

    __tablename__ = "tenant_knowledge_quotas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    max_documents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_chunks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_storage_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_embedding_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    monthly_cognify_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class KnowledgeSpend(Base):
    __tablename__ = "knowledge_spend"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # first day of the month, UTC
    period: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    embedding_usd: Mapped[float] = mapped_column(
        Numeric(14, 6), default=0, server_default="0"
    )
    embedding_tokens: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    cognify_usd: Mapped[float] = mapped_column(
        Numeric(14, 6), default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
