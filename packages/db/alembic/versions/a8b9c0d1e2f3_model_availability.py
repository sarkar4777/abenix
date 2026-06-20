from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a8b9c0d1e2f3"
down_revision = "z9y8x7w6v5u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "llm_model_pricing",
        sa.Column(
            "capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column(
            "fallback_to", postgresql.ARRAY(sa.String(length=128)), nullable=True
        ),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column("provider_endpoint", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column("display_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column(
            "is_deprecated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "llm_model_pricing",
        sa.Column("migration_hint", sa.String(length=256), nullable=True),
    )

    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("executions"):
        existing_cols = {c["name"] for c in insp.get_columns("executions")}
        if "model_requested" not in existing_cols:
            op.add_column(
                "executions",
                sa.Column("model_requested", sa.String(length=100), nullable=True),
            )
        if "model_fallback_reason" not in existing_cols:
            op.add_column(
                "executions",
                sa.Column("model_fallback_reason", sa.String(length=64), nullable=True),
            )

    op.create_table(
        "model_availability",
        sa.Column("model", sa.String(length=128), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="available"
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_failures", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status_since", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_model_availability_status", "model_availability", ["status"])

    op.create_table(
        "model_availability_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_model_availability_events_model_at",
        "model_availability_events",
        ["model", "at"],
    )

    op.execute(
        sa.text("UPDATE llm_model_pricing SET is_active = TRUE WHERE is_active IS NULL")
    )
    op.execute(
        sa.text(
            "UPDATE llm_model_pricing SET is_deprecated = FALSE WHERE is_deprecated IS NULL"
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET capabilities = '{"tools": true, "streaming": true, "vision": true, "json_mode": true}'::jsonb
            WHERE provider = 'anthropic' AND capabilities IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET capabilities = '{"tools": true, "streaming": true, "vision": true, "json_mode": true}'::jsonb
            WHERE provider = 'openai' AND capabilities IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET capabilities = '{"tools": true, "streaming": true, "vision": true, "json_mode": true}'::jsonb
            WHERE provider = 'google' AND capabilities IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET fallback_to = ARRAY['claude-sonnet-4-5-20250929','gpt-4o','azure-gpt-4o','gemini-2.5-pro']::varchar(128)[]
            WHERE model = 'claude-sonnet-4-5-20250929' AND fallback_to IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET fallback_to = ARRAY['claude-sonnet-4-5-20250929','azure-gpt-4o','gemini-2.5-pro']::varchar(128)[]
            WHERE provider = 'anthropic' AND fallback_to IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET fallback_to = ARRAY['azure-gpt-4o','claude-sonnet-4-5-20250929','gemini-2.5-pro']::varchar(128)[]
            WHERE provider = 'openai' AND fallback_to IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE llm_model_pricing
            SET fallback_to = ARRAY['gpt-4o','azure-gpt-4o','claude-sonnet-4-5-20250929']::varchar(128)[]
            WHERE provider = 'google' AND fallback_to IS NULL
            """
        )
    )

    full_caps = '\'{"tools": true, "streaming": true, "vision": true, "json_mode": true}\'::jsonb'
    no_vision = '\'{"tools": true, "streaming": true, "vision": false, "json_mode": true}\'::jsonb'
    fb_anthropic = "ARRAY['azure-gpt-4o','gpt-4o','gemini-2.5-pro']::varchar(128)[]"
    fb_openai = "ARRAY['claude-sonnet-4-5-20250929','azure-gpt-4o','gemini-2.5-pro']::varchar(128)[]"
    fb_google = (
        "ARRAY['gpt-4o','claude-sonnet-4-5-20250929','azure-gpt-4o']::varchar(128)[]"
    )
    fb_azure = (
        "ARRAY['gpt-4o','claude-sonnet-4-5-20250929','gemini-2.5-pro']::varchar(128)[]"
    )

    baseline_inserts = [
        (
            "claude-opus-4-6-20250106",
            "anthropic",
            15.0,
            75.0,
            "1.5",
            "7.5",
            "37.5",
            full_caps,
            fb_anthropic,
            "Claude Opus 4.6",
        ),
        (
            "claude-opus-4-6",
            "anthropic",
            15.0,
            75.0,
            "1.5",
            "7.5",
            "37.5",
            full_caps,
            fb_anthropic,
            "Claude Opus 4.6",
        ),
        (
            "claude-sonnet-4-6-20250106",
            "anthropic",
            3.0,
            15.0,
            "0.3",
            "1.5",
            "7.5",
            full_caps,
            fb_anthropic,
            "Claude Sonnet 4.6",
        ),
        (
            "claude-sonnet-4-6",
            "anthropic",
            3.0,
            15.0,
            "0.3",
            "1.5",
            "7.5",
            full_caps,
            fb_anthropic,
            "Claude Sonnet 4.6",
        ),
        (
            "claude-sonnet-4-5-20250929",
            "anthropic",
            3.0,
            15.0,
            "0.3",
            "1.5",
            "7.5",
            full_caps,
            fb_anthropic,
            "Claude Sonnet 4.5",
        ),
        (
            "claude-sonnet-4-20250514",
            "anthropic",
            3.0,
            15.0,
            "0.3",
            "1.5",
            "7.5",
            full_caps,
            fb_anthropic,
            "Claude Sonnet 4",
        ),
        (
            "claude-haiku-4-5-20251001",
            "anthropic",
            1.0,
            5.0,
            "0.1",
            "0.5",
            "2.5",
            full_caps,
            fb_anthropic,
            "Claude Haiku 4.5",
        ),
        (
            "claude-haiku-4-5",
            "anthropic",
            1.0,
            5.0,
            "0.1",
            "0.5",
            "2.5",
            full_caps,
            fb_anthropic,
            "Claude Haiku 4.5",
        ),
        (
            "claude-haiku-3-5-20241022",
            "anthropic",
            0.80,
            4.0,
            "0.08",
            "0.4",
            "2.0",
            full_caps,
            fb_anthropic,
            "Claude Haiku 3.5",
        ),
        (
            "gpt-4o",
            "openai",
            2.50,
            10.0,
            "1.25",
            "1.25",
            "5.0",
            full_caps,
            fb_openai,
            "GPT-4o",
        ),
        (
            "gpt-4o-mini",
            "openai",
            0.15,
            0.60,
            "0.075",
            "0.075",
            "0.30",
            full_caps,
            fb_openai,
            "GPT-4o Mini",
        ),
        (
            "gemini-2.0-flash",
            "google",
            0.10,
            0.40,
            "null",
            "null",
            "null",
            full_caps,
            fb_google,
            "Gemini 2.0 Flash",
        ),
        (
            "gemini-2.5-flash",
            "google",
            0.30,
            2.50,
            "null",
            "null",
            "null",
            full_caps,
            fb_google,
            "Gemini 2.5 Flash",
        ),
        (
            "gemini-2.5-pro",
            "google",
            1.25,
            10.0,
            "null",
            "null",
            "null",
            full_caps,
            fb_google,
            "Gemini 2.5 Pro",
        ),
        (
            "gemini-1.5-pro",
            "google",
            1.25,
            5.00,
            "null",
            "null",
            "null",
            full_caps,
            fb_google,
            "Gemini 1.5 Pro",
        ),
        (
            "azure-gpt-4o",
            "azure",
            2.50,
            10.0,
            "1.25",
            "1.25",
            "5.0",
            full_caps,
            fb_azure,
            "Azure GPT-4o",
        ),
        (
            "azure-gpt-4.1",
            "azure",
            2.00,
            8.00,
            "null",
            "null",
            "null",
            full_caps,
            fb_azure,
            "Azure GPT-4.1",
        ),
        (
            "azure-gpt-5",
            "azure",
            5.00,
            15.0,
            "null",
            "null",
            "null",
            no_vision,
            fb_azure,
            "Azure GPT-5",
        ),
    ]
    for (
        model,
        provider,
        inp,
        outp,
        cached,
        b_in,
        b_out,
        caps,
        fb,
        label,
    ) in baseline_inserts:
        op.execute(
            sa.text(
                f"""
                INSERT INTO llm_model_pricing
                    (id, model, provider, input_per_m, output_per_m,
                     cached_input_per_m, batch_input_per_m, batch_output_per_m,
                     is_active, is_deprecated, capabilities, fallback_to, display_name)
                SELECT gen_random_uuid(), '{model}', '{provider}', {inp}, {outp},
                       {cached}, {b_in}, {b_out}, TRUE, FALSE,
                       {caps}, {fb}, '{label}'
                WHERE NOT EXISTS (SELECT 1 FROM llm_model_pricing WHERE model = '{model}')
                """
            )
        )

    op.execute(
        sa.text(
            """
            INSERT INTO model_availability (model, provider, status)
            SELECT DISTINCT ON (model) model, provider, 'available'
            FROM llm_model_pricing
            WHERE is_active = TRUE
            ORDER BY model, effective_from DESC
            ON CONFLICT (model) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_availability_events_model_at", table_name="model_availability_events"
    )
    op.drop_table("model_availability_events")
    op.drop_index("ix_model_availability_status", table_name="model_availability")
    op.drop_table("model_availability")
    for col in (
        "migration_hint",
        "deprecated_at",
        "is_deprecated",
        "display_name",
        "provider_endpoint",
        "fallback_to",
        "capabilities",
    ):
        op.drop_column("llm_model_pricing", col)
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table("executions"):
        existing = {c["name"] for c in insp.get_columns("executions")}
        for c in ("model_fallback_reason", "model_requested"):
            if c in existing:
                op.drop_column("executions", c)
