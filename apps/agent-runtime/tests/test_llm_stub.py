from __future__ import annotations

from engine import llm_stub
from engine.llm_router import LLMResponse, LLMRouter


def test_off_unless_both_flags(monkeypatch):
    monkeypatch.delenv("ABENIX_LLM_STUB", raising=False)
    monkeypatch.setenv("CI", "true")
    assert not llm_stub.enabled()
    monkeypatch.setenv("ABENIX_LLM_STUB", "1")
    monkeypatch.delenv("CI", raising=False)
    assert not llm_stub.enabled()
    monkeypatch.setenv("CI", "true")
    assert llm_stub.enabled()


def test_router_sends_everything_to_the_stub(monkeypatch):
    monkeypatch.setenv("ABENIX_LLM_STUB", "1")
    monkeypatch.setenv("CI", "true")
    assert LLMRouter().candidate_chain("claude-sonnet-4-5-20250929") == [
        ("stub", "claude-sonnet-4-5-20250929")
    ]


async def test_reply_echoes_the_last_user_message(monkeypatch):
    monkeypatch.setenv("ABENIX_LLM_STUB", "1")
    monkeypatch.setenv("CI", "true")
    router = LLMRouter()
    msgs = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": [{"type": "text", "text": "hello  there"}]},
    ]
    res = await router.complete(msgs, model="claude-sonnet-4-5-20250929")
    assert isinstance(res, LLMResponse)
    assert res.content == "Stub reply: hello there"

    gen = await router.complete(msgs, model="claude-sonnet-4-5-20250929", stream=True)
    events = [e async for e in gen]
    assert "".join(e.data for e in events if e.event == "token") == res.content
    assert events[-1].event == "done"
