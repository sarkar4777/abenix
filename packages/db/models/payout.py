import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from models.agent import Agent
    from models.marketplace import Subscription
    from models.user import User


class PayoutStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class Payout(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "payouts"
    __table_args__ = (
        Index("ix_payouts_creator", "creator_id", "created_at"),
        Index("ix_payouts_subscription", "subscription_id"),
    )

    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount_total: Mapped[float] = mapped_column(Numeric(10, 2))
    platform_fee: Mapped[float] = mapped_column(Numeric(10, 2))
    creator_amount: Mapped[float] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="usd")
    status: Mapped[str] = mapped_column(String(50), default=PayoutStatus.PENDING.value)

    creator: Mapped["User"] = relationship()
    agent: Mapped["Agent"] = relationship()
    subscription: Mapped["Subscription | None"] = relationship()
