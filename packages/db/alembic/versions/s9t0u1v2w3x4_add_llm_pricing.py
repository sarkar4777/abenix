"""LLM pricing table + per-provider cost subtotals."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "s9t0u1v2w3x4"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_model_pricing",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("input_per_m", sa.Numeric(18, 12), nullable=False),
        sa.Column("output_per_m", sa.Numeric(18, 12), nullable=False),
        sa.Column("cached_input_per_m", sa.Numeric(18, 12), nullable=True),
        sa.Column("batch_input_per_m", sa.Numeric(18, 12), nullable=True),
        sa.Column("batch_output_per_m", sa.Numeric(18, 12), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_llm_pricing_model_effective", "llm_model_pricing",
                    ["model", "effective_from"])
    op.create_index("ix_llm_pricing_provider", "llm_model_pricing", ["provider"])

    # Single INSERT with VALUES list — cheaper than 14 statements and
    # keeps the migration atomic. `notes` is omitted (null) so the UI
    # can show it as "uncustomised".
    seed = sa.text(
        """
        INSERT INTO llm_model_pricing
            (model, provider, input_per_m, output_per_m,
             cached_input_per_m, batch_input_per_m, batch_output_per_m)
        VALUES
            -- Anthropic
            ('claude-opus-4-6-20250106',  'anthropic', 15.0, 75.0, 1.5,  7.5,  37.5),
            ('claude-opus-4-6',           'anthropic', 15.0, 75.0, 1.5,  7.5,  37.5),
            ('claude-sonnet-4-6-20250106','anthropic', 3.0,  15.0, 0.3,  1.5,  7.5),
            ('claude-sonnet-4-6',         'anthropic', 3.0,  15.0, 0.3,  1.5,  7.5),
            ('claude-sonnet-4-5-20250929','anthropic', 3.0,  15.0, 0.3,  1.5,  7.5),
            ('claude-sonnet-4-20250514',  'anthropic', 3.0,  15.0, 0.3,  1.5,  7.5),
            ('claude-haiku-4-5-20251001', 'anthropic', 1.0,  5.0,  0.1,  0.5,  2.5),
            ('claude-haiku-4-5',          'anthropic', 1.0,  5.0,  0.1,  0.5,  2.5),
            ('claude-haiku-3-5-20241022', 'anthropic', 0.80, 4.0,  0.08, 0.4,  2.0),
            -- OpenAI
            ('gpt-4o',                    'openai',    2.50, 10.0, 1.25, 1.25, 5.0),
            ('gpt-4o-mini',               'openai',    0.15, 0.60, 0.075,0.075,0.30),
            -- Google
            ('gemini-2.0-flash',          'google',    0.10, 0.40, null, null, null),
            ('gemini-2.5-flash',          'google',    0.30, 2.50, null, null, null),
            ('gemini-2.5-pro',            'google',    1.25, 10.0, null, null, null),
            ('gemini-1.5-pro',            'google',    1.25, 5.00, null, null, null)
        """
    )
    op.execute(seed)

    bind = op.get_bind()
    insp = sa.inspect(bind)

    def _add_cost_cols(table: str) -> None:
        if not insp.has_table(table):
            return
        existing = {c["name"] for c in insp.get_columns(table)}
        for col in ("anthropic_cost", "openai_cost", "google_cost", "other_cost"):
            if col not in existing:
                op.add_column(
                    table,
                    sa.Column(col, sa.Numeric(10, 6), nullable=False,
                              server_default=sa.text("0")),
                )

    _add_cost_cols("executions")
    _add_cost_cols("cognify_jobs")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table in ("cognify_jobs", "executions"):
        if not insp.has_table(table):
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        for col in ("anthropic_cost", "openai_cost", "google_cost", "other_cost"):
            if col in existing:
                op.drop_column(table, col)

    op.drop_index("ix_llm_pricing_provider", table_name="llm_model_pricing")
    op.drop_index("ix_llm_pricing_model_effective", table_name="llm_model_pricing")
    op.drop_table("llm_model_pricing")
