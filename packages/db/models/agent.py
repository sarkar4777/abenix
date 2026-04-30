import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if not TYPE_CHECKING:
    pass  # avoid circular

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from models.execution import Execution
    from models.knowledge_base import KnowledgeBase
    from models.marketplace import Review, Subscription
    from models.mcp_connection import AgentMCPTool
    from models.tenant import Tenant
    from models.user import User


class AgentType(str, enum.Enum):
    CUSTOM = "custom"
    OOB = "oob"
    VERTICAL = "vertical"


class AgentStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class Agent(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_tenant_created", "tenant_id", "created_at"),
        Index("ix_agents_status", "tenant_id", "status"),
    )

    creator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model_config_: Mapped[dict] = mapped_column(
        "model_config", JSONB, default=dict
    )
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agent_type"), default=AgentType.CUSTOM
    )
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    marketplace_price: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    version: Mapped[str] = mapped_column(String(50), default="0.1.0")
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), default=AgentStatus.DRAFT
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    traffic_weight: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True, server_default="100"
    )
    parent_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    per_execution_cost_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    daily_cost_limit: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    # Populated by the admin UI at /admin/scaling or via YAML. The runtime
    # reads these on every execute to route to the right pool and apply
    # rate-limits.
    runtime_pool: Mapped[str] = mapped_column(
        String(40), server_default="default", nullable=False,
        doc="Pool this agent routes to: default|chat|heavy-reasoning|gpu|long-running",
    )
    min_replicas: Mapped[int] = mapped_column(
        Integer, server_default="1", nullable=False,
        doc="KEDA floor; pool keeps at least this many replicas warm",
    )
    max_replicas: Mapped[int] = mapped_column(
        Integer, server_default="10", nullable=False,
        doc="KEDA ceiling; cost guardrail",
    )
    concurrency_per_replica: Mapped[int] = mapped_column(
        Integer, server_default="3", nullable=False,
        doc="How many simultaneous executions one pod accepts",
    )
    rate_limit_qps: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        doc="Token-bucket qps per (tenant, agent); null = unlimited",
    )
    daily_budget_usd: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True,
        doc="Daily $ cap per tenant; P4 alert auto-pauses on breach",
    )
    dedicated_mode: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False,
        doc="Opt-in per-agent pod scaling. Helm materialises a dedicated "
            "Deployment + KEDA ScaledObject keyed off the per-agent NATS "
            "subject. Use for noisy-neighbour isolation, custom resource "
            "limits, or distinct image dependencies.",
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="agents")
    creator: Mapped["User"] = relationship()
    executions: Mapped[list["Execution"]] = relationship(back_populates="agent")
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        back_populates="agent"
    )
    mcp_tools: Mapped[list["AgentMCPTool"]] = relationship(back_populates="agent")
    reviews: Mapped[list["Review"]] = relationship(back_populates="agent")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="agent")
