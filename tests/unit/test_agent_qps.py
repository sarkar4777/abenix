from __future__ import annotations

import pytest

from app.core import rate_limiter
from app.core.failure_codes import classify_exception


class _Bucket:
    """Stands in for Redis, runs the token bucket in Python."""

    def __init__(self) -> None:
        self.state: dict[str, tuple[float, float]] = {}

    async def script_load(self, _script: str) -> str:
        return "sha"

    async def evalsha(self, _sha, _n, key, capacity, refill, needed, now):
        tokens, ts = self.state.get(key, (capacity, now))
        tokens = min(capacity, tokens + max(0, now - ts) * refill)
        if tokens >= needed:
            self.state[key] = (tokens - needed, now)
            return [1, str(tokens - needed), 0]
        self.state[key] = (tokens, now)
        return [0, str(tokens), 1]


@pytest.fixture
def bucket(monkeypatch):
    fake = _Bucket()
    monkeypatch.setattr(rate_limiter, "_limiter", None)

    async def _redis():
        return fake

    import app.core.hitl as hitl

    monkeypatch.setattr(hitl, "get_redis", _redis)
    return fake


@pytest.mark.asyncio
async def test_unset_qps_always_allows(bucket):
    for _ in range(20):
        d = await rate_limiter.agent_qps_decision("t", "a", None)
        assert d.allowed


@pytest.mark.asyncio
async def test_qps_blocks_past_the_burst(bucket, monkeypatch):
    monkeypatch.setattr(rate_limiter.time, "time", lambda: 1000.0)
    got = [
        (await rate_limiter.agent_qps_decision("t", "a", 2)).allowed for _ in range(3)
    ]
    assert got == [True, True, False]
    # another agent has its own bucket
    assert (await rate_limiter.agent_qps_decision("t", "b", 2)).allowed


def test_message_reads_plainly_and_classifies_as_platform_limit():
    msg = rate_limiter.qps_message("Triage", 2, 1)
    assert "2 runs per second" in msg
    assert classify_exception(msg) == "RATE_LIMITED"
