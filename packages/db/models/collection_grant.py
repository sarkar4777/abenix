"""Per-collection grants for agents and users."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, UUIDMixin


class CollectionPermission(str, enum.Enum):
    """Permission ladder for collection access."""

    READ = "READ"
    WRITE = "WRITE"
    ADMIN = "ADMIN"


# Permission rank for "at least" comparisons in the runtime path.
PERMISSION_RANK = {
    CollectionPermission.READ: 0,
    CollectionPermission.WRITE: 1,
    CollectionPermission.ADMIN: 2,
}


class AgentCollectionGrant(UUIDMixin, Base):
    """Junction: which agents can use which collections, at what level."""

    __tablename__ = "agent_collection_grants"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "collection_id",
            name="uq_agent_collection_grant",
        ),
        # Hot path: "what collections can agent X read?" — runs on every
        # tool call. Index on agent_id is the workhorse.
        Index("ix_agent_collection_grants_agent", "agent_id"),
        Index("ix_agent_collection_grants_collection", "collection_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
    )
    # FK target is `knowledge_collections.id` — the table was renamed
    # by migration r8s9t0u1v2w3 to align with v2 vocabulary.
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
    )
    permission: Mapped[CollectionPermission] = mapped_column(
        Enum(
            CollectionPermission,
            name="collection_permission",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=CollectionPermission.READ,
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class UserCollectionGrant(UUIDMixin, Base):
    """Junction: which users can see/edit which collections."""

    __tablename__ = "user_collection_grants"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "collection_id",
            name="uq_user_collection_grant",
        ),
        Index("ix_user_collection_grants_user", "user_id"),
        Index("ix_user_collection_grants_collection", "collection_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    collection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_collections.id", ondelete="CASCADE"),
    )
    permission: Mapped[CollectionPermission] = mapped_column(
        Enum(
            CollectionPermission,
            name="collection_permission",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=CollectionPermission.READ,
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
