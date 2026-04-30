"""Pipeline State — persistent key-value store for cross-run pipeline data."""

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class PipelineState(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Persistent key-value store scoped to a pipeline agent."""

    __tablename__ = "pipeline_states"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, default={})

    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_pipeline_state_agent_key"),
        Index("ix_pipeline_state_agent", "agent_id"),
    )
