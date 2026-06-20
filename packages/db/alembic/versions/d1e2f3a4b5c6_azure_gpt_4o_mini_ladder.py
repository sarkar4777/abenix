"""Azure GPT-4o-mini row + Azure-ladder fallback chains.

User runs Azure-only on production; the previous fallback chains pointed at
gpt-4o / claude / gemini, which all 401 when their provider key is missing.
Now every non-Azure model's fallback ends with the full Azure ladder
(azure-gpt-5 -> azure-gpt-4.1 -> azure-gpt-4o -> azure-gpt-4o-mini), so the
resolver always lands on whichever Azure deployment the tenant actually has
access to.

Idempotent: re-runnable on clusters that already have the row, only updates
fallback_to.

Revision ID: d1e2f3a4b5c6
Revises: c0a1d2e3f4b5
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "d1e2f3a4b5c6"
down_revision = "c0a1d2e3f4b5"
branch_labels = None
depends_on = None


_FULL_CAPS = '{"tools": true, "streaming": true, "vision": true, "json_mode": true}'

_AZURE_LADDER = ["azure-gpt-5", "azure-gpt-4.1", "azure-gpt-4o", "azure-gpt-4o-mini"]
_FB_ANTHROPIC = [
    "claude-sonnet-4-5-20250929",
    "gpt-4o",
    "gemini-2.5-pro",
] + _AZURE_LADDER
_FB_OPENAI = ["claude-sonnet-4-5-20250929", "gemini-2.5-pro"] + _AZURE_LADDER
_FB_GOOGLE = ["gpt-4o", "claude-sonnet-4-5-20250929"] + _AZURE_LADDER
_FB_AZURE_5 = [
    "azure-gpt-4.1",
    "azure-gpt-4o",
    "azure-gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4-5-20250929",
]
_FB_AZURE_4_1 = [
    "azure-gpt-4o",
    "azure-gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4-5-20250929",
]
_FB_AZURE_4O = ["azure-gpt-4o-mini", "gpt-4o", "claude-sonnet-4-5-20250929"]
_FB_AZURE_4O_MINI = ["gpt-4o-mini", "claude-haiku-4-5"]


def _arr(items: list[str]) -> str:
    inner = ",".join(f"'{x}'" for x in items)
    return f"ARRAY[{inner}]::varchar(128)[]"


def upgrade() -> None:
    bind = op.get_bind()
    has_table = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_name='llm_model_pricing'"
        )
    ).scalar()
    if not has_table:
        return

    # Table allows multiple rows per model (historical pricing keyed by
    # effective_from), so the PK is `id` and `model` is NOT unique. ON CONFLICT
    # (model) crashes here. Do an explicit check + branch instead.
    exists = bind.execute(
        text(
            "SELECT 1 FROM llm_model_pricing WHERE model = 'azure-gpt-4o-mini' LIMIT 1"
        )
    ).scalar()
    if not exists:
        bind.execute(
            text(
                f"""
                INSERT INTO llm_model_pricing (
                    id, model, provider, input_per_m, output_per_m,
                    cached_input_per_m, batch_input_per_m, batch_output_per_m,
                    capabilities, fallback_to, display_name,
                    is_active, is_deprecated, effective_from
                )
                VALUES (
                    gen_random_uuid(), 'azure-gpt-4o-mini', 'azure', 0.15, 0.60,
                    0.075, 0.075, 0.30,
                    '{_FULL_CAPS}'::jsonb, {_arr(_FB_AZURE_4O_MINI)}, 'Azure GPT-4o Mini',
                    TRUE, FALSE, now()
                )
                """
            )
        )
    else:
        bind.execute(
            text(
                f"""
                UPDATE llm_model_pricing
                   SET fallback_to = {_arr(_FB_AZURE_4O_MINI)},
                       display_name = 'Azure GPT-4o Mini',
                       is_active = TRUE,
                       is_deprecated = FALSE
                 WHERE model = 'azure-gpt-4o-mini'
                """
            )
        )

    # Update every existing row to point at the new Azure ladder. We touch the
    # claude/gpt/gemini families by provider so future new rows pick this up
    # via the seed code, and the specific azure ladder rows by exact name so
    # the powerful->least degrade chain is correct.
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_ANTHROPIC)} WHERE provider = 'anthropic'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_OPENAI)} WHERE provider = 'openai'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_GOOGLE)} WHERE provider = 'google'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_AZURE_5)} WHERE model = 'azure-gpt-5'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_AZURE_4_1)} WHERE model = 'azure-gpt-4.1'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_AZURE_4O)} WHERE model = 'azure-gpt-4o'"
        )
    )
    bind.execute(
        text(
            f"UPDATE llm_model_pricing SET fallback_to = {_arr(_FB_AZURE_4O_MINI)} WHERE model = 'azure-gpt-4o-mini'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_table = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables WHERE table_name='llm_model_pricing'"
        )
    ).scalar()
    if not has_table:
        return
    bind.execute(
        text("DELETE FROM llm_model_pricing WHERE model = 'azure-gpt-4o-mini'")
    )
