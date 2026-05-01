from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class PipelinePatchStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class PipelineRunDiff(UUIDMixin, TenantMixin, Base):
    """Snapshot of a single pipeline-run failure."""
    __tablename__ = "pipeline_run_diffs"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(String(255))
    node_kind: Mapped[str] = mapped_column(String(64))
    node_target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_class: Mapped[str] = mapped_column(String(128))
    error_message: Mapped[str] = mapped_column(Text, default="")
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_shape: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    observed_shape: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expected_sample: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    observed_sample: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    upstream_inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    recent_success_count: Mapped[int] = mapped_column(Integer, default=0)
    recent_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class PipelinePatchProposal(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A drafted JSON-Patch against a pipeline's DSL."""
    __tablename__ = "pipeline_patch_proposals"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    triggering_diff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_run_diffs.id", ondelete="SET NULL"),
        nullable=True,
    )
    triggering_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255))
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), default=0.5)
    risk_level: Mapped[str] = mapped_column(String(16), default="low")
    dsl_before: Mapped[dict[str, Any]] = mapped_column(JSONB)
    json_patch: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    dsl_after: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[PipelinePatchStatus] = mapped_column(
        Enum(PipelinePatchStatus, name="pipeline_patch_status",
             values_callable=lambda x: [e.value for e in x]),
        default=PipelinePatchStatus.PENDING,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
