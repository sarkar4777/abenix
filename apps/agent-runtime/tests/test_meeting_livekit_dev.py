"""LiveKit dev smoke test — pointed at docker `livekit/livekit-server --dev`."""
from __future__ import annotations

import array
import asyncio
import os
import time

import pytest

pytestmark = pytest.mark.asyncio


def _has_livekit_dev() -> bool:
    return bool(os.environ.get("LIVEKIT_URL"))


@pytest.mark.skipif(not _has_livekit_dev(), reason="LIVEKIT_URL not set")
async def test_vad_chunks_speech_and_silence():
    """VAD should split a tone-silence-tone pattern into two utterances."""
    from engine.tools._vad import StreamingVAD

    vad = StreamingVAD(min_utterance_ms=100, hangover_ms=200)
    # 500ms of 440Hz tone @ 16kHz, then 500ms silence, then 500ms tone again
    sr = 16_000
    tone_samples = int(sr * 0.5)
    tone = array.array("h")
    import math
    for i in range(tone_samples):
        tone.append(int(15_000 * math.sin(2 * math.pi * 440 * i / sr)))
    silence = array.array("h", [0] * tone_samples)
    pcm = (tone.tobytes() + silence.tobytes() + tone.tobytes())

    # Feed in ~30ms chunks like the real adapter
    chunk = int(sr * 0.03) * 2
    closed = []
    for i in range(0, len(pcm), chunk):
        closed.extend(vad.feed(pcm[i : i + chunk]))
    tail = vad.flush()
    if tail:
        closed.append(tail)

    assert len(closed) >= 2, f"expected >=2 utterances, got {len(closed)}"
    # each should be roughly 500ms of s16le = 16000 bytes; allow ±50%
    for u in closed:
        assert 8_000 < len(u) < 32_000


@pytest.mark.skipif(not _has_livekit_dev(), reason="LIVEKIT_URL not set")
async def test_mint_token_produces_usable_jwt():
    """Without a real LIVEKIT_API_KEY/SECRET we return empty string; with
    dev keys set we get a JWT."""
    from engine.tools._livekit_adapter import _mint_token
    from engine.tools.meeting_adapter import JoinRequest

    req = JoinRequest(
        provider="livekit", room="af-smoke-1",
        display_name="Abenix Bot", user_id="00000000-0000-0000-0000-000000000001",
        meeting_id="00000000-0000-0000-0000-000000000002",
    )
    token = _mint_token(req, ttl_seconds=300)
    assert token, "expected a JWT string when dev keys are set"
    # JWT has three base64url-encoded parts separated by dots
    assert token.count(".") == 2


@pytest.mark.skipif(not _has_livekit_dev(), reason="LIVEKIT_URL not set")
async def test_token_accepted_by_dev_server():
    """HTTP validate-token smoke. The server's /rtc/validate endpoint"""
    import httpx
    from engine.tools._livekit_adapter import _mint_token
    from engine.tools.meeting_adapter import JoinRequest

    req = JoinRequest(
        provider="livekit",
        room=f"af-smoke-{int(time.time())}",
        display_name="Abenix Smoke Bot",
        user_id="00000000-0000-0000-0000-000000000001",
        meeting_id="00000000-0000-0000-0000-000000000002",
    )
    token = _mint_token(req, ttl_seconds=300)
    assert token, "token mint failed"

    url = os.environ["LIVEKIT_URL"].replace("ws://", "http://").replace("wss://", "https://").rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{url}/rtc/validate", params={"access_token": token})
    assert r.status_code == 200, f"validate returned {r.status_code}: {r.text}"
    assert "success" in r.text.lower(), f"expected 'success', got: {r.text[:200]}"


@pytest.mark.skipif(not _has_livekit_dev(), reason="LIVEKIT_URL not set")
@pytest.mark.skipif(os.name == "nt", reason="Docker+Windows WebRTC UDP binding is flaky; runs on Linux CI.")
async def test_adapter_can_connect_to_dev_server():
    """End-to-end RTC connect (Linux-only). Verifies the adapter opens the
    signal channel, publishes the bot's audio track, and cleanly leaves."""
    try:
        from livekit import rtc  # noqa: F401
    except ImportError:
        pytest.skip("livekit SDK not installed")

    from engine.tools._livekit_adapter import LiveKitAdapter
    from engine.tools.meeting_adapter import JoinRequest

    adapter = LiveKitAdapter()
    req = JoinRequest(
        provider="livekit",
        room=f"af-smoke-{int(time.time())}",
        display_name="Abenix Smoke Bot",
        user_id="00000000-0000-0000-0000-000000000001",
        meeting_id="00000000-0000-0000-0000-000000000002",
    )
    result = await adapter.join(req)
    try:
        assert result.ok, f"join failed: {result.error}"
        assert result.session_id.startswith("lk-")
        await adapter.post_chat("hello from the smoke test")
        await adapter.publish_audio(b"\x00" * 3200, sample_rate=16_000)
        parts = await adapter.list_participants()
        assert isinstance(parts, list)
    finally:
        await adapter.leave(reason="smoke_done")
