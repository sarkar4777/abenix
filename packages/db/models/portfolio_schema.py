"""Portfolio Schema — dynamic schema definitions for SchemaPortfolioTool."""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class PortfolioSchema(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """User-defined schema for SchemaPortfolioTool."""

    __tablename__ = "portfolio_schemas"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "domain_name", name="uq_portfolio_schemas_tenant_domain"
        ),
    )

    domain_name: Mapped[str] = mapped_column(String(100), index=True)
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_noun: Mapped[str] = mapped_column(String(50), default="record")
    record_noun_plural: Mapped[str] = mapped_column(String(50), default="records")

    # Full schema JSON: { domain, main_table, related_tables }
    schema_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
