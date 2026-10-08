"""Earned autonomy: action types, per-agent grants, the level history and the action ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

LEVELS = (0, 1, 2, 3, 4)
ACTION_MODES = ("unmanaged", "watching", "proposed", "auto", "reported", "external")
ACTION_STATUSES = (
    "recorded",
    "watching",
    "pending",
    "approved",
    "edited",
    "rejected",
    "executed",
    "failed",
    "blocked",
    "expired",
)
OUTCOME_STATUSES = ("none", "pending", "observed", "unknown", "manual")


class ActionType(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "action_types"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_action_type_key"),)

    key: Mapped[str] = mapped_column(String(200))
    label: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    tool_name: Mapped[str] = mapped_column(String(160), index=True)
    # {"param": "topic", "glob": "controls.*"}
    match: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effect: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    world_model: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome_probe: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    limits_decision_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    max_band_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    reversible: Mapped[bool] = mapped_column(Boolean, default=False)
    ceiling: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AutonomyGrant(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "autonomy_grants"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "agent_id",
            "action_type_id",
            "scope_hash",
            name="uq_autonomy_grant_scope",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    action_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("action_types.id", ondelete="CASCADE"),
        index=True,
    )
    # {"param": "site", "equals": "A"}, null means everywhere
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scope_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    ceiling: Mapped[int] = mapped_column(Integer, default=4)
    # active | paused | removed
    state: Mapped[str] = mapped_column(String(16), default="active")
    level_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    # attention note and the level a recommendation was last sent for
    attention: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AutonomyChange(UUIDMixin, Base):
    """Append only."""

    __tablename__ = "autonomy_changes"
    __table_args__ = (Index("ix_autonomy_changes_grant", "grant_id", "created_at"),)

    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("autonomy_grants.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    from_level: Mapped[int] = mapped_column(Integer)
    to_level: Mapped[int] = mapped_column(Integer)
    # user | system
    actor_type: Mapped[str] = mapped_column(String(16), default="system")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentAction(TenantMixin, Base):
    """The ledger. One row per consequential tool call or external proposal."""

    __tablename__ = "agent_actions"
    __table_args__ = (
        Index(
            "uq_agent_actions_call",
            "execution_id",
            "tool_call_id",
            unique=True,
            postgresql_where=text(
                "execution_id IS NOT NULL AND tool_call_id IS NOT NULL"
            ),
        ),
        Index("ix_agent_actions_grant", "tenant_id", "grant_id", "created_at"),
        Index("ix_agent_actions_status", "tenant_id", "status"),
        Index("ix_agent_actions_outcome_due", "outcome_status", "outcome_due_at"),
    )

    # server defaults so the runtime can insert with plain SQL
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(255), default="", server_default="")
    agent_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(160), default="", server_default="")
    level_at_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mode: Mapped[str] = mapped_column(
        String(16), default="unmanaged", server_default="unmanaged"
    )
    target: Mapped[str | None] = mapped_column(String(500), nullable=True)
    arguments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    prediction: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    limits_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="recorded", server_default="recorded"
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_answer: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewer_alternative: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outcome_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome_status: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none"
    )
    outcome_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    score: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    harm: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    harm_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # comma list of events already emitted for this row, proposed and executed
    events_sent: Mapped[str] = mapped_column(String(40), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
