import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from models.api_key import ApiKey
    from models.execution import Execution
    from models.marketplace import Review, Subscription
    from models.tenant import Tenant


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CREATOR = "creator"
    USER = "user"


class User(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.USER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_connect_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    stripe_connect_onboarded: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    notification_settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )

    # Token & cost quotas (null = unlimited)
    token_monthly_allowance: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    tokens_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    cost_monthly_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True, default=None
    )
    cost_used_this_month: Mapped[float] = mapped_column(
        Numeric(10, 4), default=0
    )
    quota_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Voice clone (ElevenLabs) — optional, with explicit consent ts.
    # voice_id is ElevenLabs-side; consent_text is what the user agreed to.
    voice_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    voice_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    voice_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    executions: Mapped[list["Execution"]] = relationship(back_populates="user")
    reviews: Mapped[list["Review"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")
