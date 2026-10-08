"""What a person reads when moderation stops their message."""

from types import SimpleNamespace

from engine.agent_executor import _moderation_block_text


def _blocked(cats, reason="", err=""):
    return SimpleNamespace(
        decision=SimpleNamespace(triggered_categories=cats, reason=reason, error=err)
    )


def test_custom_pattern_is_named_not_coded():
    text = _moderation_block_text(_blocked(["custom:0", "harassment"]), "Request")
    assert "custom:0" not in text
    assert "custom pattern 1, harassment" in text
    assert "Moderation page" in text


def test_provider_outage_is_not_called_a_policy_hit():
    text = _moderation_block_text(
        _blocked([], reason="provider_error_fail_closed", err="429"), "Request"
    )
    assert "could not be reached" in text
