"""Tool invocation log. One row per direct tool execute call.

Distinct from `executions` which represents agent runs. A tool can run
inside an agent loop OR be called directly via the SDK / REST. The agent
case already gets logged on `executions.tool_calls`. The direct case
gets a dedicated row here so it shows up in audit + analytics + the
debug view, and so the api pod is not the only place that knows the
call happened.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class ToolInvocationStatus(str, enum.Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


class ToolInvocation(UUIDMixin, TenantMixin, Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (
        Index("ix_tool_invocations_tool_ts", "tool_slug", "created_at"),
        Index("ix_tool_invocations_user", "user_id"),
        Index("ix_tool_invocations_via", "via"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    via: Mapped[str] = mapped_column(
        String(40), default="direct"
    )  # direct | agent | pipeline
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    tool_slug: Mapped[str] = mapped_column(String(120), index=True)
    arguments: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ToolInvocationStatus] = mapped_column(
        Enum(
            ToolInvocationStatus,
            name="tool_invocation_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ToolInvocationStatus.OK,
    )
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_error: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    requested_via: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )  # sdk | http | agent-runtime
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    acting_subject: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
