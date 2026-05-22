"""Per-tenant labelled (tool, default_args) bundles.

A preset is a saved invocation of a generic tool. e.g. one yahoo_finance
tool covers every instrument, but a preset named "lbma_gold_fix" pins
the args {action: commodity_future, symbol: gold} so the UI, agents,
and pipelines all share the same configured feed by a single slug.
"""

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class ToolPreset(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "tool_presets"

    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_slug: Mapped[str] = mapped_column(String(120), nullable=False)
    default_args: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    category: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    ui_group: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    asset_class: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_tool_preset_tenant_slug"),
        Index("ix_tool_preset_tool", "tenant_id", "tool_slug"),
        Index("ix_tool_preset_group", "tenant_id", "ui_group"),
    )
