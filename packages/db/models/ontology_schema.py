"""OntologySchema — typing prior + governance for a KnowledgeProject."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, UUIDMixin


class OntologySchema(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ontology_schemas"
    __table_args__ = (
        # One active version per (project, version_number). Schema
        # editor calls bump version and create a new row rather than
        # mutating in place — gives us a free history + rollback.
        UniqueConstraint("project_id", "version", name="uq_ontology_proj_version"),
        Index("ix_ontology_schemas_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_projects.id", ondelete="CASCADE"),
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(String(2000), default="")
    entity_types: Mapped[list] = mapped_column(JSONB, default=list)
    relationship_types: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
