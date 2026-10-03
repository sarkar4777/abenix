"""Agent evaluation suites: golden cases with assertions, scored runs and their per-case results."""

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
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

RUN_STATES = ("queued", "running", "completed", "failed", "cancelled")
TRIGGERS = ("manual", "schedule", "model_change", "publish_gate")


class EvalSuite(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "eval_suites"
    __table_args__ = (Index("ix_eval_suites_tenant_agent", "tenant_id", "agent_id"),)

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    # an agent or a pipeline, both live in agents
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE")
    )
    gating: Mapped[bool] = mapped_column(Boolean, default=False)
    pass_threshold: Mapped[float] = mapped_column(Float, default=0.9)
    schedule_cron: Mapped[str | None] = mapped_column(String(120), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rerun_on_model_change: Mapped[bool] = mapped_column(Boolean, default=False)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    judge_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class EvalCase(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"

    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_suites.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    input_message: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    assertions: Mapped[list] = mapped_column(JSONB, default=list)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    # the run it was captured from and what that run answered, for previews
    source_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reference_output: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalRun(UUIDMixin, TenantMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        Index("ix_eval_runs_suite_created", "suite_id", "created_at"),
        Index("ix_eval_runs_config", "agent_id", "config_hash"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_suites.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # the executions provenance config_hash: system prompt plus model config
    config_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_override: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float, default=0.9)
    threshold_met: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errored: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str] = mapped_column(String(16), default="manual")
    triggered_by_user: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EvalResult(UUIDMixin, TenantMixin, Base):
    __tablename__ = "eval_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    case_name: Mapped[str] = mapped_column(String(255), default="")
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="completed")
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    assertion_results: Mapped[list] = mapped_column(JSONB, default=list)
    output_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
