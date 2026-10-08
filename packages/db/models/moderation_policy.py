"""ModerationPolicy — per-tenant content-moderation rules."""

from __future__ import annotations

import enum
import uuid

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class ModerationAction(str, enum.Enum):
    """What the gate does when a category is triggered."""

    ALLOW = "allow"  # Pass through. Default for un-triggered categories.
    FLAG = "flag"  # Allow through, log + notify. Non-blocking.
    REDACT = "redact"  # Mask offending spans with ████, allow through.
    HOLD = "hold"  # Hold for a human reviewer to release, redact or reject.
    BLOCK = "block"  # Refuse the request. Raises ModerationBlocked.


class ModerationEventOutcome(str, enum.Enum):
    """What actually happened on a moderation_events row."""

    ALLOWED = "allowed"
    FLAGGED = "flagged"
    REDACTED = "redacted"
    BLOCKED = "blocked"
    HELD = "held"  # Waiting for a human reviewer.
    ERROR = "error"  # Moderation provider call itself failed.


class ModerationPolicy(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "moderation_policies"
    __table_args__ = (
        Index("ix_moderation_policies_tenant_active", "tenant_id", "is_active"),
    )

    # Human-facing identity. `name` is unique per tenant by convention
    # but not enforced at the DB level — two policies can share a name
    # across tenants without colliding.
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Only one active policy per tenant is applied by the gate. Toggling
    # this flag (rather than deleting) preserves historical events'
    # policy_id FK.
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    # Gate wiring — which hook points apply the policy.
    pre_llm: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    post_llm: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    on_tool_output: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Moderation provider + model. `omni-moderation-latest` supports
    # multi-modal; `text-moderation-latest` is text-only legacy.
    provider: Mapped[str] = mapped_column(
        String(40), default="openai", server_default="openai"
    )
    provider_model: Mapped[str] = mapped_column(
        String(80),
        default="omni-moderation-latest",
        server_default="omni-moderation-latest",
    )

    # Thresholds per category. Any category whose score exceeds its
    # threshold triggers the category-specific action below. Missing
    # categories default to `default_threshold`.
    # Shape: {"hate": 0.5, "violence": 0.6, "sexual/minors": 0.1, ...}
    thresholds: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    default_threshold: Mapped[float] = mapped_column(
        default=0.5,
        server_default="0.5",
    )

    # Per-category action override. Categories without an explicit
    # override use `default_action`. Values are ModerationAction enum.
    # Shape: {"hate": "block", "harassment": "flag", "sexual/minors": "block"}
    category_actions: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    default_action: Mapped[ModerationAction] = mapped_column(
        Enum(
            ModerationAction,
            name="moderation_action",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=ModerationAction.BLOCK,
        server_default="block",
    )

    # Custom regex patterns additive to the provider check. Each pattern
    # is matched case-insensitively. Match triggers `default_action`.
    # Shape: ["\\bcodename[-_ ]?aurora\\b", "internal\\s+roadmap"]
    custom_patterns: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    # Redaction replacement. When action=REDACT, the offending spans are
    # replaced with this string. Default █ lets humans spot the mask.
    redaction_mask: Mapped[str] = mapped_column(
        String(40), default="█████", server_default="█████"
    )

    # Fail-closed switch — when the moderation provider returns an error
    # (quota exhausted, network blip, key revoked), block instead of
    # silently allowing. Default false preserves legacy fail-open
    # behaviour; the seeded ABENIX default flips this to true.
    fail_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # What happens to held content nobody decided on in time.
    hold_timeout_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default=text("60")
    )
    hold_timeout_action: Mapped[str] = mapped_column(
        String(16), nullable=False, default="reject", server_default="reject"
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )


class ModerationEvent(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "moderation_events"
    __table_args__ = (
        Index("ix_moderation_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_moderation_events_outcome", "outcome"),
        Index("ix_moderation_events_execution", "execution_id"),
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("moderation_policies.id"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )

    # Correlation to an agent execution (if any). NULL for direct API
    # calls to /api/moderation/vet.
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    # Where the check fired: `api_vet` | `pre_llm` | `post_llm` |
    # `tool_output` | `agent_tool`.
    source: Mapped[str] = mapped_column(String(40), default="api_vet")

    outcome: Mapped[ModerationEventOutcome] = mapped_column(
        Enum(
            ModerationEventOutcome,
            name="moderation_event_outcome",
            values_callable=lambda e: [m.value for m in e],
        ),
    )

    # Raw content hash (SHA-256 hex prefix) so we can detect repeat
    # offenders without storing potentially-sensitive PII in the clear.
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # What the provider said — full category scores + flagged flags.
    # Shape: {"flagged": true, "categories": {...}, "category_scores": {...},
    #         "triggered": ["hate", "harassment"], "action": "block"}
    provider_response: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )

    # Which categories the gate actually acted on (may be narrower than
    # provider_response.triggered if per-category actions were ALLOW).
    acted_categories: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    # Latency of the provider call in milliseconds.
    latency_ms: Mapped[int] = mapped_column(default=0, server_default="0")


class ModerationReview(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """Content a HOLD policy stopped, waiting for or carrying a human decision."""

    __tablename__ = "moderation_reviews"
    __table_args__ = (
        Index(
            "ix_moderation_reviews_queue",
            "tenant_id",
            "status",
            "priority",
            "created_at",
        ),
        Index("ix_moderation_reviews_due", "status", "expires_at"),
        Index("ix_moderation_reviews_tenant_decided", "tenant_id", "decided_at"),
        Index("ix_moderation_reviews_user", "user_id", "status"),
        Index("ix_moderation_reviews_execution", "execution_id"),
    )

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("moderation_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # the chat message that stands in for the held content
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source: Mapped[str] = mapped_column(String(40), default="pre_llm")

    # pending | released | redacted | rejected | auto_released | auto_rejected
    status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending"
    )
    # 3 high, 2 medium, 1 low
    priority: Mapped[int] = mapped_column(
        SmallInteger, default=1, server_default=text("1")
    )
    categories: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    category_scores: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    # [{"start", "end", "category"}] over the held text
    spans: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")

    # Full text, encrypted when the KEK is set, gone after the retention window.
    held_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_length: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # matched spans masked, kept with the decision record
    masked_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    redaction_mask: Mapped[str] = mapped_column(
        String(40), default="█████", server_default="█████"
    )
    content_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    timeout_action: Mapped[str] = mapped_column(
        String(16), default="reject", server_default="reject"
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # reviewers told about it, set once by whoever announces first
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # a released message went on to the agent
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # [{"at", "by", "action", "note"}]
    history: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
