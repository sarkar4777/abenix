"""A chain where every provider fails reports the first real failure, not the last fallback's."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from engine import claude_subscription as cs
from engine.llm_router import LLMRouter


class _Failing:
    def __init__(self, exc: Exception):
        self.exc = exc

    async def complete(self, **_kw):
        raise self.exc


class _Cfg:
    enabled = False
    usable = False


def _run(chain, providers):
    router = LLMRouter()

    async def go():
        with (
            patch.object(router, "candidate_chain", return_value=chain),
            patch.object(
                router, "_get_provider", side_effect=lambda name: providers[name]
            ),
            patch.object(cs, "get_config", return_value=_Cfg()),
            patch("engine.llm_router.asyncio.sleep", return_value=None),
        ):
            await router.complete(
                messages=[{"role": "user", "content": "hi"}], model="m"
            )

    asyncio.run(go())


def test_revoked_primary_is_reported_over_a_broken_fallback():
    revoked = RuntimeError("401 OAuth access token has been revoked")
    bad_key = RuntimeError("400 API key not valid")
    with pytest.raises(RuntimeError, match="revoked"):
        _run(
            [("claude_subscription", "claude-haiku"), ("google", "gemini")],
            {"claude_subscription": _Failing(revoked), "google": _Failing(bad_key)},
        )


def test_an_unconfigured_primary_does_not_hide_the_real_error():
    google = _Failing(RuntimeError("400 API key not valid"))

    def get(name):
        if name == "anthropic":
            raise RuntimeError("no ANTHROPIC_API_KEY")
        return google

    router = LLMRouter()

    async def go():
        with (
            patch.object(
                router,
                "candidate_chain",
                return_value=[("anthropic", "a"), ("google", "g")],
            ),
            patch.object(router, "_get_provider", side_effect=get),
            patch.object(cs, "get_config", return_value=_Cfg()),
            patch("engine.llm_router.asyncio.sleep", return_value=None),
        ):
            await router.complete(
                messages=[{"role": "user", "content": "hi"}], model="a"
            )

    with pytest.raises(RuntimeError, match="API key not valid"):
        asyncio.run(go())
