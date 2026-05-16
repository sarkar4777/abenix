"""KnowledgeProject — tenant-scoped governance container for collections."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class CollectionVisibility(str, enum.Enum):
    """Default visibility for collections inside a project."""

    PRIVATE = "private"
    PROJECT = "project"
    TENANT = "tenant"


class KnowledgeProject(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_kproj_tenant_slug"),
        Index("ix_kproj_tenant_created", "tenant_id", "created_at"),
    )

    # Resource-share opt-in: lets the polymorphic ResourceShare table
    # treat projects as a shareable resource with the same VIEW/EXECUTE/EDIT
    # ladder used elsewhere.
    RESOURCE_KIND = "knowledge_project"

    name: Mapped[str] = mapped_column(String(255))
    # `slug` is the stable string used by integrations (e.g. the example app
    # bootstraps "example_app", SaudiTourism bootstraps "sauditourism").
    # Unique per tenant so two integrations in the same tenant can't
    # collide.
    slug: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")

    # Optional FK to the active ontology schema (Phase 3). Nullable so
    ontology_schema_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
    )
