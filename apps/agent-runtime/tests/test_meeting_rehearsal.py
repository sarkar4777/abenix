"""Rehearsal runs the live meeting tools against typed turns."""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from engine.tools import _meeting_session as sessmod
from engine.tools import meeting_speak as speakmod
from engine.tools._rehearsal_adapter import RehearsalAdapter, turns_key
from engine.tools.meeting_adapter import JoinRequest, get_adapter
from engine.tools.meeting_listen import MeetingListenTool
from engine.tools.meeting_speak import MeetingSpeakTool
from engine.tools.scope_gate import ScopeGateTool

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    async def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    async def blpop(self, key, timeout=1):
        items = self.lists.get(key) or []
        if items:
            return key, items.pop(0)
        await asyncio.sleep(0.02)
        return None

    async def get(self, key):
        return None


@pytest.fixture
def recorded(monkeypatch):
    out = {"transcript": [], "decisions": []}
    fake = FakeRedis()

    async def _redis():
        return fake

    async def _transcript(mid, who, text, *, ts_ms=0, extra=None):
        out["transcript"].append({"who": who, "text": text, **(extra or {})})

    async def _decision(mid, kind, text, *, detail=None):
        out["decisions"].append((kind, text))

    async def _not_killed(mid):
        return False

    monkeypatch.setattr(sessmod, "_redis", _redis)
    monkeypatch.setattr(sessmod, "append_transcript", _transcript)
    monkeypatch.setattr(sessmod, "append_decision", _decision)
    monkeypatch.setattr(sessmod, "is_killed", _not_killed)
    out["redis"] = fake
    return out


def _session(adapter, **kw):
    sess = sessmod.MeetingSession(
        execution_id="exec-r",
        meeting_id="rehearsal-abc",
        tenant_id="t",
        user_id="u",
        provider="rehearsal",
        room="rehearsal-abc",
        display_name="Rep",
        adapter=adapter,
        status="live",
        **kw,
    )
    sessmod.register(sess)
    return sess


async def test_rehearsal_is_a_registered_simulated_provider():
    adapter = get_adapter("rehearsal")
    assert isinstance(adapter, RehearsalAdapter)
    assert adapter.simulated is True


async def test_typed_turn_reaches_listen_and_sets_latency_clock(recorded):
    adapter = RehearsalAdapter()
    await adapter.join(
        JoinRequest(
            provider="rehearsal",
            room="x",
            display_name="Rep",
            meeting_id="rehearsal-abc",
        )
    )
    sess = _session(adapter, scope_allow=["roadmap"])
    try:
        ts = int(time.time() * 1000)
        await recorded["redis"].rpush(
            turns_key("rehearsal-abc"),
            json.dumps(
                {"speaker": "Dana", "text": "where is the roadmap?", "ts_ms": ts}
            ),
        )
        t0 = time.monotonic()
        res = await MeetingListenTool(execution_id="exec-r").execute(
            {
                "meeting_id": "rehearsal-abc",
                "duration_seconds": 10,
                "stt_provider": "none",
            }
        )
        assert time.monotonic() - t0 < 5
        payload = json.loads(res.content)
        assert payload["addressed"] is True
        assert payload["transcript"][0]["text"] == "where is the roadmap?"
        assert sess.last_addressed_ms == ts
        assert recorded["transcript"][0]["via"] == "chat"
        # scoped in code, whether or not the model calls scope_gate
        assert payload["transcript"][0]["scope"] == "answer"
        assert ("answer", "Scope check: inside the topics you allowed") in recorded[
            "decisions"
        ]
    finally:
        await adapter.leave()
        sessmod.drop("exec-r")


async def test_simulated_speak_spends_no_voice_and_records_latency(
    recorded, monkeypatch
):
    async def _boom(*a, **k):
        raise AssertionError("rehearsal must not call TTS")

    monkeypatch.setattr(speakmod, "_synthesize", _boom)
    adapter = RehearsalAdapter()
    sess = _session(adapter)
    sess.last_addressed_ms = int(time.time() * 1000) - 1500
    try:
        res = await MeetingSpeakTool(execution_id="exec-r").execute(
            {"meeting_id": "rehearsal-abc", "text": "The roadmap ships in phases."}
        )
    finally:
        sessmod.drop("exec-r")
    assert res.metadata["provider"] == "none"
    line = recorded["transcript"][-1]
    assert line["bot"] is True and line["via"] == "rehearsal"
    assert line["latency_ms"] >= 1500
    # one latency per question
    assert sess.last_addressed_ms == 0
    assert adapter.chat_out == ["The roadmap ships in phases."]


async def test_scope_gate_declines_outside_the_allow_list(recorded):
    sess = _session(
        RehearsalAdapter(), scope_allow=["roadmap"], scope_defer=["pricing"]
    )
    gate = ScopeGateTool(execution_id="exec-r")
    try:

        async def ask(q):
            r = await gate.execute({"meeting_id": "rehearsal-abc", "question": q})
            return json.loads(r.content)["decision"]

        assert await ask("what is on the roadmap?") == "answer"
        assert await ask("what is the pricing?") == "defer"
        assert await ask("who won the football match?") == "decline"
        # a commitment defers even when the topic is allowed
        assert await ask("can you commit to the roadmap by friday?") == "defer"
    finally:
        sessmod.drop("exec-r")
    assert sess


async def test_listen_explains_missing_speech_to_text(recorded, monkeypatch):
    from engine.tools import meeting_listen as lm
    from engine.tools.meeting_adapter import AudioFrame

    monkeypatch.setattr(lm, "_get_openai_client", lambda: None)

    class Loud(RehearsalAdapter):
        simulated = False

        async def subscribe_audio(self):
            for _ in range(200):
                yield AudioFrame(pcm=b"\x10\x27" * 320, participant="alice")
                await asyncio.sleep(0)
            await self._closed.wait()

    adapter = Loud()
    _session(adapter)
    try:
        res = await lm.MeetingListenTool(execution_id="exec-r").execute(
            {"meeting_id": "rehearsal-abc", "duration_seconds": 3}
        )
    finally:
        await adapter.leave()
        sessmod.drop("exec-r")
    assert "stt_unavailable" in json.loads(res.content)
    assert any(
        k == "notice" and "OpenAI API key" in t for k, t in recorded["decisions"]
    )


async def test_livekit_chat_reads_old_and_new_data_events():
    from types import SimpleNamespace

    from engine.tools._livekit_adapter import chat_from_data_event

    who = SimpleNamespace(identity="user-1", name="Dana")
    new = chat_from_data_event(SimpleNamespace(data=b"roadmap?", participant=who))
    old = chat_from_data_event(b"roadmap?", who, 1)
    assert new.text == old.text == "roadmap?" and new.sender == "Dana"
    assert chat_from_data_event(SimpleNamespace(data=b"  ", participant=who)) is None


async def test_livekit_post_chat_uses_reliable_keyword():
    from types import SimpleNamespace

    pytest.importorskip("livekit.rtc")

    from engine.tools._livekit_adapter import LiveKitAdapter

    sent = []

    async def publish_data(
        payload, *, reliable=True, destination_identities=(), topic=""
    ):
        sent.append((payload, reliable))

    adapter = LiveKitAdapter()
    adapter._room = SimpleNamespace(
        local_participant=SimpleNamespace(publish_data=publish_data)
    )
    await adapter.post_chat("hello room")
    assert sent == [(b"hello room", True)]
