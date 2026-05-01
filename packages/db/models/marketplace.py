import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, UUIDMixin


class Review(UUIDMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_agent", "agent_id", "created_at"),
        Index("ix_reviews_user_agent", "user_id", "agent_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    agent: Mapped["Agent"] = relationship(back_populates="reviews")
    user: Mapped["User"] = relationship(back_populates="reviews")


class Subscription(UUIDMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_user_agent", "user_id", "agent_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    plan_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active")
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="subscriptions")
    agent: Mapped["Agent"] = relationship(back_populates="subscriptions")


from models.agent import Agent  # noqa: E402
from models.user import User  # noqa: E402
