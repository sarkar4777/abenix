"""Atlas — unified ontology + knowledge-base canvas data model."""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TenantMixin, TimestampMixin, UUIDMixin


class AtlasNodeKind(str, enum.Enum):
    """What kind of thing the node represents on the canvas."""

    CONCEPT = "concept"
    INSTANCE = "instance"
    DOCUMENT = "document"
    PROPERTY = "property"


class AtlasGraph(UUIDMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "atlas_graphs"
    __table_args__ = (
        Index("ix_atlas_graphs_tenant_updated", "tenant_id", "updated_at"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="Untitled Atlas")
    description: Mapped[str] = mapped_column(Text, default="")
    # Optional binding to a knowledge collection — when set, drop-to-extract
    # uploads land in this collection and document nodes can deep-link to
    # the chunks they came from.
    kb_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_collections.id"), nullable=True, index=True
    )
    # Monotonic per-graph version. Increments on any node/edge mutation
    # so the frontend can detect stale snapshots and bail out gracefully.
    version: Mapped[int] = mapped_column(Integer, default=1)
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    # `settings` is the catch-all: layout mode, theme, default node styling,
    # constraint presets, etc. Free-form so we can ship features without a
    # migration treadmill.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)

    nodes: Mapped[list["AtlasNode"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan", passive_deletes=True,
    )
    edges: Mapped[list["AtlasEdge"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan", passive_deletes=True,
    )
    snapshots: Mapped[list["AtlasSnapshot"]] = relationship(
        back_populates="graph", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AtlasSnapshot.created_at",
    )


class AtlasNode(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "atlas_nodes"
    __table_args__ = (
        Index("ix_atlas_nodes_graph_label", "graph_id", "label"),
        Index("ix_atlas_nodes_graph_kind", "graph_id", "kind"),
    )

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_graphs.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(255))
    kind: Mapped[AtlasNodeKind] = mapped_column(
        Enum(AtlasNodeKind, name="atlas_node_kind", values_callable=lambda e: [m.value for m in e]),
        default=AtlasNodeKind.CONCEPT,
    )
    description: Mapped[str] = mapped_column(Text, default="")
    # Free-form attributes — name, type, default, constraints, etc.
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Layout in the editor. Stored as Float so React Flow can read it
    # back without a JSON detour; nullable so freshly-extracted ghost
    # nodes can ride a layout pass before they're committed.
    position_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Optional pointer to the KB document this node was extracted from
    # (or that it represents, when kind=document). Lets the Document
    # lens jump straight to the source chunks.
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True, index=True
    )
    # Provenance for the agent ghost cursor: did a human draw this, did
    # extraction propose it, was it imported from a starter ontology?
    source: Mapped[str] = mapped_column(String(40), default="user")
    # Confidence is set by the extraction agent when source != "user";
    # the canvas uses it to dim low-confidence ghost nodes.
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # `tags` is a small string array for filter chips.
    tags: Mapped[list] = mapped_column(JSONB, default=list)

    graph: Mapped[AtlasGraph] = relationship(back_populates="nodes")


class AtlasEdge(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "atlas_edges"
    __table_args__ = (
        Index("ix_atlas_edges_graph_label", "graph_id", "label"),
        Index("ix_atlas_edges_from", "from_node_id"),
        Index("ix_atlas_edges_to", "to_node_id"),
    )

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_graphs.id", ondelete="CASCADE"), index=True
    )
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
    )
    label: Mapped[str] = mapped_column(String(255), default="related_to")
    description: Mapped[str] = mapped_column(Text, default="")
    # Cardinality on each side, modelled the same way UML does — "1",
    # "0..1", "1..*", "*", or any string the operator types in. We don't
    # validate — Atlas favours expressivity over rigidity.
    cardinality_from: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cardinality_to: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Optional pointer to an inverse edge in the same graph. The ghost
    # cursor proposes pairs (`employs` / `employed_by`) and links them
    # via this column for one-step navigation.
    inverse_edge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_edges.id", ondelete="SET NULL"), nullable=True,
    )
    is_directed: Mapped[bool] = mapped_column(Boolean, default=True)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="user")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    graph: Mapped[AtlasGraph] = relationship(back_populates="edges")


class AtlasSnapshot(UUIDMixin, TimestampMixin, Base):
    """A point-in-time materialisation of a graph for the time slider."""

    __tablename__ = "atlas_snapshots"
    __table_args__ = (
        Index("ix_atlas_snapshots_graph_created", "graph_id", "created_at"),
        UniqueConstraint("graph_id", "version", name="uq_atlas_snapshot_version"),
    )

    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("atlas_graphs.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )
    auto: Mapped[bool] = mapped_column(Boolean, default=True)

    graph: Mapped[AtlasGraph] = relationship(back_populates="snapshots")
