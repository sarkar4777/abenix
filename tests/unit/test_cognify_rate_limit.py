"""The shared bucket waits instead of failing and backoff respects the provider."""

from __future__ import annotations

import asyncio

import pytest

from engine.knowledge import embed_gate
from engine.knowledge.rate_limit import (
    CallLimiter,
    backoff_delay,
    is_retryable,
    with_backoff,
)


class _Clock:
    def __init__(self):
        self.slept = []

    async def sleep(self, seconds):
        self.slept.append(seconds)


class _Redis:
    """The shape of the Lua bucket, so two processes can share it in a test."""

    def __init__(self):
        self.spent = {}
        self.keys = {}
        self.calls = []

    def eval(self, script, n, key, rate, cap, need, strict):
        self.calls.append(key)
        have = cap - self.spent.get(key, 0)
        wait = max(0.0, (need - have) / rate)
        self.spent[key] = self.spent.get(key, 0) + need
        return str(wait).encode()

    def pttl(self, key):
        return self.keys.get(key, -2)

    def set(self, key, value, px):
        self.keys[key] = px


def _limiter(redis, rpm=600, tpm=1000, sleep=None, provider="anthropic"):
    gate = embed_gate.RateGate(f"cognify:{provider}", rpm, tpm, client=redis)
    return CallLimiter(provider, rpm, tpm, gate=gate, sleep=sleep or _no_sleep)


async def _no_sleep(_seconds):
    return None


def test_two_workers_draw_from_one_bucket():
    redis, slept = _Redis(), []

    async def nap(seconds):
        slept.append(seconds)

    first, second = _limiter(redis, sleep=nap), _limiter(redis, sleep=nap)

    async def go():
        await first.acquire(1000)
        return await second.acquire(500)

    waited = asyncio.run(go())
    assert waited == pytest.approx(30.0, abs=0.5)
    assert slept == [waited]
    assert set(redis.calls) == {
        "kb:gate:cognify:anthropic:requests",
        "kb:gate:cognify:anthropic:tokens",
    }


def test_a_provider_wait_holds_the_other_workers():
    redis = _Redis()
    first, second = _limiter(redis), _limiter(redis)
    asyncio.run(first.after_failure(_Err(429, retry_after=20)))
    assert second.gate.pause_remaining() == pytest.approx(20.0, abs=0.5)
    assert asyncio.run(second.acquire(1)) == pytest.approx(20.0, abs=0.5)


def test_a_refusal_with_no_wait_holds_nobody():
    redis = _Redis()
    limiter = _limiter(redis)
    asyncio.run(limiter.after_failure(_Err(400, retry_after=20)))
    assert limiter.gate.pause_remaining() == 0


def test_jobs_on_one_provider_share_a_gate_in_redis(monkeypatch):
    from engine.knowledge import cognify_pipeline as cp

    monkeypatch.setattr(cp, "_provider_of", lambda model: "anthropic")
    a = cp.build_context("k", "t", "j1", {}, "", tenant_cfg=_TENANT_CFG)
    b = cp.build_context("k", "t", "j2", {}, "", tenant_cfg=_TENANT_CFG)
    assert a.limiter.gate is b.limiter.gate
    assert a.limiter.gate.name == "cognify:anthropic"


def test_the_gate_name_follows_the_provider_the_model_reaches(monkeypatch):
    from engine.knowledge import cognify_pipeline as cp
    from engine.llm_router import LLMRouter

    monkeypatch.setattr(
        LLMRouter,
        "candidate_chain",
        lambda self, model: [("claude_subscription", model)],
    )
    assert cp._provider_of("claude-haiku-4-5") == "claude_subscription"


_TENANT_CFG = {"auto_accept_threshold": 0.85, "conflict_action": "flag"}


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


def test_a_cut_off_reply_keeps_every_whole_item():
    from engine.knowledge.entity_extractor import parse_extraction

    text = (
        '{"entities": [{"name": "A", "type": "org"}, {"name": "B", "type": "org"},'
        ' {"name": "C", "ty'
    )
    data, cut_off = parse_extraction(text)
    assert cut_off
    assert [e["name"] for e in data["entities"]] == ["A", "B"]
    assert data["relationships"] == []


def test_a_finished_reply_is_not_marked_cut_off():
    from engine.knowledge.entity_extractor import parse_extraction

    data, cut_off = parse_extraction('x {"entities": [], "relationships": []} y')
    assert not cut_off
    assert data == {"entities": [], "relationships": []}
