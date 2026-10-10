"""Tenant DLP mode on agent input, agent output and pipeline output."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from engine.dlp import (
    apply,
    apply_to_pipeline_result,
    apply_to_value,
    policy_from_settings,
)
from engine.moderation_gate import (
    DLPBlocked,
    GateConfig,
    check,
    guards_output,
    with_dlp,
)

EMAIL = "write to jane.doe@example.com today"


def test_settings_map_to_a_policy():
    assert policy_from_settings(None) is None
    assert policy_from_settings({"mode": "mask", "enabled": False}) is None
    assert policy_from_settings({"mode": "mask"}).mode == "mask"
    assert policy_from_settings({"mode": "weird", "enabled": True}).mode == "detect"


def test_detect_passes_mask_masks_block_refuses():
    text, blocked, scan = apply(
        EMAIL, policy_from_settings({"mode": "detect"}), source="pre_llm"
    )
    assert text == EMAIL and not blocked and scan.has_pii
    text, blocked, _ = apply(
        EMAIL, policy_from_settings({"mode": "mask"}), source="pre_llm"
    )
    assert "jane.doe" not in text and "[EMAIL_MASKED]" in text and not blocked
    _, blocked, _ = apply(
        EMAIL, policy_from_settings({"mode": "block"}), source="pre_llm"
    )
    assert (
        blocked.startswith("This message was not sent") and "email address" in blocked
    )
    _, blocked, _ = apply(
        EMAIL, policy_from_settings({"mode": "block"}), source="post_llm"
    )
    assert blocked.startswith("The reply was withheld")


def test_values_inside_structures_are_masked():
    pol = policy_from_settings({"mode": "mask"})
    out, blocked = apply_to_value({"a": [EMAIL, 3], "b": "clean"}, pol)
    assert "jane.doe" not in out["a"][0] and out["a"][1] == 3 and out["b"] == "clean"
    assert not blocked
    _, blocked = apply_to_value({"a": [EMAIL]}, policy_from_settings({"mode": "block"}))
    assert blocked


def test_gate_carries_dlp_without_a_moderation_policy():
    assert with_dlp(None, policy_from_settings({"mode": "detect"}), "t") is None
    gate = with_dlp(None, policy_from_settings({"mode": "mask"}), "t")
    assert gate is not None and gate.moderation is False and gate.dlp_mode == "mask"
    # the reply is buffered so a streamed answer is masked before anyone sees it
    assert guards_output(gate)


@pytest.mark.asyncio
async def test_dlp_only_gate_masks_output_without_calling_the_provider(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr("engine.moderation_client._call_openai", boom)
    gate = with_dlp(None, policy_from_settings({"mode": "mask"}), "t")
    out, decision = await check(EMAIL, source="post_llm", config=gate)
    assert "[EMAIL_MASKED]" in out and decision.action == "allow"


@pytest.mark.asyncio
async def test_dlp_block_raises_with_a_plain_message(monkeypatch):
    gate = with_dlp(None, policy_from_settings({"mode": "block"}), "t")
    with pytest.raises(DLPBlocked) as exc:
        await check(EMAIL, source="post_llm", config=gate)
    assert "withheld" in exc.value.message


@pytest.mark.asyncio
async def test_dlp_runs_after_an_active_moderation_policy(monkeypatch):
    async def clean(content, model="x"):
        return {
            "results": [{"flagged": False, "categories": {}, "category_scores": {}}]
        }

    monkeypatch.setattr("engine.moderation_client._call_openai", clean)
    gate = with_dlp(
        GateConfig(policy_id="p"), policy_from_settings({"mode": "mask"}), "t"
    )
    assert gate.moderation is True
    out, _ = await check(EMAIL, source="pre_llm", config=gate)
    assert "jane.doe" not in out


@pytest.mark.asyncio
async def test_executor_masks_the_reply_and_refuses_on_block():
    from engine.agent_executor import _moderation_block_text

    gate = with_dlp(None, policy_from_settings({"mode": "block"}), "t")
    try:
        await check(EMAIL, source="pre_llm", config=gate)
    except DLPBlocked as mb:
        assert _moderation_block_text(mb, "Request") == mb.message


class _DB:
    def __init__(self, dlp):
        self.dlp = dlp

    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalar=lambda: self.dlp)


@pytest.mark.asyncio
async def test_pipeline_final_output_follows_the_tenant_mode():
    res = SimpleNamespace(final_output={"response": EMAIL})
    await apply_to_pipeline_result(_DB({"mode": "mask", "enabled": True}), "t", res)
    assert "jane.doe" not in res.final_output["response"]

    res = SimpleNamespace(final_output=EMAIL)
    await apply_to_pipeline_result(_DB('{"mode": "block"}'), "t", res)
    assert res.final_output.startswith("The reply was withheld")

    res = SimpleNamespace(final_output=EMAIL)
    await apply_to_pipeline_result(_DB({"mode": "detect"}), "t", res)
    assert res.final_output == EMAIL
