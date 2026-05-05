"""Edge runtime gateway registry — one row per remote pod."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class EdgeGateway(UUIDMixin, TenantMixin, Base):
    __tablename__ = "edge_gateways"

    gateway_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="online", nullable=False)
    deployed_agents: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
