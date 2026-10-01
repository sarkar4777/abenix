"""The model pricing rows every install starts with, and the seeder that
writes them.

Shared by the admin endpoint (POST /api/admin/llm-pricing/seed) and the deploy
seed `seeds/seed_llm_pricing.py`. It lives at the packages/db level rather than
under seeds/ because the seed runner has only packages/db on its path, and the
API imports from here the same way it imports models.

A fresh database is built by create_all and then stamped, so the alembic data
migrations that used to carry these rows never run on it. The catalogue came up
empty, every model picker fell back to a hardcoded list, and cost showed as
$0.0000. Idempotent, inserts only what is missing and backfills nulls.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.llm_pricing import LLMModelPricing

FULL_CAPS = {"tools": True, "streaming": True, "vision": True, "json_mode": True}
NO_VISION = {"tools": True, "streaming": True, "vision": False, "json_mode": True}

# Azure-only deploys: every non-Azure model ends its fallback chain with the
# full Azure ladder, most powerful first, so a tenant with only an Azure key
# still routes somewhere. model_resolver walks these in order.
AZURE_LADDER = ["azure-gpt-5", "azure-gpt-4.1", "azure-gpt-4o", "azure-gpt-4o-mini"]
FB_ANTHROPIC = ["claude-sonnet-4-5-20250929", "gpt-4o", "gemini-2.5-pro"] + AZURE_LADDER
FB_OPENAI = ["claude-sonnet-4-5-20250929", "gemini-2.5-pro"] + AZURE_LADDER
FB_GOOGLE = ["gpt-4o", "claude-sonnet-4-5-20250929"] + AZURE_LADDER
FB_AZURE_GPT_5 = [
    "azure-gpt-4.1",
    "azure-gpt-4o",
    "azure-gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4-5-20250929",
]
FB_AZURE_GPT_4_1 = [
    "azure-gpt-4o",
    "azure-gpt-4o-mini",
    "gpt-4o",
    "claude-sonnet-4-5-20250929",
]
FB_AZURE_GPT_4O = ["azure-gpt-4o-mini", "gpt-4o", "claude-sonnet-4-5-20250929"]
FB_AZURE_GPT_4O_MINI = ["gpt-4o-mini", "claude-haiku-4-5"]

# model, provider, input/M, output/M, cached/M, batch_in/M, batch_out/M, capabilities, fallback_to, display
BASELINE: list[tuple[Any, ...]] = [
    (
        "claude-opus-5",
        "anthropic",
        5.0,
        25.0,
        0.5,
        None,
        None,
        FULL_CAPS,
        ["claude-sonnet-5", "claude-sonnet-4-5-20250929"] + AZURE_LADDER,
        "Claude Opus 5",
    ),
    (
        "claude-sonnet-5",
        "anthropic",
        2.0,
        10.0,
        0.2,
        None,
        None,
        FULL_CAPS,
        ["claude-haiku-4-5", "claude-sonnet-4-5-20250929"] + AZURE_LADDER,
        "Claude Sonnet 5",
    ),
    (
        "claude-opus-4-6-20250106",
        "anthropic",
        15.0,
        75.0,
        1.5,
        7.5,
        37.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Opus 4.6",
    ),
    (
        "claude-opus-4-6",
        "anthropic",
        15.0,
        75.0,
        1.5,
        7.5,
        37.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Opus 4.6",
    ),
    (
        "claude-sonnet-4-6-20250106",
        "anthropic",
        3.0,
        15.0,
        0.3,
        1.5,
        7.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Sonnet 4.6",
    ),
    (
        "claude-sonnet-4-6",
        "anthropic",
        3.0,
        15.0,
        0.3,
        1.5,
        7.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Sonnet 4.6",
    ),
    (
        "claude-sonnet-4-5-20250929",
        "anthropic",
        3.0,
        15.0,
        0.3,
        1.5,
        7.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Sonnet 4.5",
    ),
    (
        "claude-sonnet-4-20250514",
        "anthropic",
        3.0,
        15.0,
        0.3,
        1.5,
        7.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Sonnet 4",
    ),
    (
        "claude-haiku-4-5-20251001",
        "anthropic",
        1.0,
        5.0,
        0.1,
        0.5,
        2.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Haiku 4.5",
    ),
    (
        "claude-haiku-4-5",
        "anthropic",
        1.0,
        5.0,
        0.1,
        0.5,
        2.5,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Haiku 4.5",
    ),
    (
        "claude-haiku-3-5-20241022",
        "anthropic",
        0.80,
        4.0,
        0.08,
        0.4,
        2.0,
        FULL_CAPS,
        FB_ANTHROPIC,
        "Claude Haiku 3.5",
    ),
    ("gpt-4o", "openai", 2.50, 10.0, 1.25, 1.25, 5.0, FULL_CAPS, FB_OPENAI, "GPT-4o"),
    (
        "gpt-4o-mini",
        "openai",
        0.15,
        0.60,
        0.075,
        0.075,
        0.30,
        FULL_CAPS,
        FB_OPENAI,
        "GPT-4o Mini",
    ),
    (
        "gemini-2.0-flash",
        "google",
        0.10,
        0.40,
        None,
        None,
        None,
        FULL_CAPS,
        FB_GOOGLE,
        "Gemini 2.0 Flash",
    ),
    (
        "gemini-2.5-flash",
        "google",
        0.30,
        2.50,
        None,
        None,
        None,
        FULL_CAPS,
        FB_GOOGLE,
        "Gemini 2.5 Flash",
    ),
    (
        "gemini-2.5-pro",
        "google",
        1.25,
        10.0,
        None,
        None,
        None,
        FULL_CAPS,
        FB_GOOGLE,
        "Gemini 2.5 Pro",
    ),
    (
        "gemini-1.5-pro",
        "google",
        1.25,
        5.00,
        None,
        None,
        None,
        FULL_CAPS,
        FB_GOOGLE,
        "Gemini 1.5 Pro",
    ),
    (
        "azure-gpt-4o",
        "azure",
        2.50,
        10.0,
        1.25,
        1.25,
        5.0,
        FULL_CAPS,
        FB_AZURE_GPT_4O,
        "Azure GPT-4o",
    ),
    (
        "azure-gpt-4o-mini",
        "azure",
        0.15,
        0.60,
        0.075,
        0.075,
        0.30,
        FULL_CAPS,
        FB_AZURE_GPT_4O_MINI,
        "Azure GPT-4o Mini",
    ),
    (
        "azure-gpt-4.1",
        "azure",
        2.00,
        8.00,
        None,
        None,
        None,
        FULL_CAPS,
        FB_AZURE_GPT_4_1,
        "Azure GPT-4.1",
    ),
    (
        "azure-gpt-5",
        "azure",
        5.00,
        15.0,
        None,
        None,
        None,
        NO_VISION,
        FB_AZURE_GPT_5,
        "Azure GPT-5",
    ),
]


async def seed_pricing(db: AsyncSession) -> dict[str, int]:
    """Insert missing baseline rows and backfill nulls on existing ones."""
    existing = {
        r[0]
        for r in (await db.execute(text("SELECT model FROM llm_model_pricing"))).all()
    }
    added = 0
    for model, provider, inp, out, cached, b_in, b_out, caps, fb, label in BASELINE:
        if model in existing:
            continue
        db.add(
            LLMModelPricing(
                model=model,
                provider=provider,
                input_per_m=inp,
                output_per_m=out,
                cached_input_per_m=cached,
                batch_input_per_m=b_in,
                batch_output_per_m=b_out,
                capabilities=caps,
                fallback_to=list(fb),
                display_name=label,
                is_active=True,
                is_deprecated=False,
            )
        )
        added += 1
    await db.commit()

    backfilled = 0
    for model, _p, _i, _o, _c, _bi, _bo, caps, fb, label in BASELINE:
        result = await db.execute(
            text(
                """
                UPDATE llm_model_pricing
                SET capabilities = COALESCE(capabilities, CAST(:caps AS jsonb)),
                    fallback_to = COALESCE(fallback_to, CAST(:fb AS varchar(128)[])),
                    display_name = COALESCE(display_name, :label),
                    is_active = COALESCE(is_active, TRUE),
                    is_deprecated = COALESCE(is_deprecated, FALSE)
                WHERE model = :model
                  AND (capabilities IS NULL OR fallback_to IS NULL OR display_name IS NULL
                       OR is_active IS NULL OR is_deprecated IS NULL)
                """
            ),
            {"caps": json.dumps(caps), "fb": fb, "label": label, "model": model},
        )
        backfilled += result.rowcount or 0
    await db.commit()
    return {
        "seeded": added,
        "backfilled": backfilled,
        "skipped_existing": len(existing) - backfilled,
    }
