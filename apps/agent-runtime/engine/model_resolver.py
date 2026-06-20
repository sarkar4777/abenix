from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


_AVAIL_CACHE: dict[str, dict[str, Any]] = {}
_PRICING_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_AT: float = 0.0
_CACHE_TTL = 60.0


@dataclass
class ResolveResult:
    requested: str
    effective: str
    chain: list[str]
    reason: str


def _sync_db_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return ""
    url = url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")
    if "?" in url:
        base, query = url.split("?", 1)
        kept = [p for p in query.split("&") if not p.lower().startswith("ssl=")]
        url = base + (("?" + "&".join(kept)) if kept else "")
    return url


def _fetch_via_psycopg2(url: str) -> tuple[dict, dict] | None:
    try:
        import psycopg2
    except Exception:
        return None
    conn = psycopg2.connect(url, connect_timeout=2)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT model, status, last_error, last_checked_at FROM model_availability"
            )
            avail = {
                m: {"status": s, "last_error": e, "last_checked_at": t}
                for m, s, e, t in cur.fetchall()
            }
            cur.execute(
                """
                SELECT DISTINCT ON (model) model, provider, input_per_m, output_per_m,
                    capabilities, fallback_to, is_deprecated, is_active
                FROM llm_model_pricing
                WHERE is_active = TRUE
                ORDER BY model, effective_from DESC
                """
            )
            pricing = {}
            for row in cur.fetchall():
                pricing[row[0]] = {
                    "provider": row[1],
                    "input_per_m": float(row[2]),
                    "output_per_m": float(row[3]),
                    "capabilities": row[4] or {},
                    "fallback_to": row[5] or [],
                    "is_deprecated": bool(row[6]) if row[6] is not None else False,
                    "is_active": bool(row[7]),
                }
        return avail, pricing
    finally:
        conn.close()


def _fetch_via_asyncpg(url: str) -> tuple[dict, dict] | None:
    try:
        import asyncio as _asyncio
        import asyncpg
    except Exception:
        return None

    async def _query():
        c = await asyncpg.connect(url, timeout=2)
        try:
            avail_rows = await c.fetch(
                "SELECT model, status, last_error, last_checked_at FROM model_availability"
            )
            pricing_rows = await c.fetch(
                """
                SELECT DISTINCT ON (model) model, provider, input_per_m, output_per_m,
                    capabilities, fallback_to, is_deprecated, is_active
                FROM llm_model_pricing
                WHERE is_active = TRUE
                ORDER BY model, effective_from DESC
                """
            )
        finally:
            await c.close()
        return avail_rows, pricing_rows

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                avail_rows, pricing_rows = ex.submit(
                    lambda: _asyncio.run(_query())
                ).result(timeout=5)
        else:
            avail_rows, pricing_rows = loop.run_until_complete(_query())
    except RuntimeError:
        avail_rows, pricing_rows = _asyncio.run(_query())

    import json as _json

    avail: dict[str, dict[str, Any]] = {}
    for r in avail_rows:
        avail[r["model"]] = {
            "status": r["status"],
            "last_error": r["last_error"],
            "last_checked_at": r["last_checked_at"],
        }
    pricing: dict[str, dict[str, Any]] = {}
    for r in pricing_rows:
        caps = r["capabilities"]
        if isinstance(caps, str):
            try:
                caps = _json.loads(caps)
            except Exception:
                caps = {}
        pricing[r["model"]] = {
            "provider": r["provider"],
            "input_per_m": float(r["input_per_m"]),
            "output_per_m": float(r["output_per_m"]),
            "capabilities": caps or {},
            "fallback_to": list(r["fallback_to"] or []),
            "is_deprecated": (
                bool(r["is_deprecated"]) if r["is_deprecated"] is not None else False
            ),
            "is_active": bool(r["is_active"]),
        }
    return avail, pricing


def _refresh_cache() -> None:
    global _AVAIL_CACHE, _PRICING_CACHE, _CACHE_AT
    now = time.monotonic()
    if _CACHE_AT and (now - _CACHE_AT) < _CACHE_TTL:
        return
    url = _sync_db_url()
    if not url:
        return
    result = None
    last_err: Exception | None = None
    for fetcher in (_fetch_via_psycopg2, _fetch_via_asyncpg):
        try:
            result = fetcher(url)
            if result is not None:
                break
        except Exception as exc:
            last_err = exc
    if result is None:
        if last_err:
            logger.warning("model_resolver cache refresh failed: %s", last_err)
        return
    _AVAIL_CACHE, _PRICING_CACHE = result
    _CACHE_AT = now


def _is_available(model: str) -> bool:
    pricing = _PRICING_CACHE.get(model)
    if pricing and pricing.get("is_deprecated"):
        return False
    avail = _AVAIL_CACHE.get(model)
    if not avail:
        return True
    return str(avail.get("status", "available")).lower() == "available"


def _capable(model: str, required: dict[str, bool]) -> bool:
    if not required:
        return True
    caps = (_PRICING_CACHE.get(model) or {}).get("capabilities") or {}
    for key, need in required.items():
        if need and not caps.get(key, False):
            return False
    return True


def resolve(
    requested: str,
    required_capabilities: dict[str, bool] | None = None,
) -> ResolveResult:
    """Pick the model that should actually receive the request."""
    _refresh_cache()
    required = required_capabilities or {}
    chain: list[str] = [requested]

    if _is_available(requested) and _capable(requested, required):
        return ResolveResult(
            requested=requested, effective=requested, chain=chain, reason="primary"
        )

    pricing = _PRICING_CACHE.get(requested) or {}
    declared = list(pricing.get("fallback_to") or [])
    visited: set[str] = {requested}
    for candidate in declared:
        if candidate in visited:
            continue
        visited.add(candidate)
        chain.append(candidate)
        if _is_available(candidate) and _capable(candidate, required):
            return ResolveResult(
                requested=requested,
                effective=candidate,
                chain=chain,
                reason="declared_fallback",
            )

    by_cost = sorted(
        (
            (m, p)
            for m, p in _PRICING_CACHE.items()
            if m not in visited and not p.get("is_deprecated")
        ),
        key=lambda kv: kv[1]["input_per_m"] + kv[1]["output_per_m"],
    )
    for candidate, _p in by_cost:
        chain.append(candidate)
        if _is_available(candidate) and _capable(candidate, required):
            return ResolveResult(
                requested=requested,
                effective=candidate,
                chain=chain,
                reason="cheapest_capable",
            )

    return ResolveResult(
        requested=requested,
        effective=requested,
        chain=chain,
        reason="no_alternative_giving_up",
    )


def invalidate_cache() -> None:
    global _CACHE_AT
    _CACHE_AT = 0.0
