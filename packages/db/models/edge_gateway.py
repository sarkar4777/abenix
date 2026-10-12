"""Edge gateways: boxes that run agent bundles, collect from local buses and devices, or both."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class EdgeGateway(UUIDMixin, TenantMixin, Base):
    __tablename__ = "edge_gateways"

    gateway_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # waiting until it enrols, then online, offline or revoked
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    deployed_agents: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 2.5.8: agents, collect or both
    roles: Mapped[list] = mapped_column(
        JSONB, default=lambda: ["agents"], nullable=False
    )
    # secret fields inside are app.core.crypto ciphertext
    collectors: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    health: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    applied_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(128), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # sha256 of the one-time enrolment token
    enroll_token_hash: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    enroll_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enrolled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_data_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # the http_push source it sends to, and its gateway key there
    telemetry_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
