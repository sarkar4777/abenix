"""LiveKit concrete MeetingAdapter."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, AsyncIterator

from engine.tools.meeting_adapter import (
    AudioFrame,
    ChatMessage,
    JoinRequest,
    JoinResult,
    MeetingAdapter,
    _BoundedQueue,
)

logger = logging.getLogger(__name__)

# Target format for STT — Whisper + most cloud ASR likes 16kHz mono s16le.
_TARGET_RATE = 16_000
_TARGET_CHANNELS = 1


class LiveKitAdapter(MeetingAdapter):
    provider = "livekit"

    def __init__(self) -> None:
        self._room: Any = None  # rtc.Room
        self._audio_source: Any = None  # rtc.AudioSource
        self._audio_track: Any = None  # rtc.LocalAudioTrack
        self._audio_q = _BoundedQueue(maxsize=500)
        self._chat_q = _BoundedQueue(maxsize=500)
        self._session_id: str = ""
        self._closed = asyncio.Event()

    async def join(self, req: JoinRequest) -> JoinResult:
        try:
            from livekit import rtc
        except ImportError:
            return JoinResult(
                ok=False,
                error=(
                    "livekit SDK not installed. Add `livekit==0.17.*` "
                    "and `livekit-api==0.7.*` to apps/agent-runtime/pyproject.toml."
                ),
            )

        url = req.url or os.environ.get("LIVEKIT_URL", "").strip()
        token = req.token
        if not token:
            token = _mint_token(req, ttl_seconds=3600)
        if not url or not token:
            return JoinResult(
                ok=False,
                error=(
                    "LiveKit connection missing url/token. Set LIVEKIT_URL, "
                    "LIVEKIT_API_KEY, LIVEKIT_API_SECRET — or pass them in the "
                    "join request."
                ),
            )

        room = rtc.Room()

        # Track subscribed → stream audio frames into our queue
        @room.on("track_subscribed")
        def _on_track(track, publication, participant):  # type: ignore[no-redef]
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                asyncio.create_task(
                    self._consume_audio_track(track, participant.identity)
                )

        # Data channel for chat
        @room.on("data_received")
        def _on_data(data, participant, kind):  # type: ignore[no-redef]
            try:
                text = (data or b"").decode("utf-8", errors="ignore")
            except Exception:
                return
            asyncio.create_task(
                self._chat_q.put(
                    ChatMessage(
                        sender=getattr(participant, "identity", "?"),
                        text=text,
                        timestamp_ms=int(time.time() * 1000),
                    )
                )
            )

        @room.on("disconnected")
        def _on_disc():  # type: ignore[no-redef]
            self._closed.set()
            self._audio_q.close()
            self._chat_q.close()

        try:
            await room.connect(url, token)
        except Exception as e:
            return JoinResult(ok=False, error=f"LiveKit connect failed: {e}")

        # Publish our own audio track for speaking
        self._audio_source = rtc.AudioSource(_TARGET_RATE, _TARGET_CHANNELS)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "bot-speech", self._audio_source
        )
        try:
            await room.local_participant.publish_track(
                self._audio_track,
                rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
            )
        except Exception as e:
            logger.warning("LiveKit: publish audio track failed — %s", e)

        self._room = room
        self._session_id = f"lk-{req.meeting_id or req.room}-{int(time.time())}"
        logger.info("LiveKit: joined room=%s session_id=%s", req.room, self._session_id)
        return JoinResult(
            ok=True,
            session_id=self._session_id,
            provider_room_sid=room.sid or "",
        )

    async def leave(self, reason: str = "bot_done") -> None:
        if self._room is None:
            return
        try:
            await self._room.disconnect()
        except Exception:
            pass
        self._closed.set()
        self._audio_q.close()
        self._chat_q.close()

    async def publish_audio(self, pcm: bytes, *, sample_rate: int = 16000) -> None:
        if not self._audio_source:
            return
        try:
            from livekit import rtc
        except ImportError:
            return
        if sample_rate != _TARGET_RATE:
            pcm = _resample_pcm(pcm, sample_rate, _TARGET_RATE)
        # chunk into ~10ms frames (160 samples at 16kHz mono s16le)
        frame_bytes = 320  # 10ms * 16kHz * 2 bytes
        for i in range(0, len(pcm), frame_bytes):
            chunk = pcm[i : i + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
            try:
                frame = rtc.AudioFrame(
                    data=chunk,
                    sample_rate=_TARGET_RATE,
                    num_channels=_TARGET_CHANNELS,
                    samples_per_channel=len(chunk) // 2,
                )
            except TypeError:
                # Older SDK signature — fall back to .create() + cast
                frame = rtc.AudioFrame.create(
                    _TARGET_RATE, _TARGET_CHANNELS, len(chunk) // 2
                )
                try:
                    memoryview(frame.data).cast("B")[: len(chunk)] = chunk
                except Exception:
                    # Last-ditch: convert bytes -> int16 array, assign element-wise
                    import array

                    samples = array.array("h")
                    samples.frombytes(chunk)
                    for idx, s in enumerate(samples):
                        if idx >= len(frame.data):
                            break
                        frame.data[idx] = s
            try:
                await self._audio_source.capture_frame(frame)
            except Exception as e:
                logger.debug("LiveKit: capture_frame failed: %s", e)
                break

    async def subscribe_audio(self) -> AsyncIterator[AudioFrame]:  # type: ignore[override]
        while not self._closed.is_set():
            item = await self._audio_q.get()
            if item is None:
                break
            yield item

    async def _consume_audio_track(self, track: Any, identity: str) -> None:
        try:
            from livekit import rtc
        except ImportError:
            return
        stream = rtc.AudioStream(track)
        async for frame_event in stream:
            # frame_event.frame: rtc.AudioFrame with .data (bytearray), .sample_rate, .num_channels
            af = frame_event.frame
            try:
                pcm = bytes(af.data)
            except Exception:
                continue
            if af.sample_rate != _TARGET_RATE or af.num_channels != _TARGET_CHANNELS:
                pcm = _resample_pcm(
                    pcm,
                    af.sample_rate,
                    _TARGET_RATE,
                    channels_in=af.num_channels,
                    channels_out=_TARGET_CHANNELS,
                )
            await self._audio_q.put(
                AudioFrame(
                    pcm=pcm,
                    sample_rate=_TARGET_RATE,
                    channels=_TARGET_CHANNELS,
                    participant=identity,
                    timestamp_ms=int(time.time() * 1000),
                )
            )

    async def post_chat(self, text: str) -> None:
        if self._room is None:
            return
        try:
            from livekit import rtc
        except ImportError:
            return
        try:
            await self._room.local_participant.publish_data(
                text.encode("utf-8"), kind=rtc.DataPacketKind.KIND_RELIABLE
            )
        except Exception as e:
            logger.debug("LiveKit post_chat failed: %s", e)

    async def subscribe_chat(self) -> AsyncIterator[ChatMessage]:  # type: ignore[override]
        while not self._closed.is_set():
            item = await self._chat_q.get()
            if item is None:
                break
            yield item

    async def list_participants(self) -> list[str]:
        if self._room is None:
            return []
        try:
            return [p.identity for p in self._room.remote_participants.values()]
        except Exception:
            return []


def _mint_token(req: JoinRequest, *, ttl_seconds: int = 3600) -> str:
    """Mint a JWT for LiveKit using the server API key/secret."""
    api_key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    if not (api_key and api_secret):
        return ""
    try:
        import jwt as pyjwt
    except ImportError:
        # PyJWT isn't installed — fall back to livekit's builtin (may fail on skew)
        try:
            from livekit import api
            from datetime import timedelta

            grant = api.VideoGrants(
                room_join=True,
                room=req.room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
            return (
                api.AccessToken(api_key, api_secret)
                .with_identity(f"bot-{req.user_id or 'agent'}")
                .with_name(req.display_name or "Abenix Bot")
                .with_grants(grant)
                .with_ttl(timedelta(seconds=ttl_seconds))
                .to_jwt()
            )
        except ImportError:
            return ""
    import time as _time

    now = int(_time.time())
    claims = {
        "iss": api_key,
        "sub": f"bot-{req.user_id or 'agent'}",
        "name": req.display_name or "Abenix Bot",
        "nbf": now - 60,  # clock-skew tolerance
        "exp": now + ttl_seconds,
        "video": {
            "roomJoin": True,
            "room": req.room,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    return pyjwt.encode(claims, api_secret, algorithm="HS256")


def _resample_pcm(
    pcm: bytes,
    rate_in: int,
    rate_out: int,
    *,
    channels_in: int = 1,
    channels_out: int = 1,
) -> bytes:
    """Very simple linear resampler. Good enough for 48k→16k + channel"""
    if not pcm:
        return b""
    if rate_in == rate_out and channels_in == channels_out:
        return pcm
    # Interpret as s16le
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
    # Downmix to mono if needed
    if channels_in > 1 and channels_out == 1:
        mono = array.array("h")
        step = channels_in
        for i in range(0, len(samples), step):
            s = sum(samples[i : i + step]) // step
            # Clamp to s16 range
            s = max(-32768, min(32767, s))
            mono.append(s)
        samples = mono
    # Rate conversion via linear interpolation
    if rate_in != rate_out and samples:
        ratio = rate_out / rate_in
        new_len = max(1, int(len(samples) * ratio))
        out = array.array("h", [0] * new_len)
        for j in range(new_len):
            src = j / ratio
            lo = int(src)
            hi = min(lo + 1, len(samples) - 1)
            frac = src - lo
            v = int(samples[lo] * (1 - frac) + samples[hi] * frac)
            out[j] = max(-32768, min(32767, v))
        samples = out
    return samples.tobytes()
