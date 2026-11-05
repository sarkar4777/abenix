"""A model with no key reaches the subscription, and a subscription 429 retries on the plan default."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from engine import claude_subscription as cs
from engine.knowledge.extractors import vision_pdf
from engine.llm_router import LLMResponse, LLMRouter, StreamEvent
from engine.tools import kyc_met_pdf_extractor as kyc


def _cfg(exclusive=False, usable=True):
    return cs.SubscriptionConfig(
        enabled=usable,
        token="sk-ant-oat01-test" if usable else "",
        default_model="claude-haiku-4-5",
        exclusive=exclusive,
    )


class RateLimited(Exception):
    status_code = 429


class Unauthorized(Exception):
    status_code = 401


class FakeProvider:
    """Fails for the models in fail_on, answers otherwise, in either call shape."""

    def __init__(self, fail_on=None, fails_with=RateLimited):
        self.fail_on = fail_on or set()
        self.fails_with = fails_with
        self.calls: list[str] = []

    async def complete(self, *, model, stream=False, **_kw):
        self.calls.append(model)
        if stream:
            return self._stream(model)
        if model in self.fail_on:
            raise self.fails_with(f"429 rate_limit_error on {model}")
        return LLMResponse(
            content="hi",
            model=model,
            input_tokens=1,
            output_tokens=1,
            cost=0.0,
            latency_ms=1,
        )

    async def _stream(self, model):
        if model in self.fail_on:
            raise self.fails_with(f"429 rate_limit_error on {model}")
        yield StreamEvent(event="token", data="hi")
        yield StreamEvent(event="done", data={"model": model, "tool_calls": []})


def _route(router, model, cfg, env, providers, stream, resolve=None):
    async def go():
        decision = resolve or (
            lambda m, required_capabilities=None: SimpleNamespace(
                requested=m, effective=m, reason="primary", chain=[m]
            )
        )
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(cs, "get_config", return_value=cfg),
            patch("engine.model_resolver.resolve", side_effect=decision),
            patch.object(router, "_get_provider", side_effect=providers.__getitem__),
            patch("engine.llm_router.asyncio.sleep", AsyncMock()),
        ):
            result = await router.complete(
                messages=[{"role": "user", "content": "hi"}],
                model=model,
                stream=stream,
            )
            if not stream:
                return result
            return [e async for e in result]

    return go()


def _chain(model, cfg, env):
    router = LLMRouter()
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(cs, "get_config", return_value=cfg),
    ):
        return router.candidate_chain(model)


@pytest.mark.parametrize("exclusive", [True, False])
def test_gemini_without_a_google_key_reaches_the_subscription(exclusive):
    chain = _chain("gemini-2.0-flash", _cfg(exclusive=exclusive), {})
    assert chain == [("claude_subscription", "claude-haiku-4-5")]


def test_gemini_goes_to_the_plan_before_another_providers_key():
    chain = _chain(
        "gemini-2.0-flash", _cfg(), {"OPENAI_API_KEY": "sk-dead-key-no-credits"}
    )
    assert chain[0] == ("claude_subscription", "claude-haiku-4-5")
    assert ("openai", "gpt-4o") in chain


def test_gemini_with_its_own_key_keeps_its_provider():
    chain = _chain("gemini-2.0-flash", _cfg(), {"GOOGLE_API_KEY": "g-real"})
    assert chain[0] == ("google", "gemini-2.0-flash")
    assert all(p != "claude_subscription" for p, _ in chain)


@pytest.mark.parametrize("stream", [False, True])
async def test_prober_marking_gemini_down_does_not_pull_it_off_the_plan(stream):
    # the live failure, model availability swaps a keyless gemini to its declared Sonnet
    def swap(m, required_capabilities=None):
        return SimpleNamespace(
            requested=m,
            effective="claude-sonnet-4-5-20250929",
            reason="declared_fallback",
            chain=[m, "claude-sonnet-4-5-20250929"],
        )

    plan = FakeProvider(fail_on={"claude-sonnet-4-5-20250929"})
    out = await _route(
        LLMRouter(),
        "gemini-2.0-flash",
        _cfg(),
        {},
        {"claude_subscription": plan},
        stream,
        resolve=swap,
    )
    assert plan.calls == ["claude-haiku-4-5"]
    assert out if stream else out.model == "claude-haiku-4-5"


@pytest.mark.parametrize("stream", [False, True])
async def test_a_plan_rate_limit_retries_on_the_plan_default(stream):
    plan = FakeProvider(fail_on={"claude-sonnet-5"})
    out = await _route(
        LLMRouter(),
        "claude-sonnet-5",
        _cfg(),
        {},
        {"claude_subscription": plan},
        stream,
    )
    assert plan.calls == ["claude-sonnet-5", "claude-haiku-4-5"]
    if stream:
        done = next(e for e in out if e.event == "done")
        assert done.data["model"] == "claude-haiku-4-5"
        assert done.data["requested_model"] == "claude-sonnet-5"
        assert done.data["fallback_reason"] == "claude_subscription"
    else:
        assert out.model == "claude-haiku-4-5"


async def test_a_rate_limited_plan_default_does_not_loop():
    plan = FakeProvider(fail_on={"claude-haiku-4-5"})
    with pytest.raises(RateLimited) as err:
        await _route(
            LLMRouter(),
            "claude-haiku-4-5",
            _cfg(),
            {},
            {"claude_subscription": plan},
            True,
        )
    assert plan.calls == ["claude-haiku-4-5"] * 3
    assert err.value.llm_model == "claude-haiku-4-5"


async def test_only_a_rate_limit_moves_to_the_plan_default():
    plan = FakeProvider(fail_on={"claude-sonnet-5"}, fails_with=Unauthorized)
    with pytest.raises(Unauthorized) as err:
        await _route(
            LLMRouter(),
            "claude-sonnet-5",
            _cfg(),
            {},
            {"claude_subscription": plan},
            False,
        )
    assert set(plan.calls) == {"claude-sonnet-5"}
    assert err.value.llm_provider == "claude_subscription"
    assert err.value.llm_model == "claude-sonnet-5"


async def test_a_stream_that_fails_before_any_token_falls_through_the_chain():
    plan = FakeProvider(fail_on={"claude-haiku-4-5"})
    api_key = FakeProvider()
    out = await _route(
        LLMRouter(),
        "claude-sonnet-5",
        _cfg(exclusive=True),
        {"ANTHROPIC_API_KEY": "sk-real"},
        {"claude_subscription": plan, "anthropic": api_key},
        True,
    )
    assert api_key.calls == ["claude-sonnet-5"]
    assert next(e for e in out if e.event == "done").data["model"] == "claude-sonnet-5"


class FakeMessages:
    def __init__(self):
        self.kwargs = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="page text")])


def _fake_client(messages):
    return lambda api_key=None: (SimpleNamespace(messages=messages), True)


@pytest.mark.parametrize(
    "module,call",
    [
        (vision_pdf, vision_pdf._claude_vision),
        (kyc, kyc._vision_extract),
    ],
)
async def test_vision_works_on_a_subscription_with_no_keys(module, call):
    messages = FakeMessages()
    image = base64.b64encode(b"png").decode()
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(cs, "get_config", return_value=_cfg()),
        patch.object(cs, "build_async_client", _fake_client(messages)),
    ):
        assert module._provider() == "claude_subscription"
        assert await call(image, 1) == "page text"
    assert messages.kwargs["model"].startswith("claude")
    assert messages.kwargs["messages"][0]["content"][0]["source"]["data"] == image


@pytest.mark.parametrize("module", [vision_pdf, kyc])
@pytest.mark.parametrize(
    "env,usable,expected",
    [
        (
            {"ANTHROPIC_API_KEY": "a", "GOOGLE_API_KEY": "g"},
            True,
            "anthropic",
        ),
        ({"GOOGLE_API_KEY": "g"}, True, "claude_subscription"),
        ({"GOOGLE_API_KEY": "g"}, False, "gemini"),
    ],
)
def test_vision_order_is_key_then_plan_then_google(module, env, usable, expected):
    with (
        patch.dict(os.environ, env, clear=True),
        patch.object(cs, "get_config", return_value=_cfg(usable=usable)),
    ):
        assert module._provider() == expected


async def test_an_anthropic_key_is_used_before_the_plan():
    messages = FakeMessages()
    client = SimpleNamespace(messages=messages)
    with (
        patch.object(cs, "get_config", return_value=_cfg(exclusive=True)),
        patch("anthropic.AsyncAnthropic", return_value=client) as made,
    ):
        out = await cs.vision_text("aW1n", "read", "claude-haiku-4-5-20251001", "sk-a")
    assert out == "page text"
    assert made.call_args.kwargs["api_key"] == "sk-a"
    assert messages.kwargs["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.parametrize("module", [vision_pdf, kyc])
def test_vision_still_says_none_with_nothing_configured(module):
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(cs, "get_config", return_value=_cfg(usable=False)),
    ):
        assert module._provider() == "none"


def test_every_failure_writer_records_the_model_the_router_tried():
    root = Path(__file__).resolve().parents[3]
    consumer = (root / "apps/agent-runtime/consumer.py").read_text()
    agents = (root / "apps/api/app/routers/agents.py").read_text()
    assert 'model_used=getattr(e, "llm_model", None)' in consumer
    assert agents.count('getattr(e, "llm_model", None) or execution.model_used') == 2
