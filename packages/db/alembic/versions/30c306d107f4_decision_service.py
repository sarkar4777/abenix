"""Decision service: models, versions, golden tests, reference sets, evaluations, approval policy.

Revision ID: 30c306d107f4
Revises: c1d2e3f4a5b6
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "30c306d107f4"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB()


# The API's startup create_all can build new tables before this runs, so every step tolerates them.
def _insp():
    return sa.inspect(op.get_bind())


def _create_table(name: str, *cols, **kw) -> None:
    if not _insp().has_table(name):
        op.create_table(name, *cols, **kw)


def _add_column(table: str, col: sa.Column) -> None:
    if col.name not in {c["name"] for c in _insp().get_columns(table)}:
        op.add_column(table, col)


def _create_index(name: str, table: str, cols: list[str], **kw) -> None:
    if name not in {i["name"] for i in _insp().get_indexes(table)}:
        op.create_index(name, table, cols, **kw)


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=None if nullable else sa.func.now(),
        nullable=nullable,
    )


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
    )


def upgrade() -> None:
    _create_table(
        "decision_models",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("risk_tier", sa.String(16), nullable=False, server_default="low"),
        sa.Column("tags", _JSONB, nullable=False, server_default="[]"),
        sa.Column("log_mode", sa.String(16), nullable=False, server_default="none"),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("archived_at", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_decision_model_key"),
    )
    _create_table(
        "decision_versions",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "model_id",
            _UUID,
            sa.ForeignKey("decision_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("authoring", _JSONB, nullable=True),
        sa.Column("content", _JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("required_facts", _JSONB, nullable=False, server_default="[]"),
        sa.Column("fact_types", _JSONB, nullable=False, server_default="{}"),
        sa.Column("reference_versions", _JSONB, nullable=False, server_default="{}"),
        _ts("valid_from", nullable=True),
        _ts("valid_to", nullable=True),
        sa.Column("valid_to_history", _JSONB, nullable=False, server_default="[]"),
        _ts("recorded_at"),
        _ts("published_at", nullable=True),
        _ts("superseded_at", nullable=True),
        sa.Column("change_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("provenance", _JSONB, nullable=True),
        sa.Column("validation", _JSONB, nullable=True),
        sa.Column("approval_id", _UUID, nullable=True),
        sa.Column("base_version_id", _UUID, nullable=True),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "author_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("editing_by", _JSONB, nullable=True),
        sa.Column("proposed_by", _UUID, nullable=True),
        _ts("proposed_at", nullable=True),
        sa.Column("published_by", _UUID, nullable=True),
        _ts("updated_at"),
        sa.UniqueConstraint("model_id", "version", name="uq_decision_version"),
    )
    _create_index(
        "ix_decision_versions_model_state", "decision_versions", ["model_id", "state"]
    )
    _create_table(
        "decision_tests",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column(
            "model_id",
            _UUID,
            sa.ForeignKey("decision_models.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("facts", _JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "expected_outcome", sa.String(32), nullable=False, server_default="decided"
        ),
        sa.Column("expected", _JSONB, nullable=True),
        sa.Column("as_of", sa.String(32), nullable=True),
        sa.Column("created_by", _UUID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    _create_table(
        "reference_sets",
        sa.Column("id", _UUID, primary_key=True),
        _tenant(),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("values", _JSONB, nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_by", _UUID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_reference_set_key"),
    )
    _create_table(
        "reference_set_versions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "set_id",
            _UUID,
            sa.ForeignKey("reference_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("values", _JSONB, nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", _UUID, nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("set_id", "version", name="uq_reference_set_version"),
    )
    _create_table(
        "decision_evaluations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_id", _UUID, nullable=False, unique=True),
        sa.Column("tenant_id", _UUID, nullable=False, index=True),
        sa.Column("model_id", _UUID, nullable=False),
        sa.Column("version_id", _UUID, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("facts", _JSONB, nullable=False),
        sa.Column("result", _JSONB, nullable=True),
        sa.Column("applied_rules", _JSONB, nullable=False, server_default="[]"),
        sa.Column("trace_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("as_of", sa.String(32), nullable=True),
        _ts("known_at", nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("caller", _JSONB, nullable=True),
        _ts("created_at"),
    )
    _create_index(
        "ix_decision_eval_model_time",
        "decision_evaluations",
        ["tenant_id", "model_id", "created_at"],
    )
    _create_index(
        "uq_decision_eval_idem",
        "decision_evaluations",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _add_column("approvals", sa.Column("policy", _JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("approvals", "policy")
    op.drop_index("uq_decision_eval_idem", table_name="decision_evaluations")
    op.drop_index("ix_decision_eval_model_time", table_name="decision_evaluations")
    op.drop_table("decision_evaluations")
    op.drop_table("reference_set_versions")
    op.drop_table("reference_sets")
    op.drop_table("decision_tests")
    op.drop_index("ix_decision_versions_model_state", table_name="decision_versions")
    op.drop_table("decision_versions")
    op.drop_table("decision_models")
