"""Queue-routed runs hold content for review the same way inline runs do."""

import asyncio

import consumer
from engine.moderation_gate import GateConfig, ModerationHeld, check


async def _no_provider(_c, model="x"):
    raise RuntimeError("OPENAI_API_KEY not configured")


def test_consumer_sink_carries_the_hold(monkeypatch):
    monkeypatch.setattr("engine.moderation_client._call_openai", _no_provider)
    events: list = []
    gate = GateConfig(
        tenant_id="",
        default_action="hold",
        custom_patterns=[r"ZX-\d+"],
        redaction_mask="##",
        conversation_id="conv-1",
        agent_id="agent-1",
        event_sink=consumer._moderation_sink(events),
    )

    async def run():
        try:
            await check("send ZX-77 over", source="pre_llm", config=gate)
        except ModerationHeld as mh:
            return mh.review_id
        return None

    review_id = asyncio.run(run())
    assert review_id
    e = events[0]
    assert e["outcome"] == "held"
    assert e["content_preview"] == "send ## over"
    assert e["hold"]["review_id"] == review_id
    assert e["hold"]["content"] == "send ZX-77 over"
    assert e["hold"]["conversation_id"] == "conv-1"


def test_executor_stream_announces_the_hold_before_done(monkeypatch):
    from engine.agent_executor import _held_event
    from engine.moderation_client import ModerationDecision

    mh = ModerationHeld(
        ModerationDecision(outcome="held", triggered_categories=["custom:0"]),
        source="pre_llm",
        content_preview="",
        review_id="r-9",
        timeout_minutes=20,
        timeout_action="release",
    )
    data = _held_event(mh)
    assert data["outcome"] == "held" and data["review_id"] == "r-9"
    assert data["timeout_action"] == "release" and data["categories"] == ["custom:0"]
    assert "waiting for review" in data["message"]


def test_no_released_messages_without_a_user():
    assert asyncio.run(consumer._released_for("t", None)) == {}
