"""Webhook delivery log — tracks each attempt to deliver a webhook event."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class WebhookDelivery(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    webhook_id = Column(
        UUID(as_uuid=True),
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event = Column(String(100), nullable=False)
    request_payload = Column(JSONB, nullable=True)
    response_status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)  # first 500 chars
    delivered = Column(Boolean, default=False)
    attempts = Column(Integer, default=1)
    delivery_id = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    event_id = Column(BigInteger, nullable=True)
    # pending | retrying | delivered | dead
    status = Column(String(16), default="delivered", nullable=False)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    execution_id = Column(UUID(as_uuid=True), nullable=True)
