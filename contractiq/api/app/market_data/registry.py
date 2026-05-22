"""Market-data registry — thin client over abenix tool presets.

ContractIQ does not own adapter classes any more. Every "source" you
see in /admin/market-sources is a row in abenix's ``tool_presets`` table
that pins a generic tool (e.g. ``yahoo_finance``) to a specific
configuration. This module:

  1. Lists presets from abenix via the SDK (single source of truth for
     "what feeds are available").
  2. Runs a preset to fetch a value, persists the result to the local
     ``contractiq_market_data_*`` cache so risk / what-if / valuation
     can read from the same fast-path table even if abenix is briefly
     unreachable.

Promoting a feed to a paid source (LBMA, CME) is a per-tenant edit of
the preset's ``config`` — no contractiq deploy needed.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.base import FetchResult
from app.models.contractiq_models import (
    ContractIQMarketDataPoint,
    ContractIQMarketDataSource,
)

logger = logging.getLogger(__name__)

# Vendor the SDK that ships in this app
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sdk"))
from abenix_sdk import Abenix  # type: ignore  # noqa: E402


def _abenix_client() -> Abenix:
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
    if not api_key:
        raise RuntimeError("CONTRACTIQ_ABENIX_API_KEY not configured")
    return Abenix(api_key=api_key, base_url=api_base, timeout=20.0)


async def list_sources(db: AsyncSession) -> list[dict[str, Any]]:
    """Union of abenix presets + local last-synced metadata."""

    try:
        async with _abenix_client() as forge:
            presets = await forge.presets.list()
    except Exception as e:
        logger.warning("could not list abenix presets: %s — falling back to local rows", e)
        presets = []

    rows = (
        await db.execute(select(ContractIQMarketDataSource))
    ).scalars().all()
    by_slug = {r.slug: r for r in rows}

    out: list[dict[str, Any]] = []
    for p in presets:
        slug = p.get("slug")
        if not slug:
            continue
        local = by_slug.get(slug)
        out.append({
            "slug": slug,
            "name": p.get("label") or slug,
            "provider": p.get("tool_slug"),
            "asset_class": p.get("asset_class"),
            "instrument_kind": p.get("ui_group") or "",
            "default_unit": "",
            "config_schema": {},
            "default_args": p.get("default_args") or {},
            "enabled": p.get("enabled", True),
            "configured": local is not None,
            "last_synced_at": local.last_synced_at.isoformat() if local and local.last_synced_at else None,
            "last_value": local.last_value if local else None,
            "ui_group": p.get("ui_group"),
        })
    return out


async def fetch(slug: str, db: AsyncSession, params: dict[str, Any] | None = None) -> FetchResult:
    """Run an abenix preset by slug; cache result locally."""

    try:
        async with _abenix_client() as forge:
            out = await forge.presets.run(slug, arguments=params or {})
    except Exception as e:
        logger.exception("abenix preset run failed for %s", slug)
        return FetchResult(source_slug=slug, error=str(e))

    if out.get("is_error"):
        return FetchResult(source_slug=slug, error=str(out.get("content") or "preset returned error"))

    meta = out.get("metadata") or {}
    value = meta.get("latest_close") if isinstance(meta, dict) else None
    result = FetchResult(
        ts=datetime.now(timezone.utc),
        value=float(value) if value is not None else None,
        payload={
            "content": out.get("content"),
            "metadata": meta,
            "tool_slug": out.get("tool_slug"),
            "arguments": out.get("arguments"),
        },
        source_slug=slug,
    )

    try:
        await _persist(slug, result, out, db)
    except Exception as e:
        logger.warning("persist of preset result failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
    return result


async def sync_source(slug: str, db: AsyncSession) -> FetchResult:
    return await fetch(slug, db)


async def _persist(slug: str, result: FetchResult, sdk_payload: dict[str, Any], db: AsyncSession) -> None:
    row = (
        await db.execute(
            select(ContractIQMarketDataSource).where(ContractIQMarketDataSource.slug == slug)
        )
    ).scalar_one_or_none()
    if row is None:
        row = ContractIQMarketDataSource(
            slug=slug,
            name=sdk_payload.get("preset_slug") or slug,
            provider=sdk_payload.get("tool_slug") or "abenix_preset",
            asset_class="",
            instrument_kind="",
            config={},
            enabled=True,
        )
        db.add(row)
        await db.flush()  # source_id is needed below
    row.last_synced_at = datetime.now(timezone.utc)
    row.last_value = {"value": result.value, "ts": result.ts.isoformat(), **result.payload}
    db.add(ContractIQMarketDataPoint(source_id=row.id, ts=result.ts, payload=row.last_value))
    await db.commit()


async def snapshot(db: AsyncSession, slugs: list[str] | None = None) -> list[dict[str, Any]]:
    if not slugs:
        sources = await list_sources(db)
        slugs = [s["slug"] for s in sources]
    out = []
    for slug in slugs:
        result = await fetch(slug, db)
        out.append({
            "slug": slug,
            "value": result.value,
            "ts": result.ts.isoformat(),
            "unit": result.payload.get("unit") or result.payload.get("metadata", {}).get("alias"),
            "payload": result.payload,
            "error": result.error,
        })
    return out
