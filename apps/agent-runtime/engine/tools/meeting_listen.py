"""Meeting listen tool — streaming STT via VAD-chunked Whisper."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
import wave
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod
from engine.tools._vad import StreamingVAD

logger = logging.getLogger(__name__)

# Phrases treated as direct bot addressing; the agent sees `addressed=true` on
# the corresponding utterance so it can prioritize a response.
_ADDRESS_MARKERS = (
    "hey bot",
    "hi bot",
    "ok bot",
    "bot,",
    "bot ",
    "hey assistant",
    "ok assistant",
    "assistant,",
    "hey abenix",
    "abenix,",
)

_KILL_MARKERS = (
    "bot leave",
    "bot, leave",
    "agent leave",
    "assistant leave",
    "bot stop",
    "bot, stop",
    "remove the bot",
)

# Whisper hallucinates these on silent / noisy audio. Drop them entirely
# rather than ship them to the agent (the agent would treat them as real
# utterances and react inappropriately).
_HALLUCINATION_MARKERS = (
    "thanks for watching",
    "thank you for watching",
    "subscribe to",
    "msworddoc word.d",
    "microsoft word",
    "for more information visit",
    "www.",
    "youtube.com",
    "click here",
    "captions by",
    "translated by",
    "amara.org",
    "go.com",
)


def _is_likely_hallucination(text: str) -> bool:
    """Whisper output that's very probably hallucinated from silence/noise.
    These aren't real speech in the meeting and shouldn't reach the agent."""
    t = (text or "").strip().lower()
    if not t:
        return True
    if any(m in t for m in _HALLUCINATION_MARKERS):
        return True
    # Single-word "transcripts" are usually filler ("you", "okay", ".")
    if len(t.split()) <= 1 and len(t) < 8:
        return True
    return False


class MeetingListenTool(BaseTool):
    name = "meeting_listen"
    description = (
        "Stream audio from the joined meeting for a bounded window, run "
        "Whisper STT on utterance boundaries (VAD-based), and return the "
        "transcript. Utterances publish to the meeting's Redis event stream "
        "AS THEY CLOSE — so the UI sees text flow in real time, not in "
        "10-second batches. Honors 'bot leave' voice commands and flags "
        "utterances that address the bot directly (addressed=true)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "duration_seconds": {
                "type": "integer",
                "default": 8,
                "minimum": 3,
                "maximum": 60,
                "description": (
                    "Maximum listen window. Loop EXITS EARLY the moment an "
                    "addressed utterance (voice or chat) is fully transcribed, "
                    "so typical turn-around is under 2s, not `duration_seconds`."
                ),
            },
            "stt_provider": {
                "type": "string",
                "enum": ["openai", "none"],
                "default": "openai",
                "description": "'none' returns VAD-chunked audio stats only (debug).",
            },
            "min_words_for_entry": {
                "type": "integer",
                "default": 1,
                "minimum": 0,
            },
            "display_name": {
                "type": "string",
                "default": "",
                "description": "Bot display name — utterances containing it are flagged addressed=true.",
            },
            "early_exit_on_addressed": {
                "type": "boolean",
                "default": True,
                "description": (
                    "When true (default), return as soon as an addressed "
                    "utterance closes. Set false to force-wait the full window."
                ),
            },
        },
        "required": ["meeting_id"],
    }

    def __init__(self, *, execution_id: str = ""):
        self._execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        sess = sessmod.get(self._execution_id)
        if not sess or sess.adapter is None:
            return ToolResult(
                content="No live meeting session — call meeting_join first.",
                is_error=True,
            )
        if sess.meeting_id != meeting_id:
            return ToolResult(content="meeting_id mismatch", is_error=True)
        if await sessmod.is_killed(meeting_id):
            return ToolResult(
                content="Kill-switch active — exiting.",
                is_error=True,
                metadata={"kill_requested": True},
            )

        duration = int(arguments.get("duration_seconds", 8))
        stt_provider = (arguments.get("stt_provider") or "openai").lower()
        min_words = int(arguments.get("min_words_for_entry", 1))
        display_name = (
            (arguments.get("display_name") or sess.display_name or "").strip().lower()
        )
        early_exit = bool(arguments.get("early_exit_on_addressed", True))
        deadline = time.monotonic() + duration

        # Per-speaker VAD + concurrent transcription tasks
        vads: dict[str, StreamingVAD] = {}
        tasks: list[asyncio.Task] = []
        transcript: list[dict[str, Any]] = []
        transcript_lock = asyncio.Lock()
        kill_heard = False
        addressed_any = False
        # Signalled as soon as we know the agent has something worth
        # reacting to (addressed utterance OR kill). Lets the audio drain
        # loop wake out of its `await` and return.
        exit_event = asyncio.Event()

        async def transcribe_and_record(speaker: str, pcm: bytes):
            nonlocal kill_heard, addressed_any
            if stt_provider != "openai":
                return
            text = await _whisper_transcribe(pcm)
            if not text:
                return
            if _is_likely_hallucination(text):
                logger.debug("dropping likely-hallucinated transcript: %s", text[:80])
                return
            words = text.split()
            if len(words) < min_words:
                return
            lowered = text.lower()
            addressed = bool(display_name and display_name in lowered) or any(
                m in lowered for m in _ADDRESS_MARKERS
            )
            if not addressed:
                ends_q = text.strip().endswith("?")
                starts_q = lowered.split(" ", 1)[0] in (
                    "what",
                    "where",
                    "when",
                    "who",
                    "why",
                    "how",
                    "can",
                    "could",
                    "should",
                    "would",
                    "is",
                    "are",
                    "do",
                    "does",
                    "did",
                )
                if ends_q or starts_q:
                    addressed = True
            if any(k in lowered for k in _KILL_MARKERS):
                kill_heard = True
                exit_event.set()
            if addressed:
                addressed_any = True
                if early_exit:
                    exit_event.set()
            entry = {
                "speaker": speaker,
                "text": text,
                "ts_ms": int(time.time() * 1000),
                "addressed": addressed,
            }
            async with transcript_lock:
                transcript.append(entry)
            await sessmod.append_transcript(
                meeting_id, speaker, text, ts_ms=entry["ts_ms"]
            )

        # Chat messages are unambiguously addressed to the bot (the user
        # typed them in the meeting chat panel). Tag them addressed=true
        # so the agent's loop reacts.
        async def consume_chat():
            nonlocal addressed_any, kill_heard
            try:
                async for msg in sess.adapter.subscribe_chat():
                    if msg is None:
                        break
                    text = (msg.text or "").strip()
                    if not text:
                        continue
                    lowered = text.lower()
                    if any(k in lowered for k in _KILL_MARKERS):
                        kill_heard = True
                        exit_event.set()
                    addressed_any = True
                    entry = {
                        "speaker": f"{msg.sender or 'chat'} (chat)",
                        "text": text,
                        "ts_ms": int(time.time() * 1000),
                        "addressed": True,
                        "via": "chat",
                    }
                    async with transcript_lock:
                        transcript.append(entry)
                    await sessmod.append_transcript(
                        meeting_id, entry["speaker"], text, ts_ms=entry["ts_ms"]
                    )
                    # Chat messages are ALWAYS explicitly addressed to the
                    # bot — exit the listen window immediately so the agent
                    # can respond without waiting out the full duration.
                    if early_exit:
                        exit_event.set()
                        break
                    if time.monotonic() >= deadline:
                        break
            except Exception as e:
                logger.debug("chat consumer error: %s", e)

        chat_task = asyncio.create_task(consume_chat())

        audio_iter = sess.adapter.subscribe_audio()
        local_q: asyncio.Queue = asyncio.Queue(maxsize=500)

        async def _audio_producer():
            try:
                async for frame in audio_iter:
                    if frame is None:
                        break
                    await local_q.put(frame)
            except Exception as e:
                logger.debug("meeting_listen audio producer error: %s", e)
            finally:
                await local_q.put(None)  # sentinel

        producer_task = asyncio.create_task(_audio_producer())
        last_kill_check = 0.0
        try:
            while (
                time.monotonic() < deadline
                and not kill_heard
                and not exit_event.is_set()
            ):
                remaining = deadline - time.monotonic()
                # Poll Redis kill-switch at most every ~1s — keeps the hot
                # path light.
                now = time.monotonic()
                if now - last_kill_check > 1.0:
                    last_kill_check = now
                    if await sessmod.is_killed(meeting_id):
                        kill_heard = True
                        break
                try:
                    frame = await asyncio.wait_for(
                        local_q.get(), timeout=min(remaining, 0.5)
                    )
                except asyncio.TimeoutError:
                    continue
                if frame is None:
                    break
                speaker = frame.participant or "unknown"
                vad = vads.setdefault(speaker, StreamingVAD())
                for utt in vad.feed(frame.pcm):
                    tasks.append(
                        asyncio.create_task(transcribe_and_record(speaker, utt))
                    )
        except Exception as e:
            logger.debug("meeting_listen loop error: %s", e)
        finally:
            if not producer_task.done():
                producer_task.cancel()
                try:
                    await producer_task
                except (asyncio.CancelledError, Exception):
                    pass

        # Flush any in-progress utterance at window end
        for speaker, vad in vads.items():
            tail = vad.flush()
            if tail:
                tasks.append(asyncio.create_task(transcribe_and_record(speaker, tail)))

        # Stop the chat consumer
        if not chat_task.done():
            chat_task.cancel()

        # Wait for all in-flight transcriptions (bounded — 15s max)
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=15.0,
                )
            except asyncio.TimeoutError:
                for t in tasks:
                    if not t.done():
                        t.cancel()

        if kill_heard:
            await sessmod.set_kill(meeting_id)

        # Sort by timestamp so the return transcript is chronological even
        # though tasks completed in race-y order.
        transcript.sort(key=lambda e: e.get("ts_ms", 0))

        return ToolResult(
            content=json.dumps(
                {
                    "meeting_id": meeting_id,
                    "duration_seconds": duration,
                    "transcript": transcript,
                    "kill_requested": kill_heard,
                    "addressed": addressed_any,
                }
            ),
            metadata={
                "entries": len(transcript),
                "kill_requested": kill_heard,
                "addressed": addressed_any,
                "streaming": True,
            },
        )


_OPENAI_CLIENT: Any = None
_OPENAI_CLIENT_KEY: str = ""


def _get_openai_client() -> Any:
    """Reuse a single AsyncOpenAI client across Whisper calls in this process."""
    global _OPENAI_CLIENT, _OPENAI_CLIENT_KEY
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    if _OPENAI_CLIENT is not None and _OPENAI_CLIENT_KEY == api_key:
        return _OPENAI_CLIENT
    _OPENAI_CLIENT = AsyncOpenAI(api_key=api_key, timeout=10.0, max_retries=1)
    _OPENAI_CLIENT_KEY = api_key
    return _OPENAI_CLIENT


async def _whisper_transcribe(pcm: bytes) -> str:
    """Single-shot Whisper via OpenAI. Called per utterance (not per window)."""
    client = _get_openai_client()
    if client is None:
        return ""
    wav = _pcm_to_wav(pcm, sample_rate=16_000)
    try:
        buf = io.BytesIO(wav)
        buf.name = "audio.wav"
        resp = await client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            response_format="text",
            # Prompt biases the model toward proper nouns it's otherwise
            # likely to mangle ("Tathagata", "Abenix", "LiveKit").
            prompt="Abenix LiveKit meeting — business discussion.",
        )
        return (
            (resp or "").strip()
            if isinstance(resp, str)
            else getattr(resp, "text", "").strip()
        )
    except Exception as e:
        logger.debug("whisper transcribe failed: %s", e)
        return ""


def _pcm_to_wav(pcm: bytes, *, sample_rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
