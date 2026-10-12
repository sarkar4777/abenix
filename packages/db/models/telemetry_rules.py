"""Telemetry asset registry and signal rules, with the history of what each rule did."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

ASSET_TYPES = ("vehicle", "machine", "sensor", "device", "system")


class TelemetryAsset(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "grp", "node", "device", name="uq_telemetry_asset_key"
        ),
        Index("ix_telemetry_assets_type", "tenant_id", "asset_type"),
    )

    grp: Mapped[str] = mapped_column(String(255))
    node: Mapped[str] = mapped_column(String(255))
    # empty for the asset itself, a part name otherwise
    device: Mapped[str] = mapped_column(String(255), default="")
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    asset_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # {lat, lon} or {x, y}, with an optional label
    location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # vin, plate, serial, model and any other key
    fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TelemetryRule(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_rules"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_telemetry_rule_name"),
        Index("ix_telemetry_rules_enabled", "enabled"),
    )
    RESOURCE_KIND = "telemetry_rule"

    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    # {kind: asset|type|tag, group, node, device, type, tag}
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {kind, signal, ...} see app.telemetry.rules.model
    condition: Mapped[dict] = mapped_column(JSONB, default=dict)
    cooldown_s: Mapped[int] = mapped_column(Integer, default=60)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fire_count: Mapped[int] = mapped_column(Integer, default=0)


class TelemetryRuleFiring(UUIDMixin, TenantMixin, Base):
    __tablename__ = "telemetry_rule_firings"
    __table_args__ = (
        Index("ix_telemetry_rule_firings_rule", "tenant_id", "rule_id", "fired_at"),
        Index(
            "ix_telemetry_rule_firings_open",
            "rule_id",
            "grp",
            "node",
            "device",
            "cleared_at",
        ),
    )

    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telemetry_rules.id", ondelete="CASCADE"),
        nullable=True,
    )
    rule_name: Mapped[str] = mapped_column(String(160))
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    grp: Mapped[str] = mapped_column(String(255))
    node: Mapped[str] = mapped_column(String(255))
    device: Mapped[str] = mapped_column(String(255), default="")
    signal: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # why it fired, in plain words
    detail: Mapped[str] = mapped_column(Text, default="")
    # firing, cleared or test
    status: Mapped[str] = mapped_column(String(16), default="firing")
    # [{kind, status: ok|failed|skipped, message, ref}]
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
