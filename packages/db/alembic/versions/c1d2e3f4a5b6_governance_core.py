"""Governance core: permission sets, risk policies, kill switches, run provenance, audit chain.

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)


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


def upgrade() -> None:
    _create_table(
        "permission_sets",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "capabilities", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.UniqueConstraint("tenant_id", "name", name="uq_permission_set_name"),
    )
    _create_table(
        "permission_assignments",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column(
            "permission_set_id",
            _UUID,
            sa.ForeignKey("permission_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "permission_set_id", "user_id", name="uq_permission_assignment"
        ),
    )
    _create_index(
        "ix_permission_assignment_user",
        "permission_assignments",
        ["tenant_id", "user_id"],
    )

    _create_table(
        "risk_policies",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id", _UUID, sa.ForeignKey("tenants.id"), nullable=False, index=True
        ),
        sa.Column("tier", sa.String(16), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "tier", name="uq_risk_policy_tier"),
    )

    _create_table(
        "kill_switches",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            _UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("target", sa.String(255), nullable=False, server_default="*"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "set_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "cleared_by",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    _create_index(
        "ix_kill_switch_lookup",
        "kill_switches",
        ["tenant_id", "scope", "target", "active"],
    )

    # what tier a run reached and exactly what ran
    _add_column("executions", sa.Column("risk_tier", sa.String(16), nullable=True))
    _add_column(
        "executions", sa.Column("risk_reasons", postgresql.JSONB(), nullable=True)
    )
    _add_column("executions", sa.Column("agent_revision", sa.Integer(), nullable=True))
    _add_column("executions", sa.Column("prompt_hash", sa.String(64), nullable=True))
    _add_column(
        "executions", sa.Column("provenance", postgresql.JSONB(), nullable=True)
    )
    _create_index("ix_executions_risk_tier", "executions", ["risk_tier"])

    # exactly what a run ran with, stamped by the database so no insert path skips it
    _create_table(
        "execution_config_snapshots",
        sa.Column("config_hash", sa.String(64), primary_key=True),
        sa.Column("agent_id", _UUID, nullable=True, index=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("model_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION executions_provenance() RETURNS trigger AS $$
        DECLARE
          a RECORD;
          h text;
          tier text;
        BEGIN
          IF NEW.agent_id IS NULL OR NEW.provenance IS NOT NULL THEN
            RETURN NEW;
          END IF;
          SELECT system_prompt, model_config, version INTO a
            FROM agents WHERE id = NEW.agent_id;
          IF NOT FOUND THEN
            RETURN NEW;
          END IF;
          h := encode(sha256(convert_to(
                 coalesce(a.system_prompt, '') || '|' || coalesce(a.model_config::text, ''),
                 'UTF8')), 'hex');
          INSERT INTO execution_config_snapshots (config_hash, agent_id, system_prompt, model_config)
            VALUES (h, NEW.agent_id, a.system_prompt, a.model_config)
            ON CONFLICT (config_hash) DO NOTHING;
          tier := CASE WHEN a.model_config->>'risk_tier' IN ('low', 'medium', 'high', 'critical')
                       THEN a.model_config->>'risk_tier' ELSE 'low' END;
          NEW.agent_revision := (SELECT max(revision_number) FROM agent_revisions
                                  WHERE agent_id = NEW.agent_id);
          NEW.prompt_hash := encode(sha256(convert_to(coalesce(a.system_prompt, ''), 'UTF8')), 'hex');
          NEW.risk_tier := coalesce(NEW.risk_tier, tier);
          NEW.provenance := jsonb_build_object(
            'config_hash', h,
            'agent_version', a.version,
            'model', a.model_config->>'model',
            'temperature', a.model_config->'temperature',
            'tools', coalesce(a.model_config->'tools', '[]'::jsonb),
            'risk_tier', tier
          );
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS executions_provenance ON executions")
    op.execute(
        "CREATE TRIGGER executions_provenance BEFORE INSERT ON executions "
        "FOR EACH ROW EXECUTE FUNCTION executions_provenance()"
    )

    # tamper-evident audit: global order, linked later by the chainer
    op.execute("CREATE SEQUENCE IF NOT EXISTS activity_logs_audit_seq")
    _add_column(
        "activity_logs",
        sa.Column(
            "audit_seq",
            sa.BigInteger(),
            server_default=sa.text("nextval('activity_logs_audit_seq')"),
            nullable=False,
        ),
    )
    _add_column("activity_logs", sa.Column("prev_hash", sa.String(64), nullable=True))
    _add_column("activity_logs", sa.Column("row_hash", sa.String(64), nullable=True))
    _add_column("activity_logs", sa.Column("chain_pos", sa.BigInteger(), nullable=True))
    # salted commitment to the actor fields, so erasure keeps the chain verifiable
    _add_column("activity_logs", sa.Column("pii_salt", sa.String(32), nullable=True))
    _add_column("activity_logs", sa.Column("pii_digest", sa.String(64), nullable=True))
    _create_index(
        "ix_activity_logs_tenant_seq", "activity_logs", ["tenant_id", "audit_seq"]
    )
    _create_index(
        "ix_activity_logs_tenant_chain", "activity_logs", ["tenant_id", "chain_pos"]
    )
    _create_index(
        "ix_activity_logs_unchained",
        "activity_logs",
        ["audit_seq"],
        postgresql_where=sa.text("row_hash IS NULL"),
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION activity_logs_immutable() RETURNS trigger AS $$
        BEGIN
          IF current_setting('abenix.audit_maintenance', true) = 'on' THEN
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'activity_logs is append-only';
          END IF;
          -- the chainer may write the hash columns once, nothing else may change
          IF OLD.row_hash IS NULL
             AND NEW.row_hash IS NOT NULL
             AND NEW.id = OLD.id
             AND NEW.tenant_id = OLD.tenant_id
             AND NEW.user_id = OLD.user_id
             AND NEW.action = OLD.action
             AND NEW.details IS NOT DISTINCT FROM OLD.details
             AND NEW.ip_address IS NOT DISTINCT FROM OLD.ip_address
             AND NEW.user_agent IS NOT DISTINCT FROM OLD.user_agent
             AND NEW.created_at = OLD.created_at
             AND NEW.audit_seq = OLD.audit_seq THEN
            RETURN NEW;
          END IF;
          RAISE EXCEPTION 'activity_logs is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS activity_logs_immutable ON activity_logs")
    op.execute(
        "CREATE TRIGGER activity_logs_immutable BEFORE UPDATE OR DELETE ON activity_logs "
        "FOR EACH ROW EXECUTE FUNCTION activity_logs_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS activity_logs_immutable ON activity_logs")
    op.execute("DROP FUNCTION IF EXISTS activity_logs_immutable()")
    op.drop_index("ix_activity_logs_unchained", table_name="activity_logs")
    op.drop_index("ix_activity_logs_tenant_chain", table_name="activity_logs")
    op.drop_index("ix_activity_logs_tenant_seq", table_name="activity_logs")
    op.drop_column("activity_logs", "pii_digest")
    op.drop_column("activity_logs", "pii_salt")
    op.drop_column("activity_logs", "chain_pos")
    op.drop_column("activity_logs", "row_hash")
    op.drop_column("activity_logs", "prev_hash")
    op.drop_column("activity_logs", "audit_seq")
    op.execute("DROP SEQUENCE IF EXISTS activity_logs_audit_seq")
    op.execute("DROP TRIGGER IF EXISTS executions_provenance ON executions")
    op.execute("DROP FUNCTION IF EXISTS executions_provenance()")
    op.drop_table("execution_config_snapshots")
    op.drop_index("ix_executions_risk_tier", table_name="executions")
    for c in (
        "provenance",
        "prompt_hash",
        "agent_revision",
        "risk_reasons",
        "risk_tier",
    ):
        op.drop_column("executions", c)
    op.drop_index("ix_kill_switch_lookup", table_name="kill_switches")
    op.drop_table("kill_switches")
    op.drop_table("risk_policies")
    op.drop_index("ix_permission_assignment_user", table_name="permission_assignments")
    op.drop_table("permission_assignments")
    op.drop_table("permission_sets")
