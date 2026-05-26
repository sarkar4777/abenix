"""Admin router for per-tool runtime config + live stats.

Drives the /admin/tool-scaling UI page. Org-wide knobs (not per-tenant);
per-tenant fairness is enforced inside the gate using ``*_per_tenant``
columns layered on top.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import tool_gate
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success

from models.tool_invocation import ToolInvocation
from models.tool_runtime_config import ToolRuntimeConfig
from models.user import User

router = APIRouter(prefix="/api/admin/tool-runtime", tags=["admin", "tool-runtime"])


def _serialize(row: ToolRuntimeConfig) -> dict[str, Any]:
    return {
        "slug": row.slug,
        "enabled": row.enabled,
        "pool": row.pool,
        "max_inflight_global": row.max_inflight_global,
        "max_inflight_per_tenant": row.max_inflight_per_tenant,
        "rate_limit_qps_global": row.rate_limit_qps_global,
        "rate_limit_qps_per_tenant": row.rate_limit_qps_per_tenant,
        "cache_ttl_seconds": row.cache_ttl_seconds,
        "cache_scope": row.cache_scope,
        "circuit_breaker_threshold": row.circuit_breaker_threshold,
        "circuit_breaker_window_s": row.circuit_breaker_window_s,
        "circuit_breaker_cooldown_s": row.circuit_breaker_cooldown_s,
        "timeout_seconds": row.timeout_seconds,
        "daily_budget_calls_per_tenant": row.daily_budget_calls_per_tenant,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
async def list_configs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Return one row per tool slug. Joined with 24h call counts + last-run latency."""
    rows = (await db.execute(select(ToolRuntimeConfig))).scalars().all()
    by_slug = {r.slug: _serialize(r) for r in rows}

    # 24h call counts + last latency, grouped by slug
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    counts = (
        await db.execute(
            select(
                ToolInvocation.tool_slug,
                func.count(ToolInvocation.id),
                func.avg(ToolInvocation.duration_ms),
            )
            .where(ToolInvocation.created_at >= since)
            .group_by(ToolInvocation.tool_slug)
        )
    ).all()

    out: list[dict[str, Any]] = []
    seen = set()
    for slug, calls, avg_ms in counts:
        cfg = by_slug.get(slug) or {"slug": slug, "configured": False}
        cfg.update(
            {
                "calls_24h": int(calls or 0),
                "avg_ms": int(avg_ms or 0),
                "configured": slug in by_slug,
            }
        )
        live = await tool_gate.stats(slug)
        cfg["inflight_global"] = live.get("inflight_global")
        cfg["breaker_state"] = live.get("breaker_state")
        out.append(cfg)
        seen.add(slug)
    # Also list configured rows that had zero 24h traffic
    for slug, cfg in by_slug.items():
        if slug in seen:
            continue
        cfg["calls_24h"] = 0
        cfg["avg_ms"] = 0
        cfg["configured"] = True
        live = await tool_gate.stats(slug)
        cfg["inflight_global"] = live.get("inflight_global")
        cfg["breaker_state"] = live.get("breaker_state")
        out.append(cfg)
    out.sort(key=lambda r: r.get("calls_24h", 0), reverse=True)
    return success(out, meta={"count": len(out)})


@router.get("/{slug}")
async def get_config(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ToolRuntimeConfig).where(ToolRuntimeConfig.slug == slug)
        )
    ).scalar_one_or_none()
    if row is None:
        # Return defaults so the UI can render even before the first save.
        return success(
            {
                "slug": slug,
                "configured": False,
                "enabled": True,
                "pool": "inline",
                "max_inflight_global": 50,
                "max_inflight_per_tenant": 20,
                "rate_limit_qps_global": 0,
                "rate_limit_qps_per_tenant": 0,
                "cache_ttl_seconds": 0,
                "cache_scope": "global",
                "circuit_breaker_threshold": 0,
                "circuit_breaker_window_s": 30,
                "circuit_breaker_cooldown_s": 60,
                "timeout_seconds": 30,
                "daily_budget_calls_per_tenant": 0,
            }
        )
    return success({**_serialize(row), "configured": True})


@router.post("")
async def upsert_config(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    slug = body.get("slug")
    if not slug:
        return error("slug is required", 400)
    row = (
        await db.execute(
            select(ToolRuntimeConfig).where(ToolRuntimeConfig.slug == slug)
        )
    ).scalar_one_or_none()
    fields = [
        "enabled",
        "pool",
        "max_inflight_global",
        "max_inflight_per_tenant",
        "rate_limit_qps_global",
        "rate_limit_qps_per_tenant",
        "cache_ttl_seconds",
        "cache_scope",
        "circuit_breaker_threshold",
        "circuit_breaker_window_s",
        "circuit_breaker_cooldown_s",
        "timeout_seconds",
        "daily_budget_calls_per_tenant",
    ]
    if row is None:
        row = ToolRuntimeConfig(slug=slug)
        db.add(row)
    for f in fields:
        if f in body and body[f] is not None:
            setattr(row, f, body[f])
    await db.commit()
    await db.refresh(row)
    return success(_serialize(row))
