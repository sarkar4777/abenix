"""Token bucket and backoff for Cognify model calls."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
RETRYABLE_TEXT = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "overloaded",
    "timeout",
    "timed out",
    "temporarily",
    "connection reset",
    "connection error",
)


class TokenBucket:
    """Refills continuously, a request bigger than the bucket waits for a full one."""

    def __init__(
        self,
        rate_per_minute: float,
        capacity: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.rate = max(float(rate_per_minute), 0.001) / 60.0
        self.capacity = float(capacity if capacity is not None else rate_per_minute)
        self.tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self.tokens = min(
            self.capacity, self.tokens + (now - self._updated) * self.rate
        )
        self._updated = now

    async def acquire(self, amount: float = 1.0) -> float:
        amount = min(float(amount), self.capacity)
        waited = 0.0
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return waited
                delay = (amount - self.tokens) / self.rate
                waited += delay
                await self._sleep(delay)


class CallLimiter:
    """Requests per minute and tokens per minute for one worker process."""

    def __init__(
        self,
        requests_per_minute: float,
        tokens_per_minute: float,
        **kw,
    ) -> None:
        self.requests = TokenBucket(requests_per_minute, **kw)
        self.tokens = TokenBucket(tokens_per_minute, **kw)

    async def acquire(self, estimated_tokens: int) -> float:
        waited = await self.requests.acquire(1)
        waited += await self.tokens.acquire(max(1, estimated_tokens))
        return waited


def is_retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    text = str(exc).lower()
    return any(t in text for t in RETRYABLE_TEXT)


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Full jitter, so workers that were limited together do not return together."""
    return random.uniform(0, min(cap, base * (2**attempt)))


async def with_backoff(
    call: Callable[[], Awaitable[T]],
    retries: int = 5,
    base: float = 1.0,
    cap: float = 60.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as exc:
            if attempt >= retries or not is_retryable(exc):
                raise
            hinted = getattr(exc, "retry_after", None)
            delay = float(hinted) if hinted else backoff_delay(attempt, base, cap)
            await sleep(delay)
            attempt += 1
