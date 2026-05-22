"""Seed sensible defaults for tool_runtime_config on startup.

Only seeds tools that benefit most from caching / rate limiting. Tools
not seeded fall back to the dataclass defaults in tool_gate.GateConfig
(safe + permissive). Admins can override any of these from /admin/tool-scaling.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# slug -> overrides applied if no row exists. Only fields that DIFFER from
# the dataclass defaults need to be listed.
DEFAULTS: dict[str, dict[str, Any]] = {
    # External rate-limited APIs — cache aggressively, throttle hard
    "yahoo_finance": {
        "max_inflight_global": 20,
        "max_inflight_per_tenant": 5,
        "rate_limit_qps_global": 8,
        "rate_limit_qps_per_tenant": 2,
        "cache_ttl_seconds": 60,
        "cache_scope": "global",
        "circuit_breaker_threshold": 8,
        "circuit_breaker_window_s": 30,
        "timeout_seconds": 15,
    },
    "tavily_search": {
        "max_inflight_global": 10,
        "max_inflight_per_tenant": 3,
        "rate_limit_qps_global": 5,
        "rate_limit_qps_per_tenant": 1,
        "cache_ttl_seconds": 300,
        "cache_scope": "global",
        "circuit_breaker_threshold": 5,
        "timeout_seconds": 30,
        "daily_budget_calls_per_tenant": 1000,
    },
    "news_feed": {
        "max_inflight_global": 10,
        "rate_limit_qps_global": 4,
        "cache_ttl_seconds": 300,
        "timeout_seconds": 20,
    },
    "academic_search": {
        "max_inflight_global": 5,
        "rate_limit_qps_global": 2,
        "cache_ttl_seconds": 1800,
        "timeout_seconds": 30,
    },
    "open_meteo": {
        "max_inflight_global": 20,
        "rate_limit_qps_global": 10,
        "cache_ttl_seconds": 600,
        "timeout_seconds": 15,
    },
    "eia_open_data": {
        "max_inflight_global": 10,
        "rate_limit_qps_global": 4,
        "cache_ttl_seconds": 900,
        "timeout_seconds": 20,
    },
    "ais_stream": {
        "max_inflight_global": 4,
        "max_inflight_per_tenant": 1,
        "rate_limit_qps_global": 1,
        "cache_ttl_seconds": 60,
        "timeout_seconds": 30,
    },
    "options_data": {
        "max_inflight_global": 5,
        "rate_limit_qps_global": 2,
        "cache_ttl_seconds": 120,
        "timeout_seconds": 20,
    },
    # KYC tools — usually slow + paid feeds
    "sanctions_screening": {
        "max_inflight_global": 8,
        "rate_limit_qps_global": 2,
        "cache_ttl_seconds": 86400,
        "cache_scope": "per_tenant",
        "timeout_seconds": 30,
        "daily_budget_calls_per_tenant": 500,
    },
    "pep_screening": {
        "max_inflight_global": 8,
        "rate_limit_qps_global": 2,
        "cache_ttl_seconds": 86400,
        "cache_scope": "per_tenant",
        "timeout_seconds": 30,
        "daily_budget_calls_per_tenant": 500,
    },
    "adverse_media": {
        "max_inflight_global": 6,
        "rate_limit_qps_global": 1,
        "cache_ttl_seconds": 3600,
        "cache_scope": "per_tenant",
        "timeout_seconds": 45,
    },
    # ML inference + LLM-bound — cap concurrency to keep pods healthy
    "ml_model": {
        "max_inflight_global": 40,
        "max_inflight_per_tenant": 10,
        "cache_ttl_seconds": 30,
        "cache_scope": "per_tenant",
        "timeout_seconds": 60,
    },
    "llm_call": {
        "max_inflight_global": 30,
        "max_inflight_per_tenant": 8,
        "rate_limit_qps_per_tenant": 5,
        "cache_ttl_seconds": 0,
        "timeout_seconds": 90,
        "daily_budget_calls_per_tenant": 5000,
    },
    "code_executor": {
        "max_inflight_global": 8,
        "max_inflight_per_tenant": 2,
        "cache_ttl_seconds": 0,
        "timeout_seconds": 60,
        "circuit_breaker_threshold": 10,
    },
    "code_asset": {
        "max_inflight_global": 6,
        "max_inflight_per_tenant": 2,
        "cache_ttl_seconds": 0,
        "timeout_seconds": 300,
        "pool": "runtime",
    },
}


async def seed_tool_runtime_defaults(db: AsyncSession) -> None:
    from models.tool_runtime_config import ToolRuntimeConfig

    existing = (
        {r.slug for r in (await db.execute(select(ToolRuntimeConfig.slug))).all()}
        if False
        else set()
    )
    # Simpler: pull all slugs
    existing = {r[0] for r in (await db.execute(select(ToolRuntimeConfig.slug))).all()}

    inserted = 0
    for slug, overrides in DEFAULTS.items():
        if slug in existing:
            continue
        db.add(ToolRuntimeConfig(slug=slug, **overrides))
        inserted += 1
    if inserted:
        logger.info("seed_tool_runtime: inserted %d default rows", inserted)
    await db.commit()
