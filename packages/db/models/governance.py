"""Governance: capability permission sets, risk tier policies, kill switches.

Generic platform controls any tenant can configure. Nothing here is specific
to one product.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin


class PermissionSet(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A named bundle of capabilities a tenant grants to users."""

    __tablename__ = "permission_sets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_permission_set_name"),
    )

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    capabilities: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # sets the platform seeds keep this key across renames, such as decision_reviewers
    builtin_key: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PermissionAssignment(UUIDMixin, TenantMixin, Base):
    __tablename__ = "permission_assignments"
    __table_args__ = (
        UniqueConstraint(
            "permission_set_id", "user_id", name="uq_permission_assignment"
        ),
        Index("ix_permission_assignment_user", "tenant_id", "user_id"),
    )

    permission_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permission_sets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RiskPolicy(UUIDMixin, TenantMixin, Base):
    """What a tenant requires of work at one risk tier. Missing rows use the defaults."""

    __tablename__ = "risk_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tier", name="uq_risk_policy_tier"),
    )

    tier: Mapped[str] = mapped_column(String(16))
    policy: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ExecutionConfigSnapshot(Base):
    """Prompt and config a run used, keyed by their hash. Written by a database trigger."""

    __tablename__ = "execution_config_snapshots"

    config_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KillSwitch(UUIDMixin, Base):
    """Stops one kind of activity. tenant_id null means every tenant."""

    __tablename__ = "kill_switches"
    __table_args__ = (
        Index("ix_kill_switch_lookup", "tenant_id", "scope", "target", "active"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(255), default="*")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    set_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    cleared_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EventOutbox(Base):
    """Events written in the same transaction as the change they describe."""

    __tablename__ = "event_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
