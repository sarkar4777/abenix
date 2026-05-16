from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class KBQueryInvocation(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "kb_query_invocations"

    kb_collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    query_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    caller_source: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_kbq_collection_created", "kb_collection_id", "created_at"),
        Index("ix_kbq_tenant_created", "tenant_id", "created_at"),
        Index("ix_kbq_execution", "execution_id"),
    )
