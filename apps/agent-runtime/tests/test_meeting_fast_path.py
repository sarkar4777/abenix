"""Unit tests for the meeting-bot latency fixes."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator

import pytest

from engine.tools import _meeting_session as sessmod
from engine.tools.meeting_adapter import AudioFrame, ChatMessage, MeetingAdapter, JoinRequest, JoinResult
from engine.tools.meeting_listen import MeetingListenTool
from engine.tools.scope_gate import ScopeGateTool

pytestmark = pytest.mark.asyncio


class FakeAdapter(MeetingAdapter):
    provider = "fake"

    def __init__(self) -> None:
        self.audio_frames: list[AudioFrame] = []
        self.chat_messages: list[ChatMessage] = []
        self._closed = False

    async def join(self, req: JoinRequest) -> JoinResult:
        return JoinResult(ok=True, session_id="fake-sess")

    async def leave(self, reason: str = "") -> None:
        self._closed = True

    async def publish_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        pass

    async def subscribe_audio(self) -> AsyncIterator[AudioFrame]:
        for frame in self.audio_frames:
            yield frame
            await asyncio.sleep(0.01)
        # Block indefinitely after the seeded frames exhaust. A real
        # adapter never ends its audio stream mid-meeting — it blocks
        # waiting for more frames. We reproduce that so the listen loop
        # must rely on the deadline OR early-exit to return.
        while not self._closed:
            await asyncio.sleep(0.1)

    async def post_chat(self, text: str) -> None:
        pass

    async def subscribe_chat(self) -> AsyncIterator[ChatMessage]:
        for msg in self.chat_messages:
            yield msg
            await asyncio.sleep(0.01)
        while not self._closed:
            await asyncio.sleep(0.1)

    async def list_participants(self) -> list[str]:
        return ["alice"]


async def test_scope_gate_no_session_answers_generic():
    """When the in-memory session is gone (pod restart), a normal"""
    gate = ScopeGateTool(execution_id="no-such-exec")
    result = await gate.execute({"meeting_id": "m1", "question": "what is the company's mission?"})
    payload = json.loads(result.content)
    assert payload["decision"] == "answer", payload
    assert result.metadata.get("no_session") is True


async def test_scope_gate_no_session_still_defers_commitment():
    """Even without a session, a commitment-shaped question MUST defer —
    the safety rail is independent of the in-memory state."""
    gate = ScopeGateTool(execution_id="no-such-exec")
    result = await gate.execute({
        "meeting_id": "m1",
        "question": "can you commit to delivery by Friday?",
    })
    payload = json.loads(result.content)
    assert payload["decision"] == "defer", payload


async def test_meeting_listen_early_exits_on_chat(monkeypatch):
    """A chat message should bounce the listen tool out in well under the"""
    # Stub Redis-backed transcript writes so the test doesn't need Redis.
    async def _noop(*_args, **_kwargs):
        return None

    async def _not_killed(*_args, **_kwargs):
        return False

    monkeypatch.setattr(sessmod, "append_transcript", _noop)
    monkeypatch.setattr(sessmod, "append_decision", _noop)
    monkeypatch.setattr(sessmod, "is_killed", _not_killed)

    adapter = FakeAdapter()
    adapter.chat_messages = [
        ChatMessage(sender="alice", text="what's our current roadmap?", timestamp_ms=0),
    ]
    sess = sessmod.MeetingSession(
        execution_id="exec-1",
        meeting_id="m1",
        tenant_id="t", user_id="u",
        provider="fake", room="r", display_name="Bot",
        adapter=adapter, status="live",
    )
    sessmod.register(sess)
    try:
        tool = MeetingListenTool(execution_id="exec-1")
        t0 = time.monotonic()
        result = await tool.execute({
            "meeting_id": "m1",
            "duration_seconds": 20,  # huge window — we expect early exit well before
            "stt_provider": "none",   # skip Whisper (no OpenAI key in CI)
            "early_exit_on_addressed": True,
        })
        elapsed = time.monotonic() - t0
    finally:
        sessmod.drop("exec-1")
        adapter._closed = True

    # Core assertion: we didn't wait the full 20s window.
    assert elapsed < 5.0, f"listen should have early-exited on chat; took {elapsed:.2f}s"
    payload = json.loads(result.content)
    # Chat message should be in the transcript flagged addressed=true.
    chat_entries = [e for e in payload["transcript"] if e.get("via") == "chat"]
    assert chat_entries, f"expected chat entry; got transcript={payload['transcript']}"
    assert chat_entries[0]["addressed"] is True
    assert payload["addressed"] is True


async def test_meeting_listen_force_wait_when_early_exit_disabled(monkeypatch):
    """Callers that set early_exit_on_addressed=false must still get the
    full-duration wait. Guards against the flag being accidentally ignored."""
    async def _noop(*_a, **_k): return None
    async def _not_killed(*_a, **_k): return False
    monkeypatch.setattr(sessmod, "append_transcript", _noop)
    monkeypatch.setattr(sessmod, "append_decision", _noop)
    monkeypatch.setattr(sessmod, "is_killed", _not_killed)

    adapter = FakeAdapter()
    adapter.chat_messages = [
        ChatMessage(sender="alice", text="hi", timestamp_ms=0),
    ]
    sess = sessmod.MeetingSession(
        execution_id="exec-2",
        meeting_id="m2", tenant_id="t", user_id="u",
        provider="fake", room="r", display_name="Bot",
        adapter=adapter, status="live",
    )
    sessmod.register(sess)
    try:
        tool = MeetingListenTool(execution_id="exec-2")
        t0 = time.monotonic()
        await tool.execute({
            "meeting_id": "m2",
            "duration_seconds": 3,
            "stt_provider": "none",
            "early_exit_on_addressed": False,
        })
        elapsed = time.monotonic() - t0
    finally:
        sessmod.drop("exec-2")
        adapter._closed = True

    # Must honor the full duration (within jitter).
    assert elapsed >= 2.5, f"expected ~3s wait; took {elapsed:.2f}s"
