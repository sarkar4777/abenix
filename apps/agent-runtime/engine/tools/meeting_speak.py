"""Meeting speak tool — TTS + publish into the meeting audio track."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Any

from engine.tools.base import BaseTool, ToolResult
from engine.tools import _meeting_session as sessmod

logger = logging.getLogger(__name__)

_TTS_CACHE: dict[str, tuple[float, bytes]] = {}
_TTS_CACHE_TTL = 60.0
_TTS_CACHE_MAX = 100

_TTS_OPENAI_CLIENT: Any = None
_TTS_OPENAI_CLIENT_KEY: str = ""
_CONSENT_CACHE: dict[tuple[str, str], tuple[float, bool]] = {}
_CONSENT_CACHE_TTL = 60.0


def _get_tts_openai_client() -> Any:
    """Singleton AsyncOpenAI client for TTS — pooled HTTPS reuse."""
    global _TTS_OPENAI_CLIENT, _TTS_OPENAI_CLIENT_KEY
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    if _TTS_OPENAI_CLIENT is not None and _TTS_OPENAI_CLIENT_KEY == api_key:
        return _TTS_OPENAI_CLIENT
    _TTS_OPENAI_CLIENT = AsyncOpenAI(api_key=api_key, timeout=15.0, max_retries=1)
    _TTS_OPENAI_CLIENT_KEY = api_key
    return _TTS_OPENAI_CLIENT


class MeetingSpeakTool(BaseTool):
    name = "meeting_speak"
    description = (
        "Speak text into the joined meeting. Supports OpenAI neutral voices "
        "OR ElevenLabs cloned voices (if the user has a consented voice_id). "
        "Every call mirrors the text to the meeting chat. Keep utterances "
        "short (< 280 chars); longer text is auto-split on sentence boundaries."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "meeting_id": {"type": "string"},
            "text": {"type": "string", "minLength": 1, "maxLength": 1200},
            "voice": {
                "type": "string",
                "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                "default": "alloy",
                "description": "OpenAI voice when provider='openai' or falling back.",
            },
            "voice_id": {
                "type": "string",
                "description": (
                    "ElevenLabs voice_id. When provided AND ELEVENLABS_API_KEY is set, "
                    "uses ElevenLabs TTS. If the voice_id is the session user's own "
                    "cloned voice, requires consent recorded on their account."
                ),
                "default": "",
            },
            "mirror_to_chat": {"type": "boolean", "default": True},
        },
        "required": ["meeting_id", "text"],
    }

    def __init__(self, *, execution_id: str = ""):
        self._execution_id = execution_id

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        meeting_id = (arguments.get("meeting_id") or "").strip()
        text = (arguments.get("text") or "").strip()
        voice = (
            arguments.get("voice") or os.environ.get("OPENAI_TTS_VOICE", "alloy")
        ).strip()
        voice_id = (arguments.get("voice_id") or "").strip()
        mirror = bool(arguments.get("mirror_to_chat", True))

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
                content="Kill-switch active — refusing to speak.",
                is_error=True,
                metadata={"killed": True},
            )

        # Provider selection + consent gate
        provider = "openai"
        cloned_fallback = False
        if voice_id and os.environ.get("ELEVENLABS_API_KEY", "").strip():
            if await _consent_ok(voice_id, sess.user_id):
                provider = "elevenlabs"
            else:
                cloned_fallback = True
                logger.info(
                    "meeting_speak: voice_id=%s lacks consent — falling back to openai",
                    voice_id[:10],
                )

        # Hard 15s budget on synthesize so a slow TTS can't freeze the bot.
        try:
            pcm = await asyncio.wait_for(
                _synthesize(provider, text, voice=voice, voice_id=voice_id),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            pcm = b""
            logger.warning("meeting_speak: TTS synthesis timed out (15s)")
        spoke_ok = False
        if pcm:
            # Publish in chunked blocks with periodic kill-switch checks so
            # a late "bot leave" can interrupt an in-flight utterance rather
            # than forcing the user to listen to the bot finish a paragraph.
            # Chunk size = ~1s of audio at 16kHz mono s16le = 32_000 bytes.
            chunk = 32_000
            total = len(pcm)
            pos = 0
            try:
                while pos < total:
                    if await sessmod.is_killed(meeting_id):
                        logger.info(
                            "meeting_speak: kill detected mid-playback at %d/%d bytes",
                            pos,
                            total,
                        )
                        break
                    block = pcm[pos : pos + chunk]
                    await sess.adapter.publish_audio(block, sample_rate=16_000)
                    pos += chunk
                spoke_ok = pos > 0
            except Exception as e:
                logger.debug("publish_audio failed: %s", e)

        if mirror:
            try:
                await sess.adapter.post_chat(text)
            except Exception as e:
                logger.debug("post_chat mirror failed: %s", e)

        await sessmod.append_decision(
            meeting_id,
            "answer",
            f"Bot spoke: {text[:140]}",
            detail={
                "provider": provider,
                "voice": voice,
                "voice_id": voice_id[:10] if voice_id else "",
                "tts_ok": spoke_ok,
                "mirror": mirror,
                "cloned_fallback": cloned_fallback,
            },
        )
        return ToolResult(
            content=f"ok: spoken={spoke_ok}, provider={provider}"
            + (", cloned_fallback=true" if cloned_fallback else ""),
            metadata={
                "spoken": spoke_ok,
                "chars": len(text),
                "provider": provider,
                "cloned_fallback": cloned_fallback,
            },
        )


async def _consent_ok(voice_id: str, user_id: str) -> bool:
    """If the voice_id belongs to a user with recorded consent, OK."""
    if not voice_id or not user_id:
        return True  # no user attachment → implicitly OK
    cache_key = (user_id, voice_id)
    now = time.time()
    hit = _CONSENT_CACHE.get(cache_key)
    if hit and now - hit[0] < _CONSENT_CACHE_TTL:
        return hit[1]

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        return False
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text as sql_text
    except ImportError:
        return False
    try:
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        async with engine.begin() as conn:
            r = await conn.execute(
                sql_text(
                    "SELECT voice_id, voice_consent_at FROM users "
                    "WHERE id = CAST(:uid AS uuid)"
                ),
                {"uid": user_id},
            )
            row = r.first()
        await engine.dispose()
    except Exception:
        return False
    if not row:
        ok = True  # voice_id doesn't belong to this user; not a personal clone
    else:
        stored_voice, consent_ts = row
        if not stored_voice or stored_voice != voice_id:
            ok = True  # different voice than the user owns — not personal
        else:
            ok = consent_ts is not None
    # Cap cache size to keep memory bounded in a long-running pod
    if len(_CONSENT_CACHE) > 500:
        oldest = min(_CONSENT_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _CONSENT_CACHE.pop(oldest, None)
    _CONSENT_CACHE[cache_key] = (now, ok)
    return ok


async def _synthesize(
    provider: str,
    text: str,
    *,
    voice: str,
    voice_id: str,
) -> bytes:
    if not text:
        return b""
    cache_key = hashlib.sha256(
        f"{provider}|{voice}|{voice_id}|{text}".encode()
    ).hexdigest()
    now = time.time()
    for k in [k for k, (t, _) in _TTS_CACHE.items() if now - t > _TTS_CACHE_TTL]:
        _TTS_CACHE.pop(k, None)
    if cache_key in _TTS_CACHE:
        return _TTS_CACHE[cache_key][1]

    pcm = b""
    if provider == "elevenlabs" and voice_id:
        from engine.tools._voice_clone import elevenlabs_tts_pcm

        pcm = await elevenlabs_tts_pcm(
            voice_id=voice_id,
            text=text,
            sample_rate=16_000,
        )
    if not pcm:
        # openai path (used as primary and as fallback)
        pcm = await _openai_tts_pcm(text, voice=voice)

    if pcm:
        if len(_TTS_CACHE) >= _TTS_CACHE_MAX:
            oldest = min(_TTS_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _TTS_CACHE.pop(oldest, None)
        _TTS_CACHE[cache_key] = (now, pcm)
    return pcm


async def _openai_tts_pcm(text: str, *, voice: str) -> bytes:
    client = _get_tts_openai_client()
    if client is None:
        return b""
    try:
        resp = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="pcm",
        )
        raw = await resp.aread() if hasattr(resp, "aread") else resp.read()
    except Exception as e:
        logger.warning("OpenAI TTS failed: %s", e)
        return b""
    return _resample_s16(raw, rate_in=24_000, rate_out=16_000)


def _resample_s16(pcm: bytes, *, rate_in: int, rate_out: int) -> bytes:
    if rate_in == rate_out or not pcm:
        return pcm
    import array

    samples = array.array("h")
    samples.frombytes(pcm)
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
    return out.tobytes()
