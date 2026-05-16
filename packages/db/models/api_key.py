from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from models.user import User


class ApiKey(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    key_hash: Mapped[str] = mapped_column(String(255))
    key_prefix: Mapped[str] = mapped_column(String(20))
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    # Scoping: restrict key to specific agents/resources. Null = full access.
    scopes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Example: {"allowed_agents": ["uuid1", "uuid2"], "allowed_actions": ["execute", "list"]}
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Usage limits (null = unlimited)
    max_monthly_tokens: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    max_monthly_cost: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True, default=None
    )
    cost_used: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    user: Mapped["User"] = relationship(back_populates="api_keys")
