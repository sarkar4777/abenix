from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from engine import claude_subscription as cs
from engine.llm_router import LLMRouter


def _cfg(
    enabled=True, token="sk-ant-oat01-test", model="claude-opus-5", exclusive=True
):
    return cs.SubscriptionConfig(
        enabled=enabled, token=token, default_model=model, exclusive=exclusive
    )


@pytest.fixture(autouse=True)
def _clear_caches():
    cs.invalidate()
    yield
    cs.invalidate()


# ── config ───────────────────────────────────────────────────────────────


def test_config_not_usable_without_token():
    assert not _cfg(token="").usable
    assert not _cfg(token="placeholder").usable


def test_config_not_usable_when_disabled():
    assert not _cfg(enabled=False).usable


def test_config_usable_when_enabled_with_token():
    assert _cfg().usable


@patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_TOKEN": "sk-ant-oat01-env"}, clear=False)
def test_env_token_opts_in_when_no_settings_row():
    # A headless install sets only the env var — no platform_settings row.
    with patch.object(cs, "_read_settings", return_value={}):
        cfg = cs.get_config(refresh=True)
    assert cfg.token == "sk-ant-oat01-env"
    assert cfg.enabled is True
    assert cfg.usable is True


@patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_TOKEN": "sk-ant-oat01-env"}, clear=False)
def test_stored_disable_overrides_env_token():
    with patch.object(
        cs, "_read_settings", return_value={"llm.subscription.enabled": "false"}
    ):
        cfg = cs.get_config(refresh=True)
    assert cfg.token == "sk-ant-oat01-env"
    assert cfg.enabled is False
    assert cfg.usable is False


def test_settings_row_wins_over_env():
    with patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_TOKEN": "env-tok"}, clear=False):
        with patch.object(
            cs,
            "_read_settings",
            return_value={
                "llm.subscription.enabled": "true",
                "llm.subscription.token": "settings-tok",
            },
        ):
            cfg = cs.get_config(refresh=True)
    assert cfg.token == "settings-tok"


# ── model remapping ──────────────────────────────────────────────────────


def test_claude_models_pass_through_when_not_exclusive():
    cfg = _cfg(model="claude-opus-5", exclusive=False)
    assert cs.map_model("claude-haiku-4-5", cfg) == "claude-haiku-4-5"
    assert cs.map_model("claude-sonnet-5", cfg) == "claude-sonnet-5"


def test_exclusive_pins_every_request_to_the_configured_model():
    # "Use it for every feature" means a seeded agent asking for Sonnet runs
    # on the configured model, so a plan with headroom only on Haiku works.
    cfg = _cfg(model="claude-haiku-4-5", exclusive=True)
    for requested in (
        "claude-sonnet-4-5-20250929",
        "claude-opus-5",
        "gpt-4o",
        "gemini-2.5-pro",
        "",
        "unknown-model",
    ):
        assert cs.map_model(requested, cfg) == "claude-haiku-4-5", requested


def test_known_non_claude_models_remap_to_a_comparable_tier():
    cfg = _cfg(exclusive=False)
    assert cs.map_model("gpt-4o", cfg) == "claude-opus-5"
    assert cs.map_model("gpt-4o-mini", cfg) == "claude-haiku-4-5"
    assert cs.map_model("gemini-2.0-flash", cfg) == "claude-haiku-4-5"


def test_unknown_model_falls_back_to_the_configured_default():
    cfg = _cfg(model="claude-sonnet-5", exclusive=False)
    assert cs.map_model("some-future-model", cfg) == "claude-sonnet-5"
    assert cs.map_model("", cfg) == "claude-sonnet-5"


# ── routing chain ────────────────────────────────────────────────────────


def _chain(model: str, cfg, env: dict[str, str]):
    router = LLMRouter()
    with patch.dict(os.environ, env, clear=True):
        with patch.object(cs, "get_config", return_value=cfg):
            with patch.object(
                router, "_native_provider_name", wraps=router._native_provider_name
            ):
                return router.candidate_chain(model)


def test_subscription_leads_the_chain_when_configured():
    # exclusive (the default) pins the request to the configured model.
    chain = _chain("claude-sonnet-5", _cfg(), {"ANTHROPIC_API_KEY": "sk-ant-real"})
    assert chain[0] == ("claude_subscription", "claude-opus-5")


def test_non_exclusive_keeps_the_requested_claude_model():
    chain = _chain(
        "claude-sonnet-5", _cfg(exclusive=False), {"ANTHROPIC_API_KEY": "sk-ant-real"}
    )
    assert chain[0] == ("claude_subscription", "claude-sonnet-5")


def test_exclusive_mode_absorbs_non_claude_requests():
    chain = _chain("gpt-4o", _cfg(exclusive=True), {"OPENAI_API_KEY": "sk-real"})
    assert chain[0] == ("claude_subscription", "claude-opus-5")


def test_non_exclusive_mode_leaves_non_claude_to_its_own_provider():
    chain = _chain("gpt-4o", _cfg(exclusive=False), {"OPENAI_API_KEY": "sk-real"})
    assert chain[0] == ("openai", "gpt-4o")
    assert all(p != "claude_subscription" for p, _ in chain)


def test_degrades_to_configured_api_keys_after_the_subscription():
    chain = _chain("claude-sonnet-5", _cfg(), {"ANTHROPIC_API_KEY": "sk-ant-real"})
    # The API-key fallback keeps the ORIGINALLY requested model — only the
    # subscription hop is pinned.
    assert ("anthropic", "claude-sonnet-5") in chain
    assert chain.index(("claude_subscription", "claude-opus-5")) < chain.index(
        ("anthropic", "claude-sonnet-5")
    )


def test_no_subscription_keeps_the_native_provider_first():
    chain = _chain("gpt-4o", _cfg(enabled=False), {"OPENAI_API_KEY": "sk-real"})
    assert chain[0] == ("openai", "gpt-4o")


def test_falls_through_to_whatever_single_provider_is_configured():
    # Subscription off, no OpenAI key, only Google configured: the request
    # for gpt-4o should still find a usable provider.
    chain = _chain("gpt-4o", _cfg(enabled=False), {"GOOGLE_API_KEY": "g-real"})
    assert ("google", "gemini-2.0-flash") in chain
    assert all(p != "openai" for p, _ in chain)


def test_placeholder_keys_are_not_treated_as_configured():
    chain = _chain("gpt-4o", _cfg(enabled=False), {"OPENAI_API_KEY": "placeholder"})
    assert all(p != "openai" or m != "gpt-4o" for p, m in chain[1:])
    # Nothing is configured at all, so the chain still names the native
    # provider so the eventual error points at the missing key.
    assert chain == [("openai", "gpt-4o")]


def test_subscription_only_install_yields_a_single_candidate():
    chain = _chain("claude-opus-5", _cfg(), {})
    assert chain == [("claude_subscription", "claude-opus-5")]


def test_chain_never_repeats_a_candidate():
    chain = _chain(
        "claude-sonnet-5",
        _cfg(),
        {
            "ANTHROPIC_API_KEY": "a",
            "OPENAI_API_KEY": "o",
            "GOOGLE_API_KEY": "g",
            "AZURE_OPENAI_API_KEY": "z",
        },
    )
    assert len(chain) == len(set(chain))


# ── effort-parameter support ──────────────────────────────────────────────


def test_effort_allowlist_excludes_models_that_reject_it():
    from engine.llm_router import _supports_effort

    # These 400 with "This model does not support the effort parameter."
    for m in (
        "claude-haiku-4-5",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-3-5-20241022",
    ):
        assert not _supports_effort(m), m


def test_effort_allowlist_includes_current_models():
    from engine.llm_router import _supports_effort

    for m in (
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-fable-5-1",
    ):
        assert _supports_effort(m), m


def test_effort_maps_from_temperature():
    from engine.llm_router import _effort_for_temperature

    assert _effort_for_temperature(0.0) == "low"
    assert _effort_for_temperature(0.2) == "low"
    assert _effort_for_temperature(0.5) == "medium"
    assert _effort_for_temperature(1.0) == "high"


def test_state_is_the_single_source_for_defaults():
    from engine.claude_subscription import (
        DEFAULT_SUBSCRIPTION_MODEL,
        subscription_state,
    )

    # env token with no stored rows counts as on, everywhere
    s = subscription_state({}, "sk-ant-oat-real")
    assert s == {
        "enabled": True,
        "default_model": DEFAULT_SUBSCRIPTION_MODEL,
        "exclusive": True,
    }
    assert subscription_state({}, "")["enabled"] is False
    off = subscription_state(
        {
            "llm.subscription.enabled": "false",
            "llm.subscription.exclusive": "false",
            "llm.subscription.default_model": "claude-sonnet-5",
        },
        "sk-ant-oat-real",
    )
    assert off == {
        "enabled": False,
        "default_model": "claude-sonnet-5",
        "exclusive": False,
    }


def test_api_default_matches_runtime():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
    from app.core.platform_settings import DEFAULTS
    from engine.claude_subscription import DEFAULT_SUBSCRIPTION_MODEL

    assert (
        DEFAULTS["llm.subscription.default_model"]["value"]
        == DEFAULT_SUBSCRIPTION_MODEL
    )
