"""Current-generation Claude pricing rows (Opus 5, Sonnet 5, Haiku 4.5).

The model catalogue that feeds every picker in the UI is built from
`llm_model_pricing`, so a model absent from this table cannot be selected
even though the runtime would happily call it. The Claude subscription
serves this family, and `llm.subscription.default_model` is validated
against the catalogue, so the rows have to exist before subscription mode
can be pointed at Opus 5.

Prices are first-party Anthropic API rates per 1M tokens. Under a
subscription the marginal cost is zero — the runtime overrides cost to 0
for subscription-served calls, and these rows stay correct for the
API-key path.

Idempotent: re-runnable, inserts only what is missing.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2g3h4i5
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2g3h4i5"
branch_labels = None
depends_on = None


_CAPS = '{"tools": true, "streaming": true, "vision": true, "json_mode": true}'

_AZURE_LADDER = ["azure-gpt-5", "azure-gpt-4.1", "azure-gpt-4o", "azure-gpt-4o-mini"]

# model, display name, input $/M, output $/M, cached input $/M, fallbacks
_ROWS: list[tuple[str, str, float, float, float, list[str]]] = [
    (
        "claude-opus-5",
        "Claude Opus 5",
        5.00,
        25.00,
        0.50,
        ["claude-sonnet-5", "claude-sonnet-4-5-20250929"] + _AZURE_LADDER,
    ),
    (
        "claude-sonnet-5",
        "Claude Sonnet 5",
        2.00,
        10.00,
        0.20,
        ["claude-haiku-4-5", "claude-sonnet-4-5-20250929"] + _AZURE_LADDER,
    ),
    (
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        1.00,
        5.00,
        0.10,
        ["claude-sonnet-5"] + _AZURE_LADDER,
    ),
]


def _arr(items: list[str]) -> str:
    inner = ",".join(f"'{x}'" for x in items)
    return f"ARRAY[{inner}]::varchar(128)[]"


def upgrade() -> None:
    bind = op.get_bind()
    has_table = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='llm_model_pricing'"
        )
    ).scalar()
    if not has_table:
        return

    for model, label, inp, out, cached, fallbacks in _ROWS:
        # `model` is not unique (historical pricing is keyed by
        # effective_from), so ON CONFLICT (model) is not available here.
        exists = bind.execute(
            text("SELECT 1 FROM llm_model_pricing WHERE model = :m LIMIT 1"),
            {"m": model},
        ).scalar()
        if exists:
            continue
        bind.execute(
            text(
                f"""
                INSERT INTO llm_model_pricing (
                    id, model, provider, input_per_m, output_per_m,
                    cached_input_per_m, capabilities, fallback_to,
                    display_name, is_active, is_deprecated, effective_from
                )
                VALUES (
                    gen_random_uuid(), :m, 'anthropic', :inp, :out,
                    :cached, '{_CAPS}'::jsonb, {_arr(fallbacks)},
                    :label, TRUE, FALSE, NOW()
                )
                """
            ),
            {"m": model, "inp": inp, "out": out, "cached": cached, "label": label},
        )


def downgrade() -> None:
    bind = op.get_bind()
    has_table = bind.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='llm_model_pricing'"
        )
    ).scalar()
    if not has_table:
        return
    for model, *_ in _ROWS:
        bind.execute(
            text("DELETE FROM llm_model_pricing WHERE model = :m"), {"m": model}
        )
