"""Tests for adaptive retry strategies."""

import pytest
from engine.adaptive_retry import RetryPolicy, RetryResult, retry_with_policy


class TestFixedRetry:
    @pytest.mark.asyncio
    async def test_success_first_try(self):
        call_count = 0

        async def succeed(**kwargs):
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_with_policy(succeed, {}, RetryPolicy(strategy="fixed"))
        assert result.success is True
        assert result.attempts == 1
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_fail_then_succeed(self):
        call_count = 0

        async def flaky(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "ok"

        policy = RetryPolicy(strategy="fixed", max_retries=3, base_delay=0.01)
        result = await retry_with_policy(flaky, {}, policy)
        assert result.success is True
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self):
        async def always_fail(**kwargs):
            raise ValueError("permanent error")

        policy = RetryPolicy(strategy="fixed", max_retries=2, base_delay=0.01)
        result = await retry_with_policy(always_fail, {}, policy)
        assert result.success is False
        assert result.attempts == 3  # initial + 2 retries
        assert "permanent error" in result.final_error

    @pytest.mark.asyncio
    async def test_zero_retries(self):
        async def fail(**kwargs):
            raise ValueError("fail")

        policy = RetryPolicy(strategy="fixed", max_retries=0, base_delay=0.01)
        result = await retry_with_policy(fail, {}, policy)
        assert result.success is False
        assert result.attempts == 1

    @pytest.mark.asyncio
    async def test_args_passed_through(self):
        received = {}

        async def capture(**kwargs):
            received.update(kwargs)
            return "ok"

        await retry_with_policy(capture, {"query": "test", "limit": 10}, RetryPolicy())
        assert received == {"query": "test", "limit": 10}


class TestRetryResult:
    def test_success_result(self):
        r = RetryResult(success=True, result="data", attempts=1)
        assert r.success is True
        assert r.result == "data"

    def test_failure_result(self):
        r = RetryResult(success=False, final_error="timeout", attempts=3)
        assert r.success is False
        assert "timeout" in r.final_error
