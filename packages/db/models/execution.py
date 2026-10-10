import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    event,
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
    # actAs delegation: when the SDK is called with `act_as=ActingSubject(...)`,
    # the abenix-side user_id stays the API-key holder (the service account)
    # but the END-USER who actually triggered the execution is recorded here.
    # Standalone-app proxies (ContractIQ, etc.) match ownership on subject_id
    # so the legitimate caller can read their own execution back.
    subject_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_requested: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_fallback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
    # governance and provenance, what tier the run reached and exactly what ran
    risk_tier: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    risk_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    agent_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # queue lease, a redelivered message only takes over once the owner stops renewing
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # what started the run, the name is a snapshot so it survives a deleted trigger
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_triggers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    trigger_kind: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    trigger_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    agent: Mapped["Agent"] = relationship(back_populates="executions")
    user: Mapped["User"] = relationship(back_populates="executions")


PROVIDERS = ("anthropic", "openai", "google", "other")


def provider_of(model: str | None) -> str:
    m = (model or "").lower().split("/")[-1]
    if m.startswith("us.anthropic.") or m.startswith("anthropic."):
        return "anthropic"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return "other"


def provider_cost_values(
    costs: dict[str, float] | None = None,
    total: float | None = None,
    model: str | None = None,
) -> dict[str, float]:
    """Column values for the per-provider split.

    An exact split wins. Without one the whole total goes to the provider of
    the model that ran, which is right for every single-model run.
    """
    split = {p: round(float((costs or {}).get(p) or 0), 6) for p in PROVIDERS}
    if not any(split.values()) and total:
        split[provider_of(model)] = round(float(total), 6)
    return {f"{p}_cost": v for p, v in split.items()}


def set_provider_costs(
    row: "Execution",
    costs: dict[str, float] | None = None,
    model: str | None = None,
) -> None:
    total = float(getattr(row, "cost", 0) or 0)
    model = model or getattr(row, "model_used", None)
    for col, v in provider_cost_values(costs, total, model).items():
        setattr(row, col, v)


@event.listens_for(Execution, "before_insert")
@event.listens_for(Execution, "before_update")
def _fill_provider_costs(_mapper, _conn, row: "Execution") -> None:
    # writers that only set the total still get a split
    if not row.cost:
        return
    if any(float(getattr(row, f"{p}_cost") or 0) for p in PROVIDERS):
        return
    set_provider_costs(row)


from models.agent import Agent  # noqa: E402
from models.user import User  # noqa: E402
