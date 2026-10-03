from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class ActivityLog(UUIDMixin, TenantMixin, Base):
    __tablename__ = "activity_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # global order, then linked per tenant by the audit chainer
    audit_seq: Mapped[int] = mapped_column(
        BigInteger, server_default=text("nextval('activity_logs_audit_seq')")
    )
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chain_pos: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pii_salt: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pii_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
