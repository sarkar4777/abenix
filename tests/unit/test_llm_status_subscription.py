"""Readiness, /resolve and the pickers agree with what the runtime does on a subscription."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import main as app_main
from app.routers import llm_models as lm

SUB = {"active": True, "exclusive": True, "default_model": "claude-haiku-4-5"}
NON_EXCLUSIVE = {**SUB, "exclusive": False}
NO_KEYS = {
    p: {"configured": False}
    for p in ("anthropic", "openai", "google", "azure", "claude_subscription")
}
GOOGLE_KEY = {**NO_KEYS, "google": {"configured": True}}


@pytest.mark.parametrize(
    "model,sub,providers,expected",
    [
        ("claude-sonnet-5", SUB, NO_KEYS, "claude-haiku-4-5"),
        ("gemini-2.0-flash", SUB, GOOGLE_KEY, "claude-haiku-4-5"),
        ("gemini-2.0-flash", NON_EXCLUSIVE, NO_KEYS, "claude-haiku-4-5"),
        ("gemini-2.5-pro", NON_EXCLUSIVE, NO_KEYS, "claude-opus-5"),
        ("gemini-2.0-flash", NON_EXCLUSIVE, GOOGLE_KEY, None),
        ("claude-sonnet-5", NON_EXCLUSIVE, NO_KEYS, "claude-sonnet-5"),
        ("claude-sonnet-5", {"active": False}, NO_KEYS, None),
    ],
)
def test_subscription_target_matches_the_router(model, sub, providers, expected):
    assert lm._subscription_target(model, None, sub, providers) == expected


async def _resolve(model, sub, providers):
    decision = SimpleNamespace(
        requested=model,
        effective="claude-sonnet-4-5-20250929",
        chain=[model, "claude-sonnet-4-5-20250929"],
        reason="declared_fallback",
    )
    no_row = MagicMock()
    no_row.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=no_row)
    with (
        patch("engine.model_resolver.resolve", return_value=decision),
        patch.object(lm, "_subscription_state", AsyncMock(return_value=sub)),
        patch.object(lm, "_probe_providers", AsyncMock(return_value=providers)),
    ):
        resp = await lm.resolve_model(model=model, user=MagicMock(), db=db)
    return json.loads(resp.body)["data"]


@pytest.mark.asyncio
async def test_resolve_reports_the_exclusive_model():
    data = await _resolve("claude-sonnet-4-5-20250929", SUB, NO_KEYS)
    assert data["effective"] == "claude-haiku-4-5"
    assert data["served_by"] == "claude_subscription"
    assert data["swap"] is True


@pytest.mark.asyncio
async def test_resolve_reports_a_keyless_gemini_on_the_plan_outside_exclusive():
    data = await _resolve("gemini-2.0-flash", NON_EXCLUSIVE, NO_KEYS)
    assert data["effective"] == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_resolve_keeps_the_resolver_answer_without_a_subscription():
    data = await _resolve("gemini-2.0-flash", {"active": False}, GOOGLE_KEY)
    assert data["effective"] == "claude-sonnet-4-5-20250929"
    assert data["served_by"] is None


class _Session:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


def _no_env_keys(monkeypatch):
    for attr in ("anthropic_api_key", "openai_api_key", "google_api_key"):
        monkeypatch.setattr(app_main.app_settings, attr, "", raising=False)


@pytest.mark.asyncio
async def test_ready_counts_an_active_subscription(monkeypatch):
    _no_env_keys(monkeypatch)
    providers = {**NO_KEYS, "claude_subscription": {"configured": True}}
    with (
        patch("app.core.deps.priority_session", lambda: _Session()),
        patch.object(lm, "_probe_providers", AsyncMock(return_value=providers)),
    ):
        assert await app_main._any_llm_provider() is True


@pytest.mark.asyncio
async def test_ready_still_reports_nothing_configured(monkeypatch):
    _no_env_keys(monkeypatch)
    with (
        patch("app.core.deps.priority_session", lambda: _Session()),
        patch.object(lm, "_probe_providers", AsyncMock(return_value=NO_KEYS)),
    ):
        assert await app_main._any_llm_provider() is False


def test_picker_offers_a_keyless_gemini_on_the_plan_outside_exclusive():
    row = SimpleNamespace(
        model="gemini-2.0-flash",
        provider="google",
        display_name="Gemini",
        is_deprecated=False,
        deprecated_at=None,
        migration_hint=None,
        input_per_m=0.1,
        output_per_m=0.4,
        capabilities={},
        fallback_to=[],
    )
    shown = lm._display(row, None, NO_KEYS, NON_EXCLUSIVE)
    assert shown["subscription_served"] is True
    assert shown["subscription_remapped_to"] == "claude-haiku-4-5"
    assert lm._display(row, None, GOOGLE_KEY, NON_EXCLUSIVE)["served_by"] == "google"
