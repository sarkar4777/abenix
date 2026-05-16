"""Atlas — unified ontology + knowledge-base canvas"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "u1v2w3x4y5z6"
down_revision = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "atlas_graphs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_collections.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "name", sa.String(255), nullable=False, server_default="Untitled Atlas"
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_atlas_graphs_tenant_updated", "atlas_graphs", ["tenant_id", "updated_at"]
    )

    atlas_node_kind = postgresql.ENUM(
        "concept",
        "instance",
        "document",
        "property",
        name="atlas_node_kind",
        create_type=False,
    )
    atlas_node_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "atlas_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_graphs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("kind", atlas_node_kind, nullable=False, server_default="concept"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("position_x", sa.Float(), nullable=True),
        sa.Column("position_y", sa.Float(), nullable=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("source", sa.String(40), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_atlas_nodes_graph_label", "atlas_nodes", ["graph_id", "label"])
    op.create_index("ix_atlas_nodes_graph_kind", "atlas_nodes", ["graph_id", "kind"])

    op.create_table(
        "atlas_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_graphs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "from_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_node_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False, server_default="related_to"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cardinality_from", sa.String(16), nullable=True),
        sa.Column("cardinality_to", sa.String(16), nullable=True),
        sa.Column(
            "inverse_edge_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_edges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_directed", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "properties",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(40), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_atlas_edges_graph_label", "atlas_edges", ["graph_id", "label"])
    op.create_index("ix_atlas_edges_from", "atlas_edges", ["from_node_id"])
    op.create_index("ix_atlas_edges_to", "atlas_edges", ["to_node_id"])

    op.create_table(
        "atlas_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "graph_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("atlas_graphs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("auto", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_atlas_snapshots_graph_created",
        "atlas_snapshots",
        ["graph_id", "created_at"],
    )
    op.create_unique_constraint(
        "uq_atlas_snapshot_version", "atlas_snapshots", ["graph_id", "version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_atlas_snapshot_version", "atlas_snapshots", type_="unique")
    op.drop_index("ix_atlas_snapshots_graph_created", table_name="atlas_snapshots")
    op.drop_table("atlas_snapshots")

    op.drop_index("ix_atlas_edges_to", table_name="atlas_edges")
    op.drop_index("ix_atlas_edges_from", table_name="atlas_edges")
    op.drop_index("ix_atlas_edges_graph_label", table_name="atlas_edges")
    op.drop_table("atlas_edges")

    op.drop_index("ix_atlas_nodes_graph_kind", table_name="atlas_nodes")
    op.drop_index("ix_atlas_nodes_graph_label", table_name="atlas_nodes")
    op.drop_table("atlas_nodes")

    sa.Enum(name="atlas_node_kind").drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_atlas_graphs_tenant_updated", table_name="atlas_graphs")
    op.drop_table("atlas_graphs")
