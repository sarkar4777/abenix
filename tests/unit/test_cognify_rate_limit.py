"""The token bucket waits instead of failing and backoff respects the provider."""

from __future__ import annotations

import asyncio

import pytest

from engine.knowledge.rate_limit import (
    CallLimiter,
    TokenBucket,
    backoff_delay,
    is_retryable,
    with_backoff,
)


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_the_bucket_paces_calls_to_the_rate():
    clock = _Clock()
    bucket = TokenBucket(60, capacity=2, clock=clock, sleep=clock.sleep)

    async def go():
        for _ in range(5):
            await bucket.acquire(1)

    asyncio.run(go())
    assert sum(clock.slept) == pytest.approx(3.0)


def test_tokens_and_requests_both_limit():
    clock = _Clock()
    limiter = CallLimiter(600, 1000, clock=clock, sleep=clock.sleep)

    async def go():
        await limiter.acquire(1000)
        return await limiter.acquire(500)

    waited = asyncio.run(go())
    assert waited == pytest.approx(30.0, abs=0.5)


class _Err(Exception):
    def __init__(self, status=None, msg="boom", retry_after=None):
        super().__init__(msg)
        self.status_code = status
        self.retry_after = retry_after


def test_what_counts_as_retryable():
    assert is_retryable(_Err(429))
    assert is_retryable(_Err(503))
    assert is_retryable(Exception("Rate limit exceeded"))
    assert is_retryable(asyncio.TimeoutError())
    assert not is_retryable(_Err(400))
    assert not is_retryable(ValueError("bad json"))


def test_backoff_is_capped_and_jittered():
    assert all(0 <= backoff_delay(9, base=1, cap=60) <= 60 for _ in range(50))


def test_with_backoff_retries_then_succeeds_and_honours_retry_after():
    clock = _Clock()
    calls = []

    async def call():
        calls.append(1)
        if len(calls) < 3:
            raise _Err(429, retry_after=7)
        return "ok"

    out = asyncio.run(with_backoff(call, sleep=clock.sleep))
    assert out == "ok" and clock.slept == [7.0, 7.0]


def test_with_backoff_gives_up_and_never_retries_a_bad_request():
    clock = _Clock()
    calls = []

    async def rejected():
        calls.append(1)
        raise _Err(400)

    with pytest.raises(_Err):
        asyncio.run(with_backoff(rejected, sleep=clock.sleep))
    assert len(calls) == 1

    async def limited():
        calls.append(1)
        raise _Err(429)

    calls.clear()
    with pytest.raises(_Err):
        asyncio.run(with_backoff(limited, retries=2, sleep=clock.sleep))
    assert len(calls) == 3


def test_a_failed_model_call_is_reported_not_taken_for_an_empty_chunk(monkeypatch):
    from engine.knowledge import entity_extractor as ex

    async def boom(*_a, **_k):
        raise _Err(400, "model rejected this")

    class _Router:
        complete = staticmethod(boom)

    import engine.llm_router as lr

    monkeypatch.setattr(lr, "LLMRouter", _Router)
    out = asyncio.run(ex.extract_from_chunk("text", 3, "doc"))
    assert out.error and "rejected" in out.error and out.entities == []
