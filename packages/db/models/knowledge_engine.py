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
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class CognifyStatus(str, enum.Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    RESOLVING = "resolving"
    GRAPHING = "graphing"
    EMBEDDING = "embedding"
    COMPLETE = "complete"
    FAILED = "failed"
    STOPPED = "stopped"


class CognifyJob(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "cognify_jobs"
    __table_args__ = (
        Index("ix_cognify_jobs_kb_status", "kb_id", "status"),
        Index("ix_cognify_jobs_tenant_created", "tenant_id", "created_at"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    status: Mapped[CognifyStatus] = mapped_column(
        Enum(CognifyStatus, name="cognify_status"), default=CognifyStatus.PENDING
    )
    documents_processed: Mapped[int] = mapped_column(Integer, default=0)
    entities_extracted: Mapped[int] = mapped_column(Integer, default=0)
    entities_merged: Mapped[int] = mapped_column(Integer, default=0)
    relationships_extracted: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    # Per-provider subtotals so the UI can show "Anthropic $X + OpenAI
    # fallback $Y". These sum to cost_usd.
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
    duration_seconds: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    documents_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_processed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_skipped: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_failed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    entities_written: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    entities_failed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    relationships_written: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    relationships_failed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    off_ontology_dropped: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    budget_usd: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    stop_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CognifyJobDocument(Base):
    """One document inside a job. The worker takes these one at a time."""

    __tablename__ = "cognify_job_documents"
    __table_args__ = (Index("ix_cognify_job_documents_status", "job_id", "status"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cognify_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # pending, queued, running, done, failed, stopped
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False
    )
    chunks_total: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_done: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_skipped: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    chunks_failed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CognifyChunk(Base):
    """What a rerun skips. Extraction output waits here until the graph holds it."""

    __tablename__ = "cognify_chunks"
    __table_args__ = (
        Index(
            "ix_cognify_chunks_pending",
            "kb_id",
            "document_id",
            postgresql_where=text("status = 'extracted'"),
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    chunk_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    chunk_index: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # extracted means paid for and not yet in the graph, done means in the graph
    status: Mapped[str] = mapped_column(
        String(16), default="done", server_default="done", nullable=False
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tokens_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    cost_usd: Mapped[float] = mapped_column(
        Numeric(12, 6), default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GraphEntity(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "graph_entities"
    __table_args__ = (
        Index(
            "ix_graph_entities_kb_name",
            "kb_id",
            "canonical_name",
            unique=True,
        ),
        Index("ix_graph_entities_kb_type", "kb_id", "entity_type"),
        Index("ix_graph_entities_kb_concept", "kb_id", "atlas_concept_id"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    canonical_name: Mapped[str] = mapped_column(String(500))
    entity_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_doc_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    neo4j_node_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, default=1)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # the Atlas concept this entity is an instance of, when an ontology governs the KB
    atlas_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    atlas_graph_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class GraphRelationship(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "graph_relationships"
    __table_args__ = (
        Index(
            "ix_graph_rels_source_target",
            "source_entity_id",
            "target_entity_id",
        ),
        Index("ix_graph_rels_kb_type", "kb_id", "relationship_type"),
        Index(
            "uq_graph_rels_triple",
            "kb_id",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            unique=True,
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_entities.id")
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("graph_entities.id")
    )
    relationship_type: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_doc_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    neo4j_rel_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    weight: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), default=1.0)
    atlas_edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class CognifyReport(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cognify_reports"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cognify_jobs.id"), unique=True
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    entities_by_type: Mapped[dict] = mapped_column(JSONB)
    top_entities: Mapped[dict] = mapped_column(JSONB)
    relationship_types: Mapped[dict] = mapped_column(JSONB)
    new_entities: Mapped[int] = mapped_column(Integer, default=0)
    merged_entities: Mapped[int] = mapped_column(Integer, default=0)
    new_relationships: Mapped[int] = mapped_column(Integer, default=0)
    strengthened_relationships: Mapped[int] = mapped_column(Integer, default=0)
    documents_processed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    processing_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RetrievalFeedback(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "retrieval_feedback"
    __table_args__ = (
        Index("ix_retrieval_feedback_kb_mode", "kb_id", "search_mode"),
        Index("ix_retrieval_feedback_kb_exec", "kb_id", "execution_id"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True
    )
    query: Mapped[str] = mapped_column(Text)
    search_mode: Mapped[str] = mapped_column(String(50))
    result_entity_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_chunk_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_count: Mapped[int] = mapped_column(Integer, default=0)


class RetrievalMetric(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "retrieval_metrics"
    __table_args__ = (
        Index(
            "ix_retrieval_metrics_kb_mode_period",
            "kb_id",
            "search_mode",
            "period_start",
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search_mode: Mapped[str] = mapped_column(String(50))
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_rating: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    p95_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    positive_feedback: Mapped[int] = mapped_column(Integer, default=0)
    negative_feedback: Mapped[int] = mapped_column(Integer, default=0)
    graph_hops_used: Mapped[int] = mapped_column(Integer, default=0)
    entities_in_results: Mapped[int] = mapped_column(Integer, default=0)


class MemifyLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "memify_logs"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(50))
    nodes_pruned: Mapped[int] = mapped_column(Integer, default=0)
    edges_pruned: Mapped[int] = mapped_column(Integer, default=0)
    edges_strengthened: Mapped[int] = mapped_column(Integer, default=0)
    edges_weakened: Mapped[int] = mapped_column(Integer, default=0)
    facts_derived: Mapped[int] = mapped_column(Integer, default=0)
    entities_merged: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
