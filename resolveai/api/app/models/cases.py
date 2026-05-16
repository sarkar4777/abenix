"""ResolveAI case-lifecycle tables."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UUIDMixin


class CaseStatus(str, enum.Enum):
    """Finite state machine for a case."""

    INGESTED = "ingested"
    TRIAGED = "triaged"
    POLICY_RESEARCHED = "policy_researched"
    AWAITING_APPROVAL = "awaiting_approval"
    AUTO_RESOLVED = "auto_resolved"
    HANDED_TO_HUMAN = "handed_to_human"
    HUMAN_HANDLING = "human_handling"
    CLOSED = "closed"
    PIPELINE_ERROR = "pipeline_error"


case_status_enum = SAEnum(
    CaseStatus,
    name="case_status",
    values_callable=lambda e: [m.value for m in e],
    native_enum=False,  # CHECK constraint, avoids DB-level enum migrations
)


class Case(Base, UUIDMixin, TimestampMixin):
    """One customer-service ticket, from ingest to close."""

    __tablename__ = "resolveai_cases"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Customer + channel context
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    customer_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")

    # Ticket body
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(16), nullable=False, default="US")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")

    # Lifecycle
    status: Mapped[CaseStatus] = mapped_column(
        case_status_enum,
        nullable=False,
        default=CaseStatus.INGESTED,
        index=True,
    )

    # Triage output
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticket_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deflection_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Resolution
    resolution_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    action_plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Cost / SLA / assignment
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_human: Mapped[str | None] = mapped_column(String(128), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Safety
    pii_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    events: Mapped[list["CaseEvent"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="CaseEvent.ts",
    )
    actions: Mapped[list["ActionAudit"]] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="ActionAudit.created_at",
    )
    csat_scores: Mapped[list["CSATScore"]] = relationship(
        back_populates="case", cascade="all, delete-orphan",
    )
    sla_breaches: Mapped[list["SLABreach"]] = relationship(
        back_populates="case", cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Wire-format case row (flat dict for the JSON API)."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "customer_id": self.customer_id,
            "customer_tier": self.customer_tier,
            "channel": self.channel,
            "subject": self.subject,
            "body": self.body,
            "order_id": self.order_id,
            "sku": self.sku,
            "jurisdiction": self.jurisdiction,
            "locale": self.locale,
            "status": self.status.value if isinstance(self.status, CaseStatus) else self.status,
            "intent": self.intent,
            "ticket_category": self.ticket_category,
            "urgency": self.urgency,
            "sentiment": self.sentiment,
            "deflection_score": self.deflection_score,
            "resolution": self.resolution_summary,
            "citations": self.citations or [],
            "action_plan": self.action_plan or {},
            "cost_usd": self.cost_usd,
            "duration_ms": self.duration_ms,
            "assigned_human": self.assigned_human,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "sla_deadline_at": self.sla_deadline_at.isoformat() if self.sla_deadline_at else None,
            "pii_flags": self.pii_flags or [],
            "risk_flags": self.risk_flags or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CaseEvent(Base, UUIDMixin):
    """Ordered, append-only timeline row for a case."""

    __tablename__ = "resolveai_case_events"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolveai_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    case: Mapped[Case] = relationship(back_populates="events")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "ts": self.ts.isoformat() if self.ts else None,
            "type": self.type,
            "actor": self.actor,
            "summary": self.summary,
            "payload": self.payload or {},
        }


class ActionAudit(Base, UUIDMixin):
    """Every refund/credit/escalate decision — append-only."""

    __tablename__ = "resolveai_action_audit"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolveai_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)  # refund|partial_refund|…
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    policy_citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    requires_approval: Mapped[bool] = mapped_column(nullable=False, default=False)
    approval_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executor: Mapped[str] = mapped_column(String(128), nullable=False, default="pipeline")
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_approval",
    )  # pending_approval|approved|executed|failed|cancelled

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "action_type in ('refund','partial_refund','replacement','credit',"
            "'apology','escalate','other')",
            name="ck_action_audit_action_type",
        ),
        CheckConstraint(
            "status in ('pending_approval','approved','executed','failed','cancelled')",
            name="ck_action_audit_status",
        ),
    )

    case: Mapped[Case] = relationship(back_populates="actions")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "action_type": self.action_type,
            "amount_usd": self.amount_usd,
            "rationale": self.rationale,
            "policy_citations": self.policy_citations or [],
            "requires_approval": self.requires_approval,
            "approval_tier": self.approval_tier,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "executor": self.executor,
            "external_id": self.external_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CSATScore(Base, UUIDMixin):
    """Predicted or actual CSAT for a closed case."""

    __tablename__ = "resolveai_csat_scores"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolveai_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # predicted|survey|agent_rating
    predicted_nps_bucket: Mapped[str | None] = mapped_column(String(16), nullable=True)
    red_flags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    __table_args__ = (
        CheckConstraint("score between 1 and 5", name="ck_csat_score_range"),
        CheckConstraint(
            "source in ('predicted','survey','agent_rating')",
            name="ck_csat_source",
        ),
        CheckConstraint(
            "predicted_nps_bucket is null or predicted_nps_bucket in "
            "('detractor','passive','promoter')",
            name="ck_csat_nps_bucket",
        ),
    )

    case: Mapped[Case] = relationship(back_populates="csat_scores")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "score": self.score,
            "source": self.source,
            "predicted_nps_bucket": self.predicted_nps_bucket,
            "red_flags": self.red_flags or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SLABreach(Base, UUIDMixin):
    """One row per SLA miss — paging + post-mortem evidence."""

    __tablename__ = "resolveai_sla_breaches"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resolveai_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sla_type: Mapped[str] = mapped_column(String(32), nullable=False)  # first_response|resolution
    breached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    minutes_overdue: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    escalated_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "sla_type in ('first_response','resolution')",
            name="ck_sla_breach_type",
        ),
    )

    case: Mapped[Case] = relationship(back_populates="sla_breaches")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "case_id": str(self.case_id),
            "sla_type": self.sla_type,
            "breached_at": self.breached_at.isoformat() if self.breached_at else None,
            "minutes_overdue": self.minutes_overdue,
            "escalated_to": self.escalated_to,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class VoCInsight(Base, UUIDMixin):
    """One Voice-of-Customer cluster — nightly Trend Miner output."""

    __tablename__ = "resolveai_voc_insights"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(String(128), nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    example_case_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    suggested_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status in ('open','acknowledged','resolved')",
            name="ck_voc_insight_status",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "cluster_id": self.cluster_id,
            "signal": self.signal,
            "case_count": self.case_count,
            "anomaly_score": self.anomaly_score,
            "example_case_ids": self.example_case_ids or [],
            "suggested_action": self.suggested_action,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TenantSettings(Base, UUIDMixin, TimestampMixin):
    """Per-tenant ResolveAI configuration."""

    __tablename__ = "resolveai_tenant_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, index=True,
    )
    approval_tiers: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "auto_ceiling_usd": 25.0,
            "t1_ceiling_usd": 250.0,
            "manager_ceiling_usd": 5000.0,
        },
    )
    sla_first_response_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    sla_resolution_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    slack_escalation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    moderation_policy_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    integrations: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {
            "stripe_mode": "mock",
            "shopify_mode": "mock",
            "zendesk_mode": "mock",
            "shipengine_mode": "mock",
        },
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_settings_tenant_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "approval_tiers": self.approval_tiers,
            "sla_first_response_minutes": self.sla_first_response_minutes,
            "sla_resolution_minutes": self.sla_resolution_minutes,
            "slack_escalation_url": self.slack_escalation_url,
            "moderation_policy_id": self.moderation_policy_id,
            "integrations": self.integrations,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
