"""Shared rate limit and backoff for Cognify model calls."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from engine.knowledge.embed_gate import RateGate, cognify_gate, retry_after_seconds

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


class CallLimiter:
    """Requests and tokens per minute on the gate every Cognify worker shares."""

    def __init__(
        self,
        provider: str,
        requests_per_minute: float,
        tokens_per_minute: float,
        gate: RateGate | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.gate = gate or cognify_gate(
            provider, requests_per_minute, tokens_per_minute
        )
        self._sleep = sleep

    async def acquire(self, estimated_tokens: int) -> float:
        wait = await asyncio.to_thread(self.gate.wait_needed, estimated_tokens)
        if wait > 0:
            await self._sleep(wait)
        return wait

    async def after_failure(self, exc: BaseException) -> None:
        """A provider that names a wait holds every worker for that long."""
        hinted = getattr(exc, "retry_after", None) or retry_after_seconds(exc)
        if hinted and is_retryable(exc):
            await asyncio.to_thread(self.gate.pause, float(hinted))


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
