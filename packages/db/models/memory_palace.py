"""MemPalace hierarchical memory models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, UUIDMixin


class MemoryWing(UUIDMixin, TenantMixin, Base):
    """Top-level grouping: a person, project, or topic."""

    __tablename__ = "memory_wings"
    __table_args__ = (Index("ix_memory_wings_agent", "agent_id", "tenant_id"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # person, project, topic
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    halls: Mapped[list["MemoryHall"]] = relationship(
        back_populates="wing", cascade="all, delete-orphan"
    )


class HallType(str, enum.Enum):
    FACTUAL = "factual"
    PROCEDURAL = "procedural"
    EPISODIC = "episodic"
    EMOTIONAL = "emotional"
    DECISION = "decision"


class MemoryHall(UUIDMixin, Base):
    """Category within a wing — type of memory."""

    __tablename__ = "memory_halls"

    wing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_wings.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255))
    hall_type: Mapped[HallType] = mapped_column(
        Enum(HallType, name="hall_type"), default=HallType.FACTUAL
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    wing: Mapped[MemoryWing] = relationship(back_populates="halls")
    rooms: Mapped[list["MemoryRoom"]] = relationship(
        back_populates="hall", cascade="all, delete-orphan"
    )


class MemoryRoom(UUIDMixin, Base):
    """A specific idea, concept, or memory unit."""

    __tablename__ = "memory_rooms"
    __table_args__ = (Index("ix_memory_rooms_hall", "hall_id"),)

    hall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_halls.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(500))
    summary_aaak: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # AAAK-compressed summary
    full_content: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=5)  # 1-10
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # Pinecone vector ID
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    hall: Mapped[MemoryHall] = relationship(back_populates="rooms")
    drawers: Mapped[list["MemoryDrawer"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class MemoryDrawer(UUIDMixin, Base):
    """Original verbatim content stored for fidelity."""

    __tablename__ = "memory_drawers"

    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_rooms.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    room: Mapped[MemoryRoom] = relationship(back_populates="drawers")


class MemoryEntity(UUIDMixin, Base):
    """Knowledge graph node for agent memory."""

    __tablename__ = "memory_entities"
    __table_args__ = (Index("ix_memory_entities_agent", "agent_id", "name"),)

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    name: Mapped[str] = mapped_column(String(500))
    entity_type: Mapped[str] = mapped_column(
        String(100)
    )  # person, company, concept, event
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MemoryRelation(UUIDMixin, Base):
    """Knowledge graph edge between memory entities."""

    __tablename__ = "memory_relations"

    from_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE")
    )
    to_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_entities.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(
        String(100)
    )  # WORKS_FOR, CAUSED, RELATED_TO
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    properties: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
