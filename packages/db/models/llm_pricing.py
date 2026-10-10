"""Per-model LLM pricing table — the source of truth for cost"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class LLMModelPricing(UUIDMixin, Base):
    __tablename__ = "llm_model_pricing"
    __table_args__ = (
        Index("ix_llm_pricing_model_effective", "model", "effective_from"),
        Index("ix_llm_pricing_provider", "provider"),
    )

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    input_per_m: Mapped[float] = mapped_column(Numeric(18, 12), nullable=False)
    output_per_m: Mapped[float] = mapped_column(Numeric(18, 12), nullable=False)
    cached_input_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    batch_input_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    batch_output_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fallback_to: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(128)),
        nullable=True,
    )
    provider_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deprecated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    migration_hint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelAvailability(Base):
    __tablename__ = "model_availability"
    __table_args__ = (Index("ix_model_availability_status", "status"),)

    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="available")
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_ok_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class ModelAvailabilityEvent(Base):
    """Each status change of a model, written by the availability probe and admin overrides."""

    __tablename__ = "model_availability_events"
    __table_args__ = (Index("ix_model_availability_events_model_at", "model", "at"),)

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
