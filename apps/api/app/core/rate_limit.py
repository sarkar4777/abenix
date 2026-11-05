from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
import time

import redis.asyncio as aioredis
from fastapi import Request
from starlette.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

_REDIS_POOL: dict[str, aioredis.Redis] = {}
_REDIS_LOCK = asyncio.Lock()


async def _get_redis() -> aioredis.Redis:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    pool_key = f"{settings.redis_url}|{id(loop)}"
    existing = _REDIS_POOL.get(pool_key)
    if existing is not None:
        return existing
    async with _REDIS_LOCK:
        existing = _REDIS_POOL.get(pool_key)
        if existing is not None:
            return existing
        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=50,
            socket_keepalive=True,
            health_check_interval=30,
        )
        _REDIS_POOL[pool_key] = client
        return client


async def sliding_window_check(
    key: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int, int]:
    """Check if a key has exceeded its rate limit using a Redis sliding window.

    Returns (allowed, remaining, retry_after_seconds).
    """
    try:
        r = await _get_redis()
        now = time.time()
        window_start = now - window_seconds
        pipe_key = f"abenix:ratelimit:{key}"

        pipe = r.pipeline()
        pipe.zremrangebyscore(pipe_key, 0, window_start)
        pipe.zcard(pipe_key)
        pipe.zadd(pipe_key, {str(now): now})
        pipe.expire(pipe_key, window_seconds + 1)
        results = await pipe.execute()

        current_count = results[1]
        if current_count >= limit:
            oldest = await r.zrange(pipe_key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(oldest[0][1] + window_seconds - now) + 1
            else:
                retry_after = window_seconds
            await r.zrem(pipe_key, str(now))
            return False, 0, max(retry_after, 1)
    except (aioredis.RedisError, OSError) as e:
        # a limiter outage must not become an API outage
        logger.warning("rate limit skipped, Redis is unavailable (%s)", e)
        return True, limit, 0

    remaining = limit - current_count - 1
    return True, remaining, 0


def client_ip_from(peer: str | None, forwarded: str | None) -> str:
    """The first public address from the right, a caller controls only the left of the list."""
    if not forwarded or not _peer_is_proxy(peer):
        return peer or "unknown"
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_internal(hop):
            return hop
    return hops[0] if hops else (peer or "unknown")


def _peer_is_proxy(peer: str | None) -> bool:
    if not peer:
        return True
    try:
        ipaddress.ip_address(peer.strip())
    except ValueError:
        return True
    return _is_internal(peer)


def _is_internal(address: str | None) -> bool:
    try:
        ip = ipaddress.ip_address((address or "").strip())
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else None
    return client_ip_from(peer, request.headers.get("x-forwarded-for"))


def _get_user_id(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or auth.startswith("Bearer af_"):
        return None
    from app.core.security import verify_token

    payload = verify_token(auth.removeprefix("Bearer "))
    return payload.get("sub")


_API_KEY_IDS: dict[str, tuple[float, str]] = {}
_API_KEY_ID_TTL = 60.0


def _raw_api_key(request: Request) -> str:
    raw = request.headers.get("x-api-key", "")
    if raw.startswith("af_"):
        return raw
    auth = request.headers.get("authorization", "")
    return auth.removeprefix("Bearer ") if auth.startswith("Bearer af_") else ""


async def _lookup_api_key_id(key_hash: str) -> str | None:
    from sqlalchemy import select

    from app.core.deps import async_session
    from models.api_key import ApiKey

    try:
        async with async_session() as db:
            row = (
                await db.execute(
                    select(ApiKey.id).where(
                        ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True)
                    )
                )
            ).first()
    except Exception as e:  # noqa: BLE001
        logger.warning("api key lookup for the rate limit failed (%s)", e)
        return None
    return str(row[0]) if row else None


async def _api_key_id(request: Request) -> str | None:
    """The id of a real key. Made up keys get no bucket of their own, they stay on the IP limit."""
    raw = _raw_api_key(request)
    if not raw:
        return None
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    now = time.monotonic()
    hit = _API_KEY_IDS.get(key_hash)
    if hit and hit[0] > now:
        return hit[1]
    key_id = await _lookup_api_key_id(key_hash)
    if key_id:
        if len(_API_KEY_IDS) > 4096:
            _API_KEY_IDS.clear()
        _API_KEY_IDS[key_hash] = (now + _API_KEY_ID_TTL, key_id)
    return key_id


def _rate_limit_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "data": None,
            "error": {
                "message": "Rate limit exceeded. Try again later.",
                "code": 429,
            },
        },
        headers={"Retry-After": str(retry_after)},
    )


import os as _os

# Defaults — production-safe. Local dev gets a much higher ceiling so the
# UAT suite doesn't hit 429 mid-run and the next developer doesn't have to
# learn the magic envvar bump the hard way.
#
# Two triggers for dev mode (either one flips the ceiling):
#   * IS_LOCAL_DEV=1 — explicit opt-in, cluster sets it via dev helm values
#   * ENVIRONMENT=local — the standard knob the rest of the stack reads;
#     picking it up here means scripts/dev-local.sh (which exports
#     ENVIRONMENT=local) gets the dev ceiling automatically, so the next
#     dev doesn't have to learn the IS_LOCAL_DEV bump the hard way.
# API keys flagged with `bypass_rate_limit` in the DB also skip the gate
# via _is_dev_bypass below.
_IS_LOCAL_DEV = _os.environ.get("IS_LOCAL_DEV", "").lower() in (
    "1",
    "true",
    "yes",
) or _os.environ.get("ENVIRONMENT", "").lower() in ("local", "dev", "development")

# Prod defaults — explicit. Devs can still override via env, but the
# committed default is the right one for prod.
_PROD_USER_LIMIT = 300
_PROD_ANON_LIMIT = 60
_PROD_AUTH_LIMIT = 30
_PROD_WINDOW = 60

# Dev-mode bumps. Picked to be high enough for the full 111-test UAT suite
# + parallel browser smoke without ever hitting 429. The per-IP (anon)
# ceiling matters for the pipeline_gas live UAT because the polling loop
# hammers a single IP while the agent is still iterating.
_DEV_USER_LIMIT = 5000
_DEV_ANON_LIMIT = 5000
_DEV_AUTH_LIMIT = 5000

_DEFAULT_USER_LIMIT = int(
    _os.environ.get(
        "RATE_LIMIT_USER_REQ_PER_MIN",
        str(_DEV_USER_LIMIT if _IS_LOCAL_DEV else _PROD_USER_LIMIT),
    )
)
_DEFAULT_ANON_LIMIT = int(
    _os.environ.get(
        "RATE_LIMIT_ANON_REQ_PER_MIN",
        str(_DEV_ANON_LIMIT if _IS_LOCAL_DEV else _PROD_ANON_LIMIT),
    )
)
_DEFAULT_WINDOW = int(_os.environ.get("RATE_LIMIT_WINDOW_SECONDS", str(_PROD_WINDOW)))
_DEFAULT_AUTH_LIMIT = int(
    _os.environ.get(
        "RATE_LIMIT_AUTH_REQ_PER_MIN",
        str(_DEV_AUTH_LIMIT if _IS_LOCAL_DEV else _PROD_AUTH_LIMIT),
    )
)


def _is_dev_bypass(request: Request) -> bool:
    """Per-API-key bypass for the rate limiter.

    A request is bypassed when:
      - IS_LOCAL_DEV=1 (env), OR
      - the X-RateLimit-Bypass header carries the RATE_LIMIT_BYPASS_TOKEN
        env value (used by the deploy-azure UAT runner so a single op
        can issue a one-shot key without touching the limit defaults).
    """
    if _IS_LOCAL_DEV:
        return True
    token = _os.environ.get("RATE_LIMIT_BYPASS_TOKEN", "")
    if token and request.headers.get("x-ratelimit-bypass", "") == token:
        return True
    return False


async def rate_limit_user(
    request: Request, limit: int | None = None, window: int | None = None
) -> JSONResponse | None:
    """Rate limit by authenticated user ID, falling back to IP."""
    if _is_dev_bypass(request):
        return None
    user_id = _get_user_id(request)
    api_key_id = None if user_id else await _api_key_id(request)
    if api_key_id:
        key = f"apikey:{api_key_id}"
        lim = limit if limit is not None else _DEFAULT_USER_LIMIT
    elif user_id:
        key = f"user:{user_id}"
        lim = limit if limit is not None else _DEFAULT_USER_LIMIT
    else:
        key = f"ip:{_get_client_ip(request)}"
        lim = limit if limit is not None else _DEFAULT_ANON_LIMIT

    win = window if window is not None else _DEFAULT_WINDOW
    allowed, remaining, retry_after = await sliding_window_check(key, lim, win)
    if not allowed:
        return _rate_limit_response(retry_after)
    return None


async def rate_limit_auth(request: Request) -> JSONResponse | None:
    """Stricter rate limit for auth endpoints. Default 30 req/min by IP —"""
    if _is_dev_bypass(request):
        return None
    ip = _get_client_ip(request)
    key = f"auth:{ip}"
    allowed, remaining, retry_after = await sliding_window_check(
        key,
        _DEFAULT_AUTH_LIMIT,
        _DEFAULT_WINDOW,
    )
    if not allowed:
        return _rate_limit_response(retry_after)
    return None
