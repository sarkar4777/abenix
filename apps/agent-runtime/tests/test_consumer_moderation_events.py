"""Queue-routed runs record moderation decisions like inline runs."""

import asyncio
from types import SimpleNamespace

import consumer
from engine.moderation_gate import GateConfig, ModerationBlocked, check


def test_gate_sink_collects_a_masked_block():
    events: list = []
    gate = GateConfig(
        policy_id="",
        tenant_id="",
        user_id="",
        custom_patterns=[r"\b\d{3}-\d{2}-\d{4}\b"],
        redaction_mask="#####",
        default_action="block",
        event_sink=consumer._moderation_sink(events),
    )

    async def run():
        try:
            await check("my ssn is 123-45-6789", source="pre_llm", config=gate)
        except ModerationBlocked:
            return True
        return False

    assert asyncio.run(run()) is True
    assert events and events[0]["outcome"] == "blocked"
    assert events[0]["content_preview"] == "my ssn is #####"
    assert events[0]["acted_categories"] == ["custom:0"]


def test_nothing_to_persist_is_a_no_op():
    asyncio.run(consumer._persist_moderation_events(None, [], "x", None))
    asyncio.run(consumer._persist_moderation_events(SimpleNamespace(), [], "x", None))
