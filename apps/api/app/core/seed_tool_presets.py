"""Seed default tool presets for every tenant on startup.

These presets are the labelled (tool, args) bundles that the metals/gas
admin pages and dashboards used to show as the example app-specific adapters.
They now live in abenix as generic presets and are visible to every app
that has the underlying tool in its allow-list. Tenants can freely
add/remove their own; the system presets are tagged is_system=True so the
delete endpoint refuses to wipe them.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Each entry becomes one row per tenant. The ``tool_slug`` is the abenix
# tool that does the actual fetch; ``default_args`` pins the call so the
# UI / agent / SDK caller doesn't need to remember it.
SYSTEM_PRESETS: list[dict[str, Any]] = [
    {
        "slug": "lbma_gold_fix",
        "label": "LBMA Gold AM/PM Fix",
        "description": "Front-month gold future (GC=F) as proxy for LBMA. Swap to LBMA paid feed via config when ready.",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "gold",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "gold",
        "category": "finance",
    },
    {
        "slug": "lbma_silver_price",
        "label": "LBMA Silver Price",
        "description": "Silver front-month proxy (SI=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "silver",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "silver",
        "category": "finance",
    },
    {
        "slug": "lppm_platinum_fix",
        "label": "LPPM Platinum Fix",
        "description": "Platinum front-month proxy (PL=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "platinum",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "platinum",
        "category": "finance",
    },
    {
        "slug": "lppm_palladium_fix",
        "label": "LPPM Palladium Fix",
        "description": "Palladium front-month proxy (PA=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "palladium",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "palladium",
        "category": "finance",
    },
    {
        "slug": "comex_copper",
        "label": "COMEX copper settlement",
        "description": "Copper front-month future (HG=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "copper",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "copper",
        "category": "finance",
    },
    {
        "slug": "metals_etf_gld",
        "label": "Metals ETF — GLD NAV",
        "description": "GLD ETF NAV as a sentiment / flow proxy.",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "etf_gld",
            "history_days": 90,
        },
        "ui_group": "metals",
        "asset_class": "metals",
        "category": "finance",
    },
    {
        "slug": "shanghai_gold_usdcny",
        "label": "USD/CNY (for SGE derivation)",
        "description": "USDCNY needed to derive Shanghai Gold from LBMA proxy.",
        "tool_slug": "yahoo_finance",
        "default_args": {"action": "fx_rate", "symbol": "usdcny", "history_days": 30},
        "ui_group": "fx",
        "asset_class": "fx",
        "category": "finance",
    },
    {
        "slug": "ttf_settlement",
        "label": "TTF settlement (front-month)",
        "description": "TTF natgas front-month proxy (TTF=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "natgas_ttf",
            "history_days": 30,
        },
        "ui_group": "gas",
        "asset_class": "natgas",
        "category": "finance",
    },
    {
        "slug": "henry_hub_natgas",
        "label": "Henry Hub natgas",
        "description": "US Henry Hub front-month (NG=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "natgas_henry_hub",
            "history_days": 30,
        },
        "ui_group": "gas",
        "asset_class": "natgas",
        "category": "finance",
    },
    {
        "slug": "wti_crude",
        "label": "WTI crude",
        "description": "WTI front-month (CL=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "wti",
            "history_days": 60,
        },
        "ui_group": "oil",
        "asset_class": "oil",
        "category": "finance",
    },
    {
        "slug": "brent_crude",
        "label": "Brent crude",
        "description": "Brent front-month (BZ=F).",
        "tool_slug": "yahoo_finance",
        "default_args": {
            "action": "commodity_future",
            "symbol": "brent",
            "history_days": 60,
        },
        "ui_group": "oil",
        "asset_class": "oil",
        "category": "finance",
    },
]


async def seed_presets_for_all_tenants(db: AsyncSession) -> None:
    """Upsert one copy of every system preset per tenant. Idempotent."""

    from models.tenant import Tenant
    from models.tool_preset import ToolPreset

    tenants = (await db.execute(select(Tenant))).scalars().all()
    if not tenants:
        logger.info("seed_presets: no tenants yet — skipping")
        return

    inserted = 0
    for tenant in tenants:
        for spec in SYSTEM_PRESETS:
            existing = (
                await db.execute(
                    select(ToolPreset).where(
                        ToolPreset.tenant_id == tenant.id,
                        ToolPreset.slug == spec["slug"],
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Keep is_system flag in sync but don't overwrite user edits to
                # label/default_args/enabled.
                if not existing.is_system:
                    existing.is_system = True
                continue
            row = ToolPreset(
                tenant_id=tenant.id,
                slug=spec["slug"],
                label=spec["label"],
                description=spec.get("description"),
                tool_slug=spec["tool_slug"],
                default_args=spec.get("default_args") or {},
                config=spec.get("config") or {},
                category=spec.get("category"),
                ui_group=spec.get("ui_group"),
                asset_class=spec.get("asset_class"),
                enabled=True,
                is_system=True,
            )
            db.add(row)
            inserted += 1
    if inserted:
        logger.info("seed_presets: inserted %d preset rows", inserted)
    await db.commit()
