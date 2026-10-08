"""A reply the output policy could stop is never streamed before the check decides."""

from __future__ import annotations

from unittest.mock import MagicMock

from engine.agent_executor import AgentExecutor
from engine.llm_router import LLMRouter, StreamEvent
from engine.moderation_gate import GateConfig, guards_output
from engine.tools.base import ToolRegistry

REPLY = ["Your ticket ", "ZX-4242", " is filed."]


def _router() -> LLMRouter:
    async def complete(**kwargs):
        async def gen():
            for t in REPLY:
                yield StreamEvent(event="token", data=t)
            yield StreamEvent(
                event="done",
                data={
                    "model": "claude-sonnet-4-5-20250929",
                    "input_tokens": 1,
                    "output_tokens": 3,
                    "cost": 0.0,
                    "latency_ms": 1,
                    "tool_calls": [],
                },
            )

        return gen()

    router = LLMRouter()
    provider = MagicMock()
    provider.complete = complete
    router._providers["anthropic"] = provider
    return router


async def _no_provider(_c, model="x"):
    raise RuntimeError("OPENAI_API_KEY not configured")


def _gate(action: str, **kw) -> GateConfig:
    return GateConfig(
        pre_llm=False,
        post_llm=True,
        default_action=action,
        custom_patterns=[r"ZX-\d+"],
        redaction_mask="##",
        **kw,
    )


async def _run(gate: GateConfig | None, monkeypatch) -> list:
    monkeypatch.setattr("engine.moderation_client._call_openai", _no_provider)
    ex = AgentExecutor(
        llm_router=_router(), tool_registry=ToolRegistry(), moderation_gate=gate
    )
    return [e async for e in ex.stream("file it")]


def test_which_policies_guard_the_reply():
    assert not guards_output(None)
    assert not guards_output(GateConfig(post_llm=True, default_action="flag"))
    assert not guards_output(GateConfig(post_llm=False, default_action="hold"))
    assert guards_output(GateConfig(post_llm=True, default_action="hold"))
    assert guards_output(GateConfig(post_llm=True, default_action="block"))
    assert guards_output(
        GateConfig(
            post_llm=True, default_action="flag", category_actions={"hate": "block"}
        )
    )
    assert guards_output(
        GateConfig(post_llm=True, default_action="flag", fail_closed=True)
    )


async def test_a_held_reply_never_reaches_the_stream(monkeypatch):
    events = await _run(_gate("hold"), monkeypatch)
    kinds = [e.event for e in events]
    tokens = "".join(str(e.data) for e in events if e.event == "token")
    assert "ZX-4242" not in tokens and "Your ticket" not in tokens
    assert kinds.index("reply_checking") < kinds.index("moderation")
    mod = next(e.data for e in events if e.event == "moderation")
    assert mod["outcome"] == "held" and "ZX-4242" not in str(mod)
    assert events[-1].data["moderation_held"] is True


async def test_a_blocked_reply_never_reaches_the_stream(monkeypatch):
    events = await _run(_gate("block"), monkeypatch)
    assert not any("ZX-4242" in str(e.data) for e in events)
    assert events[-1].data["moderation_blocked"] is True


async def test_a_clean_guarded_reply_arrives_in_one_piece_after_the_check(monkeypatch):
    gate = _gate("hold")
    gate.custom_patterns = [r"NOPE-\d+"]
    events = await _run(gate, monkeypatch)
    kinds = [e.event for e in events]
    tokens = [e.data for e in events if e.event == "token"]
    assert tokens == ["".join(REPLY)]
    assert kinds.index("reply_checking") < kinds.index("token")


async def test_a_redacted_guarded_reply_shows_only_the_masked_text(monkeypatch):
    events = await _run(_gate("redact"), monkeypatch)
    assert not any("ZX-4242" in str(e.data) for e in events)
    mod = next(e.data for e in events if e.event == "moderation")
    assert mod["content"] == "Your ticket ## is filed."
    assert not [e for e in events if e.event == "token"]


async def test_without_an_output_policy_tokens_stream_as_before(monkeypatch):
    events = await _run(GateConfig(post_llm=True, default_action="flag"), monkeypatch)
    assert [e.data for e in events if e.event == "token"] == REPLY
    assert "reply_checking" not in [e.event for e in events]
