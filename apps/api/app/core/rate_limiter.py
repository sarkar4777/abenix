"""Token-bucket rate limiter for per-(tenant, agent) request throttling."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

try:
    from prometheus_client import Counter
except Exception:  # pragma: no cover — prometheus is optional
    Counter = None  # type: ignore

logger = logging.getLogger(__name__)


# Prometheus counters — cheap when disabled (Counter becomes a no-op)
_RATE_LIMIT_HITS: Optional[object] = None
_RATE_LIMIT_FAIL_OPEN: Optional[object] = None

if Counter is not None:
    try:
        _RATE_LIMIT_HITS = Counter(
            "abenix_rate_limit_hits_total",
            "Rate-limit rejections (429s) by tenant + agent",
            ["tenant_id", "agent_slug", "reason"],
        )
        _RATE_LIMIT_FAIL_OPEN = Counter(
            "abenix_rate_limit_fail_open_total",
            "Count of requests that bypassed the limiter because Redis was down",
        )
    except Exception:
        # Duplicated registry (happens in test reloads) — ignore
        pass


@dataclass
class RateLimitDecision:
    allowed: bool
    reason: str = ""  # "qps_exceeded" | "budget_exceeded" | ""
    retry_after_seconds: int = 0
    remaining_tokens: float = 0.0


_LUA_TOKEN_BUCKET = """
local state = redis.call('GET', KEYS[1])
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local needed = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local tokens
local ts
if state then
  local decoded = cjson.decode(state)
  tokens = decoded.tokens
  ts = decoded.ts
  -- refill based on elapsed time
  local elapsed = math.max(0, now - ts)
  tokens = math.min(capacity, tokens + elapsed * refill)
else
  tokens = capacity
end

local allowed = 0
local retry = 0
if tokens >= needed then
  tokens = tokens - needed
  allowed = 1
else
  -- how long until we have enough?
  retry = math.ceil((needed - tokens) / refill)
end

redis.call('SET', KEYS[1], cjson.encode({tokens=tokens, ts=now}), 'EX', 3600)
return {allowed, tostring(tokens), retry}
"""


class RateLimiter:
    """Async token-bucket limiter with Redis backing store."""

    def __init__(self, redis_client) -> None:
        # redis_client is an async-redis client (aioredis / redis.asyncio)
        self.redis = redis_client
        self._lua_sha: Optional[str] = None

    async def _ensure_script(self) -> str:
        if self._lua_sha is None:
            self._lua_sha = await self.redis.script_load(_LUA_TOKEN_BUCKET)
        return self._lua_sha

    async def check(
        self,
        tenant_id: str,
        agent_slug: str,
        qps: int,
    ) -> RateLimitDecision:
        """Apply the token-bucket for this (tenant, agent). qps=None/0 → always allow."""
        if not qps or qps <= 0:
            return RateLimitDecision(allowed=True)

        key = f"rl:{tenant_id}:{agent_slug}"
        capacity = float(qps)  # 1-second burst window
        refill = float(qps)  # steady-state qps
        now = time.time()

        try:
            sha = await self._ensure_script()
            # redis-py async returns bytes; decode_responses=True gives strings
            result = await self.redis.evalsha(sha, 1, key, capacity, refill, 1, now)
        except Exception as e:
            logger.warning("rate_limiter redis failure — failing open: %s", e)
            if _RATE_LIMIT_FAIL_OPEN is not None:
                try:
                    _RATE_LIMIT_FAIL_OPEN.inc()
                except Exception:
                    pass
            return RateLimitDecision(allowed=True)

        allowed = int(result[0]) == 1
        remaining = float(result[1])
        retry_after = int(result[2])

        if not allowed and _RATE_LIMIT_HITS is not None:
            try:
                _RATE_LIMIT_HITS.labels(
                    tenant_id=tenant_id, agent_slug=agent_slug, reason="qps_exceeded"
                ).inc()
            except Exception:
                pass

        return RateLimitDecision(
            allowed=allowed,
            reason="" if allowed else "qps_exceeded",
            retry_after_seconds=retry_after,
            remaining_tokens=remaining,
        )


_limiter: Optional[RateLimiter] = None


def get_limiter(redis_client) -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(redis_client)
    return _limiter


def qps_message(agent_name: str, qps: int, retry_after: int) -> str:
    unit = "run" if qps == 1 else "runs"
    return (
        f"{agent_name} is held to {qps} {unit} per second by its rate limit. "
        f"Try again in {max(1, retry_after)}s, or raise the limit on Admin, Scaling."
    )


async def agent_qps_decision(
    tenant_id: str, agent_key: str, qps: int | None
) -> RateLimitDecision:
    """Apply an agent's rate_limit_qps. Fails open when Redis is unreachable."""
    if not qps or qps <= 0:
        return RateLimitDecision(allowed=True)
    from app.core.hitl import get_redis

    try:
        client = await get_redis()
    except Exception as e:
        logger.warning("rate_limiter redis unavailable, failing open: %s", e)
        return RateLimitDecision(allowed=True)
    return await get_limiter(client).check(str(tenant_id), str(agent_key), int(qps))
