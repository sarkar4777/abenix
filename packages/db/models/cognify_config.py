import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class CognifyConfig(Base):
    __tablename__ = "cognify_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    auto_accept_threshold: Mapped[float] = mapped_column(Float, default=0.85)
    conflict_action: Mapped[str] = mapped_column(String(16), default="flag")
    max_parallel_docs: Mapped[int] = mapped_column(Integer, default=8)
    daily_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CognifyConflict(Base):
    __tablename__ = "cognify_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    entity_canonical_name: Mapped[str] = mapped_column(String(512))
    property_name: Mapped[str] = mapped_column(String(128))
    source_a_doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_a_value: Mapped[str] = mapped_column(Text)
    source_a_confidence: Mapped[float] = mapped_column(Float)
    source_b_doc_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_b_value: Mapped[str] = mapped_column(Text)
    source_b_confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="open")
    resolved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
