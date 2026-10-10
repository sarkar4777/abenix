"""New agents start on a sensible available model, never the priciest one."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.default_model import FALLBACK_MODEL, pick_default_model


def _m(value, provider, out=15.0, available=True, sub=False, **kw):
    return {
        "value": value,
        "provider": provider,
        "output_per_m": out,
        "provider_available": available,
        "subscription_served": sub,
        "is_deprecated": False,
        "status": "available",
        **kw,
    }


NO_KEYS = {
    "anthropic": {"configured": False},
    "openai": {"configured": False},
    "google": {"configured": False},
    "azure": {"configured": False},
    "claude_subscription": {"configured": True},
}


def _catalogue(sub=False, anthropic=True, openai=True):
    return [
        _m("claude-opus-5", "anthropic", 25, anthropic or sub, sub),
        _m("claude-opus-4-6", "anthropic", 75, anthropic or sub, sub),
        _m("claude-sonnet-4-5-20250929", "anthropic", 15, anthropic or sub, sub),
        _m("claude-haiku-4-5", "anthropic", 5, anthropic or sub, sub),
        _m("gpt-4o", "openai", 10, openai, False),
        _m("gpt-5", "openai", 40, openai, False),
    ]


def test_subscription_only_uses_the_subscription_default():
    sub = {"active": True, "exclusive": False, "default_model": "claude-haiku-4-5"}
    got = pick_default_model(
        _catalogue(sub=True, anthropic=False, openai=False), NO_KEYS, sub
    )
    assert got == "claude-haiku-4-5"


def test_exclusive_subscription_shows_the_model_that_actually_runs():
    providers = {**NO_KEYS, "anthropic": {"configured": True}}
    sub = {"active": True, "exclusive": True, "default_model": "claude-haiku-4-5"}
    assert (
        pick_default_model(_catalogue(sub=True), providers, sub) == "claude-haiku-4-5"
    )


def test_api_keys_pick_a_balanced_sonnet_not_opus():
    providers = {
        **NO_KEYS,
        "anthropic": {"configured": True},
        "openai": {"configured": True},
    }
    got = pick_default_model(_catalogue(), providers, {"active": False})
    assert got == "claude-sonnet-4-5-20250929"


def test_newer_sonnet_wins_when_it_is_in_the_catalogue():
    providers = {**NO_KEYS, "anthropic": {"configured": True}}
    rows = _catalogue() + [_m("claude-sonnet-5", "anthropic", 10)]
    assert pick_default_model(rows, providers, None) == "claude-sonnet-5"


def test_openai_only_picks_a_balanced_gpt():
    providers = {**NO_KEYS, "openai": {"configured": True}}
    got = pick_default_model(_catalogue(anthropic=False), providers, None)
    assert got == "gpt-4o"


def test_unconfigured_provider_models_are_skipped():
    providers = {**NO_KEYS, "openai": {"configured": True}}
    rows = _catalogue(anthropic=False, openai=True)
    assert not pick_default_model(rows, providers, None).startswith("claude")


def test_deprecated_and_unavailable_models_are_skipped():
    providers = {**NO_KEYS, "anthropic": {"configured": True}}
    rows = [
        _m("claude-sonnet-4-5-20250929", "anthropic", 15, is_deprecated=True),
        _m("claude-sonnet-4-6", "anthropic", 15, status="unavailable"),
        _m("claude-opus-5", "anthropic", 25),
        _m("claude-haiku-4-5", "anthropic", 5),
        _m("claude-other", "anthropic", 10),
    ]
    got = pick_default_model(rows, providers, None)
    assert got not in (
        "claude-sonnet-4-5-20250929",
        "claude-sonnet-4-6",
        "claude-opus-5",
    )


def test_unknown_catalogue_never_picks_the_priciest():
    providers = {"acme": {"configured": True}}
    rows = [
        _m("acme-big", "acme", 90),
        _m("acme-mid", "acme", 10),
        _m("acme-small", "acme", 1),
    ]
    assert pick_default_model(rows, providers, None) == "acme-mid"


def test_empty_catalogue_falls_back():
    assert pick_default_model([], {}, None) == FALLBACK_MODEL


def test_default_agent_model_survives_a_broken_catalogue(monkeypatch):
    import app.routers.llm_models as lm

    async def boom(db, *a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(lm, "_catalogue", boom)
    assert asyncio.run(lm.default_agent_model(MagicMock())) == FALLBACK_MODEL


def _create(body_kwargs, monkeypatch, default="claude-haiku-4-5"):
    import app.routers.agents as ag
    import app.routers.llm_models as lm
    from app.schemas.agents import CreateAgentRequest

    async def fake_default(db):
        return default

    monkeypatch.setattr(lm, "default_agent_model", fake_default)
    monkeypatch.setattr(ag, "log_action", AsyncMock())
    monkeypatch.setattr(ag, "_sync_kb_grants", AsyncMock(return_value=[]))
    monkeypatch.setattr(ag, "_apply_scaling", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_serialize_agent", lambda a: dict(a.model_config_))

    db = MagicMock()
    no_row = MagicMock()
    no_row.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=no_row)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    user = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=SimpleNamespace(value="user")
    )
    body = CreateAgentRequest(name="T", **body_kwargs)
    resp = asyncio.run(ag.create_agent(body, MagicMock(), user=user, db=db))
    import json

    return json.loads(resp.body)["data"]


@pytest.mark.parametrize(
    "body",
    [{}, {"model_config": {"temperature": 0.2}}, {"tools": ["calculator"]}],
)
def test_create_without_a_model_uses_the_shared_default(body, monkeypatch):
    assert _create(body, monkeypatch)["model"] == "claude-haiku-4-5"


@pytest.mark.parametrize(
    "body",
    [{"model": "gpt-4o"}, {"model_config": {"model": "gpt-4o"}}],
)
def test_create_keeps_an_explicit_model(body, monkeypatch):
    assert _create(body, monkeypatch)["model"] == "gpt-4o"
