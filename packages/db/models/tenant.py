import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from models.agent import Agent
    from models.user import User


class TenantPlan(str, enum.Enum):
    FREE = "free"
    PRO = "pro"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class Tenant(UUIDMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    plan: Mapped[TenantPlan] = mapped_column(
        Enum(TenantPlan, name="tenant_plan"), default=TenantPlan.FREE
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    # Per-tenant Slack webhook for outbound notifications. Falls back to
    # ABENIX_SLACK_WEBHOOK_URL env var when NULL — see
    # apps/api/app/core/notifications.py.
    slack_webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    daily_cost_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    monthly_cost_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
    agents: Mapped[list["Agent"]] = relationship(back_populates="tenant")
