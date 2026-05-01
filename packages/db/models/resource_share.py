"""Generic resource-sharing table."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class SharePermission(str, enum.Enum):
    """Permission tiers for shared resources."""
    VIEW = "VIEW"
    EXECUTE = "EXECUTE"
    EDIT = "EDIT"


class ResourceShare(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "resource_shares"
    __table_args__ = (
        # One share per (resource, recipient) pair — last write wins on
        # permission upgrade/downgrade. Also enforces no duplicate rows
        # piling up if the share UI double-fires.
        UniqueConstraint(
            "resource_type", "resource_id", "shared_with_user_id",
            name="uq_resource_share_recipient",
        ),
        Index("ix_resource_shares_recipient", "shared_with_user_id"),
        Index("ix_resource_shares_resource", "resource_type", "resource_id"),
    )

    # Resource being shared. resource_type matches the model's
    # `RESOURCE_KIND` class attribute — see e.g. agent.py.
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))

    # Recipient. We store user_id when known and email as a fallback —
    # invite flow can resolve email→user_id later when the user signs up.
    shared_with_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    shared_with_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    permission: Mapped[SharePermission] = mapped_column(
        Enum(SharePermission, name="share_permission",
             values_callable=lambda e: [m.value for m in e]),
        default=SharePermission.VIEW,
    )

    # Audit trail — who initiated the share. Used by the share-list
    # endpoint to filter "shares I created" vs "shares I received".
    shared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"),
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
