from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class MeetingStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    AUTHORIZED = "authorized"  # user has authorized the bot + set scope
    LIVE = "live"
    DONE = "done"
    KILLED = "killed"  # user revoked mid-meeting
    FAILED = "failed"


class MeetingProvider(str, enum.Enum):
    LIVEKIT = "livekit"
    TEAMS = "teams"
    ZOOM = "zoom"


class Meeting(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        Index("ix_meetings_user_status", "user_id", "status"),
        Index("ix_meetings_scheduled", "scheduled_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300))
    provider: Mapped[str] = mapped_column(
        String(20), default=MeetingProvider.LIVEKIT.value
    )
    room: Mapped[str] = mapped_column(String(500))
    join_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(30), default=MeetingStatus.SCHEDULED.value, index=True
    )

    # User-declared scope for the bot
    scope_allow: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    scope_defer: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    persona_scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    display_name: Mapped[str] = mapped_column(String(200), default="Abenix Assistant")

    # Resolved at end-of-meeting
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_count: Mapped[int] = mapped_column(Integer, default=0)
    decision_count: Mapped[int] = mapped_column(Integer, default=0)
    deferral_count: Mapped[int] = mapped_column(Integer, default=0)

    notes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MeetingDeferral(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """Persistent record of a question the bot deferred to the user."""

    __tablename__ = "meeting_deferrals"
    __table_args__ = (
        Index("ix_meeting_deferrals_meeting", "meeting_id", "created_at"),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"  # pending | answered | timed_out | cancelled
    )
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PersonaItem(UUIDMixin, TenantMixin, TimestampMixin, Base):
    """Records every piece of persona-scoped data fed into the ring-fenced KB."""

    __tablename__ = "persona_items"
    __table_args__ = (Index("ix_persona_items_user_scope", "user_id", "persona_scope"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id"),
        nullable=True,
        index=True,
    )
    persona_scope: Mapped[str] = mapped_column(String(80), default="self", index=True)
    kind: Mapped[str] = mapped_column(
        String(30), default="note"
    )  # note | file | meeting_context
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | indexed | failed
    pinecone_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
