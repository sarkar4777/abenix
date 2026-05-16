import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from models.knowledge_project import CollectionVisibility


class KBStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentStatus(str, enum.Enum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeBase(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """A KnowledgeBase row IS a Collection in v2 terminology."""

    __tablename__ = "knowledge_collections"
    __table_args__ = (
        Index("ix_kb_tenant_created", "tenant_id", "created_at"),
        Index("ix_kb_project", "project_id"),
    )

    RESOURCE_KIND = "knowledge_collection"

    # v2: collections live inside a project. Nullable for legacy rows
    # during the migration window; backfilled by the Phase 1 migration
    # to a "Default" project per tenant.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_projects.id"),
        nullable=True,
    )
    default_visibility: Mapped[CollectionVisibility] = mapped_column(
        Enum(
            CollectionVisibility,
            name="collection_visibility",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=CollectionVisibility.PROJECT,
    )

    # Legacy single-agent owner. Kept for backwards-compat reads; new
    # code should use AgentCollectionGrant. The Phase 1 migration
    # backfills a grant row for every KB that has agent_id set so the
    # new runtime path returns the same set of collections.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True, index=True
    )
    # created_by lets ResourceShare/permission helpers treat KBs the
    # same way they treat agents/ml_models. Nullable for legacy rows.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-3-small"
    )
    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    # v2: which vector backend stores this collection's embeddings.
    # Defaults to pinecone for legacy rows; new collections default to
    # pgvector via the API layer (Phase 5 will let users pick).
    vector_backend: Mapped[str] = mapped_column(
        String(20),
        default="pinecone",
    )
    status: Mapped[KBStatus] = mapped_column(
        Enum(KBStatus, name="kb_status"), default=KBStatus.PROCESSING
    )
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    graph_enabled: Mapped[bool] = mapped_column(default=False)
    entity_count: Mapped[int] = mapped_column(Integer, default=0)
    relationship_count: Mapped[int] = mapped_column(Integer, default=0)
    last_cognified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agent: Mapped["Agent | None"] = relationship(back_populates="knowledge_bases")
    documents: Mapped[list["Document"]] = relationship(back_populates="knowledge_base")


class Document(UUIDMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_kb_status", "kb_id", "status"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), index=True
    )
    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(50))
    file_size: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status"), default=DocumentStatus.PROCESSING
    )
    storage_url: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")


from models.agent import Agent  # noqa: E402
