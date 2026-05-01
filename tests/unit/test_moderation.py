"""Tests for engine.moderation_gate + engine.moderation_client.

The moderation gate is the platform's content-policy enforcement
point. Per the failure-visibility memory, the gate is non-bypassable
when wired in but is a complete no-op when no policy is loaded — so
the tests cover both "no policy → ALLOW" and "policy active → BLOCK"
to make sure the contract holds. Provider calls are mocked so the
tests run offline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from engine.moderation_client import (
    ACTION_ALLOW,
    ACTION_BLOCK,
    ACTION_FLAG,
    ACTION_REDACT,
    ModerationDecision,
    _custom_pattern_hit,
    _pick_action,
    _redact,
    content_hash,
    evaluate,
)
from engine.moderation_gate import GateConfig, ModerationBlocked, check

# ── pure helpers ────────────────────────────────────────────────────


def test_content_hash_is_deterministic_and_64_chars():
    a = content_hash("hello world")
    b = content_hash("hello world")
    c = content_hash("hello world.")
    assert a == b
    assert a != c
    assert len(a) == 64  # SHA-256 hex digest length


def test_custom_pattern_hit_returns_matching_patterns():
    patterns = [r"\bsecret\b", r"\bpassword\b"]
    hits = _custom_pattern_hit("the secret is hidden", patterns)
    assert r"\bsecret\b" in hits
    assert r"\bpassword\b" not in hits


def test_custom_pattern_hit_is_case_insensitive():
    hits = _custom_pattern_hit("SECRET payload", [r"\bsecret\b"])
    assert hits == [r"\bsecret\b"]


def test_custom_pattern_hit_skips_invalid_regex_silently():
    """A bad pattern must not crash the gate — just skip and continue."""
    hits = _custom_pattern_hit("anything", [r"[unclosed", r"\bok\b"])
    assert hits == []


def test_redact_replaces_offending_spans_with_mask():
    out = _redact("call me at 555-1234", [r"\d{3}-\d{4}"], "[REDACTED]")
    assert "555-1234" not in out
    assert "[REDACTED]" in out


def test_pick_action_chooses_most_severe():
    """When two categories trigger different actions, the gate must pick
    the most severe (BLOCK > REDACT > FLAG > ALLOW)."""
    triggered = ["hate", "harassment"]
    actions = {"hate": ACTION_FLAG, "harassment": ACTION_BLOCK}
    chosen, _ = _pick_action(triggered, actions, default_action=ACTION_ALLOW)
    assert chosen == ACTION_BLOCK


def test_pick_action_falls_back_to_default():
    triggered = ["unknown_category"]
    chosen, _ = _pick_action(triggered, {}, default_action=ACTION_FLAG)
    assert chosen == ACTION_FLAG


# ── evaluate() with mocked provider ─────────────────────────────────


def _mock_provider(category_scores: dict, flagged: bool = False):
    """Return an async function that mimics _call_openai's response shape.

    The provider's `categories` map is True only when the corresponding
    score is above 0.5 — matching how OpenAI's moderation endpoint
    actually reports it. evaluate() ORs category-true with the
    score-vs-threshold check, so a clean score must come with
    `categories[cat] = False` to truly count as clean.
    """

    async def fake(_content, model="omni-moderation-latest"):
        return {
            "results": [
                {
                    "flagged": flagged,
                    "categories": {k: v >= 0.5 for k, v in category_scores.items()},
                    "category_scores": category_scores,
                }
            ]
        }

    return fake


@pytest.mark.asyncio
async def test_evaluate_allows_clean_content():
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.0, "hate": 0.0}),
    ):
        decision = await evaluate("Hello, how can I help you today?")
    assert decision.action == ACTION_ALLOW
    assert decision.outcome == "allowed"
    assert decision.triggered_categories == []


@pytest.mark.asyncio
async def test_evaluate_blocks_when_threshold_exceeded():
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.95, "hate": 0.05}, flagged=True),
    ):
        decision = await evaluate(
            "violent content here",
            default_threshold=0.5,
            default_action=ACTION_BLOCK,
        )
    assert decision.action == ACTION_BLOCK
    assert decision.outcome == "blocked"
    assert "violence" in decision.triggered_categories


@pytest.mark.asyncio
async def test_evaluate_per_category_action_overrides_default():
    """category_actions={'hate': 'flag'} must downgrade hate-only triggers
    to FLAG even when default_action is BLOCK."""
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"hate": 0.9}, flagged=True),
    ):
        decision = await evaluate(
            "hateful content",
            category_actions={"hate": ACTION_FLAG},
            default_action=ACTION_BLOCK,
        )
    assert decision.action == ACTION_FLAG
    assert decision.outcome == "flagged"


@pytest.mark.asyncio
async def test_evaluate_custom_pattern_triggers_block():
    """Custom regex patterns are authoritative — a hit always uses
    default_action regardless of the provider's verdict."""
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.01}, flagged=False),
    ):
        decision = await evaluate(
            "discussing internal codename aurora details",
            custom_patterns=[r"\bcodename\s+aurora\b"],
            default_action=ACTION_BLOCK,
        )
    assert decision.action == ACTION_BLOCK
    assert decision.outcome == "blocked"


@pytest.mark.asyncio
async def test_evaluate_redact_returns_masked_content():
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.05}, flagged=False),
    ):
        decision = await evaluate(
            "my SSN is 123-45-6789 ok",
            custom_patterns=[r"\d{3}-\d{2}-\d{4}"],
            default_action=ACTION_REDACT,
            redaction_mask="[REDACTED]",
        )
    assert decision.action == ACTION_REDACT
    assert decision.outcome == "redacted"
    assert decision.redacted_content is not None
    assert "123-45-6789" not in decision.redacted_content
    assert "[REDACTED]" in decision.redacted_content


@pytest.mark.asyncio
async def test_evaluate_empty_content_short_circuits():
    """Empty input never even calls the provider — defensive optimisation."""

    async def panic(_c, model="x"):
        raise AssertionError("provider should NOT be called for empty content")

    with patch("engine.moderation_client._call_openai", new=panic):
        decision = await evaluate("")
    assert decision.action == ACTION_ALLOW


@pytest.mark.asyncio
async def test_evaluate_provider_error_records_but_does_not_raise():
    """Provider exceptions must be caught and surfaced via decision.error
    so the gate can decide whether to fail-open or fail-closed."""

    async def panic(_c, model="x"):
        raise RuntimeError("network down")

    with patch("engine.moderation_client._call_openai", new=panic):
        decision = await evaluate("normal text", default_action=ACTION_BLOCK)
    assert decision.error is not None
    assert "network down" in decision.error
    # No triggered categories → action stays ALLOW with outcome=error
    assert decision.outcome == "error"


# ── gate (check function) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_no_policy_is_passthrough():
    """When config is None, the gate must pass content through unchanged
    with action=ALLOW. New tenants without a seeded policy hit this."""
    out, decision = await check("anything goes", source="pre_llm", config=None)
    assert out == "anything goes"
    assert decision.action == ACTION_ALLOW
    assert decision.outcome == "allowed"


@pytest.mark.asyncio
async def test_gate_pre_llm_disabled_skips_evaluation():
    """A policy with pre_llm=False must not call the provider for pre-LLM
    checks. Belt-and-suspenders for tenants who only want post-LLM gating."""

    async def panic(_c, model="x"):
        raise AssertionError("evaluate should be skipped")

    with patch("engine.moderation_client._call_openai", new=panic):
        cfg = GateConfig(pre_llm=False)
        out, dec = await check("violent content", source="pre_llm", config=cfg)
    assert out == "violent content"
    assert dec.action == ACTION_ALLOW


@pytest.mark.asyncio
async def test_gate_block_raises_moderation_blocked():
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.99}, flagged=True),
    ):
        cfg = GateConfig(pre_llm=True, default_action=ACTION_BLOCK)
        with pytest.raises(ModerationBlocked) as excinfo:
            await check("violent prompt", source="pre_llm", config=cfg)

    assert excinfo.value.source == "pre_llm"
    assert "violent prompt" in excinfo.value.content_preview


@pytest.mark.asyncio
async def test_gate_redact_returns_masked_content():
    """REDACT must rewrite the content rather than block — the LLM still
    sees a sanitised version."""
    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.01}, flagged=False),
    ):
        cfg = GateConfig(
            pre_llm=True,
            default_action=ACTION_REDACT,
            custom_patterns=[r"\bsecret\b"],
            redaction_mask="█",
        )
        out, dec = await check("the secret thing", source="pre_llm", config=cfg)
    assert dec.action == ACTION_REDACT
    assert "secret" not in out
    assert "█" in out


@pytest.mark.asyncio
async def test_gate_fail_closed_blocks_on_provider_error():
    """fail_closed=True turns a provider outage into a BLOCK so we don't
    silently let unmoderated content through."""

    async def panic(_c, model="x"):
        raise RuntimeError("provider timeout")

    with patch("engine.moderation_client._call_openai", new=panic):
        cfg = GateConfig(pre_llm=True, fail_closed=True)
        with pytest.raises(ModerationBlocked) as excinfo:
            await check("anything", source="pre_llm", config=cfg)
    assert excinfo.value.decision.reason == "provider_error_fail_closed"


@pytest.mark.asyncio
async def test_gate_fires_event_sink_with_decision_metadata():
    """Tenants persist moderation events via an event_sink callback —
    the sink must receive structured metadata so /moderation/events can
    show real activity."""
    captured = {}

    def sink(**kwargs):
        captured.update(kwargs)

    with patch(
        "engine.moderation_client._call_openai",
        new=_mock_provider({"violence": 0.0}, flagged=False),
    ):
        cfg = GateConfig(pre_llm=True, event_sink=sink)
        await check(
            "harmless",
            source="pre_llm",
            config=cfg,
            execution_id="exec-123",
        )

    assert captured["source"] == "pre_llm"
    assert captured["execution_id"] == "exec-123"
    assert isinstance(captured["decision"], ModerationDecision)
    assert "harmless" in captured["content_preview"]
