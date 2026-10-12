"""Machine telemetry: the MQTT brokers a tenant reads Sparkplug B from."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

DEFAULT_TOPICS = ["spBv1.0/#"]


class TelemetryConnection(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "telemetry_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_telemetry_connection_name"),
        Index("ix_telemetry_connections_enabled", "enabled"),
        Index("ix_telemetry_connections_transport", "transport"),
    )
    RESOURCE_KIND = "telemetry_connection"

    name: Mapped[str] = mapped_column(String(255))
    broker_url: Mapped[str] = mapped_column(Text)
    topics: Mapped[list] = mapped_column(JSONB, default=lambda: list(DEFAULT_TOPICS))
    raw_topics: Mapped[list] = mapped_column(JSONB, default=list)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # app.core.crypto ciphertext when a KEK is set
    password: Mapped[str | None] = mapped_column(Text, nullable=True)
    protocol: Mapped[str] = mapped_column(String(32), default="sparkplug_b")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # $share/abenix/... so every ingest replica takes a slice of one busy broker
    shared_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    # a team is a permission set, null means the whole workspace
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("permission_sets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 2.5.8 T8: any transport and payload format
    transport: Mapped[str] = mapped_column(String(32), default="mqtt")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    # each value encrypted with app.core.crypto, never returned
    secrets: Mapped[dict] = mapped_column(JSONB, default=dict)
    decoder: Mapped[str] = mapped_column(String(32), default="sparkplug_b")
    decoder_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    # sha256 of the http_push bearer token, the token itself is shown once
    ingest_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    strict: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TelemetryDeviceKey(UUIDMixin, TenantMixin, Base):
    """A key one device, or one edge gateway, pushes with. Only its hash is kept."""

    __tablename__ = "telemetry_device_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_telemetry_device_key_hash"),
        Index("ix_telemetry_device_keys_connection", "connection_id", "device_id"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telemetry_connections.id", ondelete="CASCADE")
    )
    # device: writes only as device_id. gateway: writes for the assets allowed_nodes names
    kind: Mapped[str] = mapped_column(String(16), default="device")
    device_id: Mapped[str] = mapped_column(String(255))
    group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_nodes: Mapped[list] = mapped_column(JSONB, default=list)
    label: Mapped[str] = mapped_column(String(255), default="")
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
