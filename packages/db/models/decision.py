"""Decision models: versioned, bitemporal business rules evaluated by the ZEN engine."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, UUIDMixin

# draft -> proposed -> approved -> published -> superseded | retired, or proposed -> rejected
VERSION_STATES = (
    "draft",
    "proposed",
    "approved",
    "rejected",
    "published",
    "superseded",
    "retired",
)


class DecisionModel(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "decision_models"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_decision_model_key"),
    )

    key: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    risk_tier: Mapped[str] = mapped_column(String(16), default="low")
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    # none | sampled | all
    log_mode: Mapped[str] = mapped_column(String(16), default="none")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DecisionVersion(UUIDMixin, TenantMixin, Base):
    """Immutable once proposed. A correction is a new version."""

    __tablename__ = "decision_versions"
    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_decision_version"),
        Index("ix_decision_versions_model_state", "model_id", "state"),
    )

    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decision_models.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="draft")
    # the builder document, null when the version was authored in the flow view
    authoring: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    required_facts: Mapped[list] = mapped_column(JSONB, default=list)
    fact_types: Mapped[dict] = mapped_column(JSONB, default=dict)
    reference_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    # valid time: when the rules apply to the regulated activity
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # each later change to valid_to, {"from", "to", "at"}, so known_at queries see the old end
    valid_to_history: Mapped[list] = mapped_column(JSONB, default=list)
    # recorded time: when the platform learned or approved it
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    change_note: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # optimistic lock for draft saves, sent and checked as an ETag
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    editing_by: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    proposed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DecisionTest(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A golden case: these facts must give this result."""

    __tablename__ = "decision_tests"

    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_models.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
    expected_outcome: Mapped[str] = mapped_column(String(32), default="decided")
    expected: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    # exact, or subset where extra result keys are ignored
    match_mode: Mapped[str] = mapped_column(
        String(16), default="exact", server_default="exact"
    )
    as_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class ReferenceSet(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A named, versioned list such as product codes, snapshotted into decisions at compile time."""

    __tablename__ = "reference_sets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_reference_set_key"),
    )

    key: Mapped[str] = mapped_column(String(160))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    values: Mapped[list] = mapped_column(JSONB, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class ReferenceSetVersion(UUIDMixin, Base):
    __tablename__ = "reference_set_versions"
    __table_args__ = (
        UniqueConstraint("set_id", "version", name="uq_reference_set_version"),
    )

    set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reference_sets.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    values: Mapped[list] = mapped_column(JSONB, default=list)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DecisionEvaluation(Base):
    """A persisted, reproducible evaluation. Written only when asked for, or by log mode."""

    __tablename__ = "decision_evaluations"
    __table_args__ = (
        Index("ix_decision_eval_model_time", "tenant_id", "model_id", "created_at"),
        Index(
            "uq_decision_eval_idem",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), default=uuid.uuid4, unique=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    facts: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    applied_rules: Mapped[list] = mapped_column(JSONB, default=list)
    trace_hash: Mapped[str] = mapped_column(String(64), default="")
    as_of: Mapped[str | None] = mapped_column(String(32), nullable=True)
    known_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    caller: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
