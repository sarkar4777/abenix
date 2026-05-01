from __future__ import annotations

import asyncio
import time
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request
from starlette.responses import JSONResponse

from app.core.config import settings


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

    remaining = limit - current_count - 1
    return True, remaining, 0


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _get_user_id(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return None
    from app.core.security import verify_token
    payload = verify_token(auth.removeprefix("Bearer "))
    return payload.get("sub")


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

_DEFAULT_USER_LIMIT = int(_os.environ.get("RATE_LIMIT_USER_REQ_PER_MIN", "300"))
_DEFAULT_ANON_LIMIT = int(_os.environ.get("RATE_LIMIT_ANON_REQ_PER_MIN", "60"))
_DEFAULT_WINDOW = int(_os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
_DEFAULT_AUTH_LIMIT = int(_os.environ.get("RATE_LIMIT_AUTH_REQ_PER_MIN", "30"))


async def rate_limit_user(request: Request, limit: int | None = None, window: int | None = None) -> JSONResponse | None:
    """Rate limit by authenticated user ID, falling back to IP."""
    user_id = _get_user_id(request)
    if user_id:
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
    ip = _get_client_ip(request)
    key = f"auth:{ip}"
    allowed, remaining, retry_after = await sliding_window_check(
        key, _DEFAULT_AUTH_LIMIT, _DEFAULT_WINDOW,
    )
    if not allowed:
        return _rate_limit_response(retry_after)
    return None
