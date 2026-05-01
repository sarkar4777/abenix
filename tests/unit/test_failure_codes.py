"""Tests for app.core.failure_codes — the exception → stable failure_code mapper.

This classifier is load-bearing for the dashboards and `/alerts`. Every
failed execution row in the DB carries a `failure_code` string from this
function; if the rule order or regex changes drift silently, alert
groupings break and on-call gets the wrong page.
"""

from __future__ import annotations

import pytest

from app.core.failure_codes import classify_exception


@pytest.mark.parametrize(
    "exc, expected",
    [
        # Stale-sweeper messages must beat the timeout rule even though
        # the message contains "running for >N minutes" which superficially
        # looks like a timeout.
        (Exception("execution stuck in RUNNING for 30 minutes"), "STALE_SWEEP"),
        (Exception("sweep backfill ran"), "STALE_SWEEP"),
        (Exception("owning process likely crashed"), "STALE_SWEEP"),
        # LLM provider rate-limits — common operational failure
        (Exception("rate limit exceeded"), "LLM_RATE_LIMIT"),
        (Exception("HTTP 429 Too Many Requests"), "LLM_RATE_LIMIT"),
        # Provider-specific
        (Exception("Anthropic API error: connection reset"), "LLM_PROVIDER_ERROR"),
        (Exception("OpenAI exception during streaming"), "LLM_PROVIDER_ERROR"),
        (Exception("Gemini error: model unavailable"), "LLM_PROVIDER_ERROR"),
        # Bad LLM output
        (Exception("Expecting value: line 1 column 1"), "LLM_INVALID_RESPONSE"),
        (Exception("invalid response from provider"), "LLM_INVALID_RESPONSE"),
        # Sandbox failures
        (Exception("OOMKilled by kernel"), "SANDBOX_OOM"),
        (Exception("memory limit exceeded"), "SANDBOX_OOM"),
        (Exception("deadline exceeded after 60s"), "SANDBOX_TIMEOUT"),
        (Exception("Operation timed out"), "SANDBOX_TIMEOUT"),
        (Exception("process exited with exit code 5"), "SANDBOX_NONZERO_EXIT"),
        (Exception("non-zero exit from sandbox"), "SANDBOX_NONZERO_EXIT"),
        (Exception("Image not in allow-list"), "SANDBOX_IMAGE_BLOCKED"),
        # Tool layer
        (Exception("Unknown tool: ghost_tool"), "TOOL_NOT_FOUND"),
        (Exception("ToolError raised by code_executor"), "TOOL_ERROR"),
        # Budget / quota
        (Exception("daily budget exceeded for tenant"), "BUDGET_EXCEEDED"),
        (Exception("quota exhausted"), "BUDGET_EXCEEDED"),
        (Exception("insufficient credit"), "BUDGET_EXCEEDED"),
        # Moderation must beat the generic tool-error rule even though
        # ModerationBlocked is technically raised from the tool layer.
        (Exception("Moderation blocked: violence"), "MODERATION_BLOCKED"),
        (Exception("policy triggered on PII"), "MODERATION_BLOCKED"),
        # Infra
        (ConnectionResetError("Connection reset by peer"), "INFRA_CRASH"),
        (Exception("connection refused"), "INFRA_CRASH"),
        (Exception("server disconnected mid-request"), "INFRA_CRASH"),
        (Exception("HTTP 401 Unauthorized"), "INFRA_AUTH_ERROR"),
        (Exception("forbidden by upstream"), "INFRA_AUTH_ERROR"),
    ],
)
def test_classify_exception_matches_expected_code(exc, expected):
    assert classify_exception(exc) == expected


def test_classify_none_returns_unknown():
    assert classify_exception(None) == "UNKNOWN_ERROR"


def test_classify_unmatched_returns_unknown():
    assert (
        classify_exception(Exception("some entirely novel failure")) == "UNKNOWN_ERROR"
    )
    assert classify_exception(ValueError("bad arg")) == "UNKNOWN_ERROR"


def test_classify_accepts_plain_string():
    assert classify_exception("rate limit exceeded") == "LLM_RATE_LIMIT"
    assert classify_exception("Moderation blocked") == "MODERATION_BLOCKED"


def test_classify_uses_class_name_for_match():
    """ConnectionResetError matches because the class name appears in
    the synthesized text — this is how raw exception types without a
    descriptive message still get classified."""

    class ServerDisconnectError(Exception):
        pass

    assert classify_exception(ServerDisconnectError()) == "INFRA_CRASH"


def test_rule_order_stale_sweep_beats_timeout():
    """A stale-sweeper exception that mentions 'running for >5 min'
    contains the substring 'timed' (in 'minute(s)') only by coincidence
    in some phrasings; the explicit stuck-in-running rule must win."""
    msg = "execution stuck in RUNNING for 7 minutes — owning process likely crashed"
    assert classify_exception(Exception(msg)) == "STALE_SWEEP"


def test_rule_order_moderation_beats_tool_error():
    """ModerationBlocked exceptions ARE technically tool-layer events
    when the moderation gate fires from inside a tool, but they should
    still classify as MODERATION_BLOCKED for dashboard grouping."""
    assert (
        classify_exception(Exception("Moderation blocked from tool exception"))
        == "MODERATION_BLOCKED"
    )
