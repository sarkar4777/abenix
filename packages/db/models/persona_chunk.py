import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, REAL, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class PersonaChunk(UUIDMixin, Base):
    """One embedded chunk of a persona item, searched only by its owner."""

    __tablename__ = "persona_chunks"
    __table_args__ = (
        Index("ix_persona_chunks_owner_scope", "tenant_id", "user_id", "persona_scope"),
        Index("ix_persona_chunks_item", "item_id"),
    )

    # real[] rather than vector(1536) so create_all never needs the extension, search casts to vector
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persona_items.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    persona_scope: Mapped[str] = mapped_column(String(80))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(ARRAY(REAL))
    embedding_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
