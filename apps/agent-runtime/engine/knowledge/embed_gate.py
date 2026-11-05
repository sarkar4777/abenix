"""Embedding rate limit shared by every worker, with a pause all of them honour after a 429."""

from __future__ import annotations

import email.utils
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# requests waiting on the bucket sleep off the debt, so nobody needs to retry
_RESERVE = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000
local rate = tonumber(ARGV[1])
local cap = tonumber(ARGV[2])
local need = math.min(tonumber(ARGV[3]), cap)
local strict = ARGV[4] == '1'
local state = redis.call('HMGET', KEYS[1], 't', 'ts')
local tokens = tonumber(state[1]) or cap
local ts = tonumber(state[2]) or now
tokens = math.min(cap, tokens + math.max(0, now - ts) * rate)
local wait = 0
if tokens < need then wait = (need - tokens) / rate end
if wait == 0 or not strict then tokens = tokens - need end
redis.call('HSET', KEYS[1], 't', tostring(tokens), 'ts', tostring(now))
redis.call('EXPIRE', KEYS[1], 3600)
return tostring(wait)
"""


def _redis_client() -> Any:
    import redis

    url = (
        os.environ.get("KB_RATE_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or os.environ.get("CELERY_BROKER_URL")
    )
    if not url:
        return None
    return redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)


class _LocalBucket:
    def __init__(self, rate: float, cap: float) -> None:
        self.rate, self.cap = rate, cap
        self.tokens, self.ts = cap, time.monotonic()
        self.lock = threading.Lock()

    def reserve(self, need: float, strict: bool = False) -> float:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.cap, self.tokens + (now - self.ts) * self.rate)
            self.ts = now
            need = min(need, self.cap)
            wait = (need - self.tokens) / self.rate if self.tokens < need else 0.0
            if wait == 0 or not strict:
                self.tokens -= need
            return wait


class RateGate:
    """Requests and tokens per minute under one name, in Redis when it answers."""

    def __init__(
        self,
        name: str,
        requests_per_minute: float,
        tokens_per_minute: float,
        client: Any = None,
    ) -> None:
        self.name = name
        self.limits = {
            "requests": max(requests_per_minute, 1.0),
            "tokens": max(tokens_per_minute, 1.0),
        }
        self._client = client
        self._client_loaded = client is not None
        self._local = {
            kind: _LocalBucket(limit / 60.0, limit)
            for kind, limit in self.limits.items()
        }
        self._local_pause = 0.0
        self._warned = False

    def _redis(self) -> Any:
        if not self._client_loaded:
            self._client_loaded = True
            try:
                self._client = _redis_client()
            except Exception as exc:
                logger.warning("embedding rate limit stays local: %s", exc)
        return self._client

    def _fell_back(self, exc: Exception) -> None:
        if not self._warned:
            self._warned = True
            logger.warning("embedding rate limit stays local, redis said %s", exc)

    def _reserve(self, kind: str, amount: float, strict: bool = False) -> float:
        limit = self.limits[kind]
        client = self._redis()
        if client is not None:
            try:
                return float(
                    client.eval(
                        _RESERVE,
                        1,
                        f"kb:gate:{self.name}:{kind}",
                        limit / 60.0,
                        limit,
                        amount,
                        "1" if strict else "0",
                    )
                )
            except Exception as exc:
                self._fell_back(exc)
        return self._local[kind].reserve(amount, strict)

    def pause_remaining(self) -> float:
        client = self._redis()
        if client is not None:
            try:
                ms = client.pttl(f"kb:gate:{self.name}:pause")
                return max(0.0, ms / 1000.0) if ms and ms > 0 else 0.0
            except Exception as exc:
                self._fell_back(exc)
        return max(0.0, self._local_pause - time.monotonic())

    def pause(self, seconds: float) -> None:
        """Hold every worker on this provider, a shorter hint never cuts a longer one."""
        self._local_pause = max(self._local_pause, time.monotonic() + seconds)
        client = self._redis()
        if client is None:
            return
        try:
            key = f"kb:gate:{self.name}:pause"
            if self.pause_remaining() < seconds:
                client.set(key, "1", px=max(1, int(seconds * 1000)))
        except Exception as exc:
            self._fell_back(exc)

    def wait_needed(self, tokens: float) -> float:
        wait = max(self.pause_remaining(), 0.0)
        wait = max(wait, self._reserve("requests", 1))
        return max(wait, self._reserve("tokens", max(tokens, 1)))

    def acquire(self, tokens: float = 1) -> float:
        wait = self.wait_needed(tokens)
        if wait > 0:
            time.sleep(wait)
        return wait

    def try_acquire(self, tokens: float = 1) -> bool:
        """For optional work, go ahead now or skip it, a refusal spends nothing."""
        if self.pause_remaining() > 0 or self._reserve("requests", 1, strict=True) > 0:
            return False
        return self._reserve("tokens", max(tokens, 1), strict=True) <= 0


def estimate_tokens(texts: list[str]) -> int:
    return max(1, sum(len(t) for t in texts) // 4)


def retry_after_seconds(exc: BaseException) -> float | None:
    """What the provider asked for, from the response headers on the SDK error."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None)
    if not headers:
        return None
    ms = headers.get("retry-after-ms")
    if ms:
        try:
            return max(0.0, float(ms) / 1000.0)
        except ValueError:
            pass
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        return max(0.0, parsed.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


_GATES: dict[str, RateGate] = {}
_GATES_LOCK = threading.Lock()


def embed_gate(provider: str) -> RateGate:
    with _GATES_LOCK:
        gate = _GATES.get(provider)
        if gate is None:
            gate = RateGate(
                f"embed:{provider}",
                float(os.environ.get("KB_EMBED_RPM", "3000")),
                float(os.environ.get("KB_EMBED_TPM", "1000000")),
            )
            _GATES[provider] = gate
        return gate


def rerank_gate(tenant_id: str) -> RateGate:
    key = f"rerank:{tenant_id or 'none'}"
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            per_minute = float(os.environ.get("KB_RERANK_PER_MINUTE", "60"))
            gate = RateGate(key, per_minute, 1e9)
            _GATES[key] = gate
        return gate
