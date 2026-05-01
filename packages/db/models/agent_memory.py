"""Agent Memory model — persistent factual/procedural/episodic memory for agents."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, UUIDMixin


class MemoryType(str, enum.Enum):
    FACTUAL = "factual"  # Facts the agent has learned (e.g., "user prefers CSV format")
    PROCEDURAL = "procedural"  # How-to knowledge (e.g., "to deploy, run X then Y")
    EPISODIC = (
        "episodic"  # Past event summaries (e.g., "last migration failed at step 3")
    )


class AgentMemory(UUIDMixin, TenantMixin, Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_agent_key", "agent_id", "key"),
        Index("ix_agent_memories_agent_type", "agent_id", "memory_type"),
        Index("ix_agent_memories_tenant_agent", "tenant_id", "agent_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), index=True
    )
    key: Mapped[str] = mapped_column(String(500))
    value: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[MemoryType] = mapped_column(
        Enum(MemoryType, name="memory_type", create_type=False),
        default=MemoryType.FACTUAL,
    )
    importance: Mapped[int] = mapped_column(Integer, default=5)  # 1-10 scale
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
