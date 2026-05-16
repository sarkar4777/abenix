"""Provider-level circuit breaker for LLM + external-tool calls."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

try:
    from prometheus_client import Counter
except Exception:
    Counter = None  # type: ignore

logger = logging.getLogger(__name__)

_TRIPS: Optional[object] = None
_FAILFAST: Optional[object] = None

if Counter is not None:
    try:
        _TRIPS = Counter(
            "abenix_circuit_breaker_trips_total",
            "Number of times a provider circuit opened",
            ["provider", "reason"],
        )
        _FAILFAST = Counter(
            "abenix_circuit_breaker_failfast_total",
            "Requests that were failed-fast while the breaker was open",
            ["provider"],
        )
    except Exception:
        pass


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _BreakerState:
    state: State
    failures: int
    opened_at: float  # epoch seconds


class CircuitBreaker:
    """One instance per provider (anthropic, openai, google, gemini...)."""

    def __init__(
        self,
        provider: str,
        redis_client=None,
        fail_threshold: int = 3,
        cooldown_seconds: int = 30,
    ) -> None:
        self.provider = provider
        self.redis = redis_client
        self.fail_threshold = fail_threshold
        self.cooldown_seconds = cooldown_seconds
        # Fallback in-memory state if Redis isn't available
        self._local = _BreakerState(State.CLOSED, 0, 0.0)
        self._key = f"cb:{provider}"
        self._lock = asyncio.Lock()

    async def _load(self) -> _BreakerState:
        if self.redis is None:
            return self._local
        try:
            raw = await self.redis.hgetall(self._key)
            if not raw:
                return self._local

            # redis may return bytes or strings depending on decode_responses
            def get(k, default=0):
                return raw.get(k, raw.get(k.encode(), default))

            state_str = get("state", "closed")
            if isinstance(state_str, bytes):
                state_str = state_str.decode()
            return _BreakerState(
                state=State(state_str),
                failures=int(get("failures", 0)),
                opened_at=float(get("opened_at", 0.0)),
            )
        except Exception as e:
            logger.debug("circuit_breaker redis load failed: %s — using local", e)
            return self._local

    async def _save(self, s: _BreakerState) -> None:
        self._local = s
        if self.redis is None:
            return
        try:
            await self.redis.hset(
                self._key,
                mapping={
                    "state": s.state.value,
                    "failures": s.failures,
                    "opened_at": s.opened_at,
                },
            )
            await self.redis.expire(self._key, 3600)
        except Exception as e:
            logger.debug("circuit_breaker redis save failed: %s — local only", e)

    async def allow(self) -> bool:
        """Return True if a request should be sent; False to fail-fast."""
        s = await self._load()
        now = time.time()
        if s.state == State.OPEN:
            if now - s.opened_at >= self.cooldown_seconds:
                # Try a probe
                s.state = State.HALF_OPEN
                await self._save(s)
                return True
            # Still cooling down
            if _FAILFAST is not None:
                try:
                    _FAILFAST.labels(provider=self.provider).inc()
                except Exception:
                    pass
            return False
        return True

    async def record_success(self) -> None:
        async with self._lock:
            s = await self._load()
            if s.state == State.HALF_OPEN or s.failures > 0:
                s.state = State.CLOSED
                s.failures = 0
                s.opened_at = 0.0
                await self._save(s)

    async def record_failure(self, reason: str = "error") -> None:
        async with self._lock:
            s = await self._load()
            s.failures += 1
            if s.failures >= self.fail_threshold:
                s.state = State.OPEN
                s.opened_at = time.time()
                if _TRIPS is not None:
                    try:
                        _TRIPS.labels(provider=self.provider, reason=reason).inc()
                    except Exception:
                        pass
                logger.warning(
                    "circuit_breaker OPEN for %s (reason=%s, cooldown=%ds)",
                    self.provider,
                    reason,
                    self.cooldown_seconds,
                )
            await self._save(s)


# Module-level registry — one CircuitBreaker per provider
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(provider: str, redis_client=None) -> CircuitBreaker:
    if provider not in _breakers:
        _breakers[provider] = CircuitBreaker(provider, redis_client=redis_client)
    return _breakers[provider]
