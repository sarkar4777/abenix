"""Tool runtime gate — cache, semaphore, rate-limit, breaker.

Every tool call (direct SDK, preset run, agent loop, pipeline step) goes
through one function: ``gate.acquire(...)``. It returns one of:

  ALLOW_CACHED   — the cached result; no execution needed
  ALLOW          — caller must execute the tool, then call ``release()``
  DENY           — reason string for the caller to surface to the user

The gate stores its state in Redis so all api/agent-runtime/worker pods
see the same numbers. Falls open (allow) on Redis errors so an outage
doesn't take the platform down — see RateLimiter for the same pattern.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.core.execution_state import _get_redis

logger = logging.getLogger(__name__)


@dataclass
class GateConfig:
    enabled: bool = True
    pool: str = "inline"  # inline | runtime
    max_inflight_global: int = 50
    max_inflight_per_tenant: int = 20
    rate_limit_qps_global: int = 0
    rate_limit_qps_per_tenant: int = 0
    cache_ttl_seconds: int = 0
    cache_scope: str = "global"  # global | per_tenant
    circuit_breaker_threshold: int = 0
    circuit_breaker_window_s: int = 30
    circuit_breaker_cooldown_s: int = 60
    timeout_seconds: int = 30
    daily_budget_calls_per_tenant: int = 0


@dataclass
class GateDecision:
    allowed: bool
    cached: bool = False
    cached_value: Optional[dict[str, Any]] = None
    reason: str = ""
    token: Optional[str] = None  # opaque handle for release()
    cache_key: Optional[str] = None  # so release() can store result
    config: Optional[GateConfig] = None
    started_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


_DEFAULT_CONFIG = GateConfig()


def _canonical_args_hash(arguments: dict[str, Any]) -> str:
    """Stable hash for cache key. Sorts keys and stringifies."""
    blob = json.dumps(arguments or {}, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:24]


def _cache_key(slug: str, tenant_id: str, args_hash: str, scope: str) -> str:
    if scope == "per_tenant":
        return f"toolcache:{slug}:{tenant_id}:{args_hash}"
    return f"toolcache:{slug}:_:{args_hash}"


# leases, one member per call with its own expiry, so a call that never releases frees itself
def _sem_key_global(slug: str) -> str:
    return f"toollease:{slug}:_global"


def _sem_key_tenant(slug: str, tenant_id: str) -> str:
    return f"toollease:{slug}:{tenant_id}"


def _breaker_key(slug: str) -> str:
    return f"toolbreaker:{slug}"


def _budget_key(slug: str, tenant_id: str) -> str:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"toolbudget:{slug}:{tenant_id}:{today}"


# ── Token bucket Lua (per-key) ────────────────────────────────────────────
_LUA_BUCKET = """
local state = redis.call('GET', KEYS[1])
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens, ts
if state then
  local d = cjson.decode(state)
  tokens = math.min(capacity, d.tokens + math.max(0, now - d.ts) * refill)
else
  tokens = capacity
end
local allowed = 0
local retry = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry = math.ceil((1 - tokens) / math.max(refill, 0.0001))
end
redis.call('SET', KEYS[1], cjson.encode({tokens=tokens, ts=now}), 'EX', 600)
return {allowed, retry}
"""


async def _bucket_take(r, key: str, qps: int) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    if qps <= 0:
        return True, 0
    try:
        res = await r.eval(_LUA_BUCKET, 1, key, float(qps), float(qps), time.time())
        return int(res[0]) == 1, int(res[1])
    except Exception as e:
        logger.warning("tool_gate bucket failure (fail open): %s", e)
        return True, 0


async def _sem_acquire(r, key: str, cap: int, ttl_s: int, member: str) -> bool:
    """Take a lease that expires after ttl_s. A cancelled or crashed call frees its slot by itself."""
    if cap <= 0:
        return True
    try:
        now = time.time()
        await r.zremrangebyscore(key, "-inf", now)
        await r.zadd(key, {member: now + ttl_s})
        await r.expire(key, int(ttl_s) + 60)
        if await r.zcard(key) > cap:
            await r.zrem(key, member)
            return False
        return True
    except Exception as e:
        logger.warning("tool_gate sem failure (fail open): %s", e)
        return True


async def _sem_release(r, key: str, member: str) -> None:
    try:
        await r.zrem(key, member)
    except Exception:
        pass


async def _sem_count(r, key: str) -> int:
    await r.zremrangebyscore(key, "-inf", time.time())
    return int(await r.zcard(key) or 0)


async def _cache_get(r, key: str) -> Optional[dict[str, Any]]:
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(r, key: str, value: dict[str, Any], ttl_s: int) -> None:
    if ttl_s <= 0:
        return
    try:
        await r.set(key, json.dumps(value, default=str), ex=ttl_s)
    except Exception:
        pass


async def _breaker_state(r, slug: str) -> str:
    """Returns one of 'closed' | 'open' | 'half_open'."""
    try:
        raw = await r.get(_breaker_key(slug))
        if not raw:
            return "closed"
        d = json.loads(raw)
        if d.get("state") == "open":
            if time.time() - d.get("opened_at", 0) > d.get("cooldown_s", 60):
                return "half_open"
            return "open"
        return "closed"
    except Exception:
        return "closed"


async def _breaker_record_failure(
    r, slug: str, threshold: int, window_s: int, cooldown_s: int
):
    if threshold <= 0:
        return
    try:
        raw = await r.get(_breaker_key(slug))
        d = json.loads(raw) if raw else {"failures": [], "state": "closed"}
        now = time.time()
        # Drop old failures outside the window
        d["failures"] = [t for t in d.get("failures", []) if now - t < window_s]
        d["failures"].append(now)
        if len(d["failures"]) >= threshold:
            d["state"] = "open"
            d["opened_at"] = now
            d["cooldown_s"] = cooldown_s
        await r.set(
            _breaker_key(slug), json.dumps(d), ex=max(window_s, cooldown_s) + 60
        )
    except Exception:
        pass


async def _breaker_record_success(r, slug: str):
    """Half-open success closes the breaker; closed-state stays closed."""
    try:
        raw = await r.get(_breaker_key(slug))
        if raw:
            d = json.loads(raw)
            if d.get("state") in ("open", "half_open"):
                d["state"] = "closed"
                d["failures"] = []
                await r.set(_breaker_key(slug), json.dumps(d), ex=300)
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────


async def load_config(slug: str, db) -> GateConfig:
    """Read the per-tool config row. Returns defaults if no row exists."""
    try:
        from sqlalchemy import select

        from models.tool_runtime_config import ToolRuntimeConfig

        row = (
            await db.execute(
                select(ToolRuntimeConfig).where(ToolRuntimeConfig.slug == slug)
            )
        ).scalar_one_or_none()
        if row is None:
            return _DEFAULT_CONFIG
        return GateConfig(
            enabled=row.enabled,
            pool=row.pool,
            max_inflight_global=row.max_inflight_global,
            max_inflight_per_tenant=row.max_inflight_per_tenant,
            rate_limit_qps_global=row.rate_limit_qps_global,
            rate_limit_qps_per_tenant=row.rate_limit_qps_per_tenant,
            cache_ttl_seconds=row.cache_ttl_seconds,
            cache_scope=row.cache_scope,
            circuit_breaker_threshold=row.circuit_breaker_threshold,
            circuit_breaker_window_s=row.circuit_breaker_window_s,
            circuit_breaker_cooldown_s=row.circuit_breaker_cooldown_s,
            timeout_seconds=row.timeout_seconds,
            daily_budget_calls_per_tenant=row.daily_budget_calls_per_tenant,
        )
    except Exception as e:
        logger.warning("load_config %s failed (using defaults): %s", slug, e)
        return _DEFAULT_CONFIG


async def acquire(
    tool_slug: str,
    tenant_id: str,
    arguments: dict[str, Any],
    db,
) -> GateDecision:
    cfg = await load_config(tool_slug, db)
    if not cfg.enabled:
        return GateDecision(
            allowed=False, reason=f"tool '{tool_slug}' is disabled by admin", config=cfg
        )

    r = await _get_redis()
    if r is None:
        # Redis down — fail open with no caching/limiting, only feature-flag.
        return GateDecision(allowed=True, config=cfg, started_at=time.time())

    args_hash = _canonical_args_hash(arguments)
    cache_key = _cache_key(tool_slug, tenant_id, args_hash, cfg.cache_scope)

    # 1. Cache lookup
    if cfg.cache_ttl_seconds > 0:
        cached = await _cache_get(r, cache_key)
        if cached is not None:
            return GateDecision(
                allowed=True,
                cached=True,
                cached_value=cached,
                config=cfg,
                cache_key=cache_key,
                started_at=time.time(),
            )

    # 2. Circuit breaker
    state = await _breaker_state(r, tool_slug)
    if state == "open":
        return GateDecision(
            allowed=False, reason=f"circuit breaker open for '{tool_slug}'", config=cfg
        )

    # 3. Rate limits
    if cfg.rate_limit_qps_global > 0:
        ok, retry = await _bucket_take(
            r, f"toolqps:{tool_slug}:_", cfg.rate_limit_qps_global
        )
        if not ok:
            return GateDecision(
                allowed=False, reason=f"rate limit (global, retry {retry}s)", config=cfg
            )
    if cfg.rate_limit_qps_per_tenant > 0:
        ok, retry = await _bucket_take(
            r, f"toolqps:{tool_slug}:{tenant_id}", cfg.rate_limit_qps_per_tenant
        )
        if not ok:
            return GateDecision(
                allowed=False,
                reason=f"rate limit (per-tenant, retry {retry}s)",
                config=cfg,
            )

    # 4. Daily budget
    if cfg.daily_budget_calls_per_tenant > 0:
        try:
            v = await r.incr(_budget_key(tool_slug, tenant_id))
            if v == 1:
                await r.expire(_budget_key(tool_slug, tenant_id), 26 * 3600)
            if v > cfg.daily_budget_calls_per_tenant:
                await r.decr(_budget_key(tool_slug, tenant_id))
                return GateDecision(
                    allowed=False, reason="daily budget exhausted", config=cfg
                )
        except Exception:
            pass

    # 5. Concurrency
    import uuid as _uuid

    lease = _uuid.uuid4().hex
    lease_ttl = int(cfg.timeout_seconds or 60) + 30
    if not await _sem_acquire(
        r,
        _sem_key_global(tool_slug),
        cfg.max_inflight_global,
        lease_ttl,
        lease,
    ):
        return GateDecision(
            allowed=False, reason=f"{tool_slug} at global concurrency cap", config=cfg
        )
    if not await _sem_acquire(
        r,
        _sem_key_tenant(tool_slug, tenant_id),
        cfg.max_inflight_per_tenant,
        lease_ttl,
        lease,
    ):
        await _sem_release(r, _sem_key_global(tool_slug), lease)
        return GateDecision(
            allowed=False,
            reason=f"{tool_slug} at per-tenant concurrency cap",
            config=cfg,
        )

    token = lease
    return GateDecision(
        allowed=True,
        config=cfg,
        cache_key=cache_key,
        token=token,
        started_at=time.time(),
    )


async def release(
    decision: GateDecision,
    tool_slug: str,
    tenant_id: str,
    *,
    ok: bool,
    result_payload: Optional[dict[str, Any]] = None,
) -> None:
    if decision.cached:
        # Cache hit short-circuited; nothing acquired.
        return
    cfg = decision.config or _DEFAULT_CONFIG
    r = await _get_redis()
    if r is None:
        return

    # Release the leases (acquired in this exact order)
    if decision.token:
        await _sem_release(r, _sem_key_tenant(tool_slug, tenant_id), decision.token)
        await _sem_release(r, _sem_key_global(tool_slug), decision.token)

    # Cache success result
    if (
        ok
        and cfg.cache_ttl_seconds > 0
        and decision.cache_key
        and result_payload is not None
    ):
        await _cache_set(r, decision.cache_key, result_payload, cfg.cache_ttl_seconds)

    # Circuit-breaker state machine
    if ok:
        await _breaker_record_success(r, tool_slug)
    else:
        await _breaker_record_failure(
            r,
            tool_slug,
            cfg.circuit_breaker_threshold,
            cfg.circuit_breaker_window_s,
            cfg.circuit_breaker_cooldown_s,
        )


async def stats(tool_slug: str) -> dict[str, Any]:
    """Live counters — what the admin UI shows."""
    r = await _get_redis()
    if r is None:
        return {"slug": tool_slug, "redis": False}
    out: dict[str, Any] = {"slug": tool_slug, "redis": True}
    try:
        out["inflight_global"] = await _sem_count(r, _sem_key_global(tool_slug))
        out["breaker_state"] = await _breaker_state(r, tool_slug)
    except Exception:
        pass
    return out
