import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, UUIDMixin


class ExecutionStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Execution(UUIDMixin, TenantMixin, Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_agent_status", "agent_id", "status"),
        Index("ix_executions_user_agent", "user_id", "agent_id"),
        Index("ix_executions_tenant_created", "tenant_id", "created_at"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    input_message: Mapped[str] = mapped_column(Text)
    output_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status"), default=ExecutionStatus.RUNNING
    )
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    # Per-provider subtotals so dashboards can split "we spent $X on
    # Anthropic, $Y on OpenAI fallback, $Z on Google." The plain `cost`
    # column is still the total — these four sum to it.
    anthropic_cost: Mapped[float] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    openai_cost: Mapped[float] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    google_cost: Mapped[float] = mapped_column(
        Numeric(10, 6), default=0, nullable=False
    )
    other_cost: Mapped[float] = mapped_column(Numeric(10, 6), default=0, nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    node_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    execution_trace: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True
    )
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    agent: Mapped["Agent"] = relationship(back_populates="executions")
    user: Mapped["User"] = relationship(back_populates="executions")


from models.agent import Agent  # noqa: E402
from models.user import User  # noqa: E402
