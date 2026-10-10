import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    Numeric,
    String,
    Text,
)
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
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255))
    # SSO / OIDC. Both are NULL for password-auth users. For SSO users
    # auth_provider is e.g. "google" / "github" / "microsoft" and
    # external_id is the provider's stable subject (Google `sub`,
    # GitHub numeric id, Microsoft `oid`). The pair is unique-indexed
    # so the OIDC callback resolves in one query.
    auth_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.USER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_connect_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_connect_onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_settings: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=dict
    )
    # Two-step sign-in. The secret is encrypted with the tenant key, recovery
    # codes are stored as sha256 digests and each one works once.
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    totp_recovery_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Token & cost quotas (null = unlimited)
    token_monthly_allowance: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    tokens_used_this_month: Mapped[int] = mapped_column(Integer, default=0)
    cost_monthly_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True, default=None
    )
    cost_used_this_month: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
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
