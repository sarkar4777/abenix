"""Per-model LLM pricing table — the source of truth for cost"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Numeric, String, func
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
    # All rates in $ per 1,000,000 tokens, matching published provider docs.
    input_per_m: Mapped[float] = mapped_column(Numeric(18, 12), nullable=False)
    output_per_m: Mapped[float] = mapped_column(Numeric(18, 12), nullable=False)
    cached_input_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    # Batch-API / async-tier discount; null = batch pricing unavailable.
    batch_input_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
    batch_output_per_m: Mapped[float | None] = mapped_column(
        Numeric(18, 12),
        nullable=True,
    )
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
