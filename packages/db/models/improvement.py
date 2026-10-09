"""Governed self-improvement: feedback, lessons, lesson clusters and improvement proposals."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

LESSON_SOURCES = (
    "thumbs",
    "correction",
    "autonomy_reject",
    "autonomy_edit",
    "autonomy_alternative",
    "harm",
    "band_miss",
    "run_failed",
    "pipeline_failed",
    "drift",
    "eval_failed",
    "note",
    "sdk",
    "positive",
)
CLUSTER_STATES = ("open", "proposing", "proposed", "fixed", "dismissed")
PROPOSAL_STATES = (
    "drafting",
    "proving",
    "failed_proof",
    "awaiting_approval",
    "approved",
    "rejected",
    "released",
    "kept",
    "rolled_back",
    "superseded",
)
CHANGE_KINDS = (
    "examples",
    "prompt_edit",
    "tool_config",
    "pipeline_patch",
    "tool_set",
    "model",
)
CASE_STATES = ("accepted", "suggested", "dropped")
REVISION_SOURCES = ("edit", "healing", "improvement", "revert", "import")


class Feedback(UUIDMixin, TenantMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        Index(
            "ix_feedback_tenant_agent_created", "tenant_id", "agent_id", "created_at"
        ),
        Index("ix_feedback_tenant_created", "tenant_id", "created_at"),
        Index("ix_feedback_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LessonCluster(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "lesson_clusters"
    __table_args__ = (
        Index(
            "uq_lesson_clusters_signature",
            "tenant_id",
            "agent_id",
            "signature",
            unique=True,
        ),
        Index(
            "ix_lesson_clusters_tenant_state", "tenant_id", "state", "last_lesson_at"
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(String(300), default="", server_default="")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    # stable hash new lessons are matched on, so grouping is incremental
    signature: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    negative_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    severity: Mapped[str] = mapped_column(
        String(16), default="low", server_default="low"
    )
    trend: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    state: Mapped[str] = mapped_column(
        String(16), default="open", server_default="open"
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    last_lesson_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Lesson(UUIDMixin, TenantMixin, Base):
    __tablename__ = "lessons"
    __table_args__ = (
        Index("uq_lessons_capture", "source", "capture_key", unique=True),
        Index("ix_lessons_tenant_created", "tenant_id", "created_at"),
        Index("ix_lessons_agent_created", "tenant_id", "agent_id", "created_at"),
        Index("ix_lessons_cluster", "cluster_id", "created_at"),
        Index("ix_lessons_execution", "execution_id"),
        Index("ix_lessons_by_user", "by_user"),
        Index(
            "ix_lessons_unclustered",
            "created_at",
            postgresql_where=text("cluster_id IS NULL"),
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    agent_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lesson_clusters.id", ondelete="SET NULL"),
        nullable=True,
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    polarity: Mapped[str] = mapped_column(
        String(16), default="negative", server_default="negative"
    )
    input_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    output_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # with source, makes a repeated capture of the same signal a no-op
    capture_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    by_user: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ImprovementProposal(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "improvement_proposals"
    __table_args__ = (
        Index("ix_improvement_proposals_agent", "tenant_id", "agent_id", "created_at"),
        Index("ix_improvement_proposals_state", "tenant_id", "state"),
        Index("ix_improvement_proposals_cluster", "cluster_id"),
    )
    # rows are serialised right after updates, updated_at must not lazy load in async code
    __mapper_args__ = {"eager_defaults": True}

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lesson_clusters.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_kind: Mapped[str] = mapped_column(String(32))
    diff: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    rationale: Mapped[str] = mapped_column(Text, default="", server_default="")
    risk: Mapped[str] = mapped_column(String(16), default="low", server_default="low")
    state: Mapped[str] = mapped_column(
        String(24), default="drafting", server_default="drafting"
    )
    progress: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    proof: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    released_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    watch_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    watch_runs_target: Mapped[int] = mapped_column(
        Integer, default=200, server_default="200"
    )
    watch_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
