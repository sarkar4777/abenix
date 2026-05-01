"""Voice cloning via ElevenLabs — TTS with the user's cloned voice."""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"


async def elevenlabs_tts_pcm(
    *, voice_id: str, text: str, api_key: Optional[str] = None,
    model: str = "eleven_turbo_v2_5", sample_rate: int = 16_000,
) -> bytes:
    """Return raw 16-bit mono PCM at `sample_rate`. Empty bytes on any failure."""
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not (api_key and voice_id and text):
        return b""

    # ElevenLabs supports pcm_16000, pcm_22050, pcm_24000, pcm_44100
    supported = {16_000, 22_050, 24_000, 44_100}
    sr = sample_rate if sample_rate in supported else 16_000
    url = f"{_ELEVENLABS_BASE}/text-to-speech/{voice_id}?output_format=pcm_{sr}"
    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                url, json=payload,
                headers={"xi-api-key": api_key, "accept": "audio/pcm"},
            )
            r.raise_for_status()
            return r.content or b""
    except Exception as e:
        logger.warning("elevenlabs TTS failed: %s", e)
        return b""


async def elevenlabs_clone_voice(
    *, name: str, reference_audio_bytes: bytes, reference_filename: str = "voice.wav",
    description: str = "", labels: Optional[dict] = None,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Upload a reference clip, return new voice_id. Returns None on failure."""
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key or not reference_audio_bytes:
        return None
    try:
        files = {
            "files": (reference_filename, reference_audio_bytes, "audio/wav"),
        }
        data = {"name": name, "description": description}
        if labels:
            import json as _json
            data["labels"] = _json.dumps(labels)
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{_ELEVENLABS_BASE}/voices/add",
                headers={"xi-api-key": api_key},
                files=files, data=data,
            )
            r.raise_for_status()
            body = r.json()
            return body.get("voice_id")
    except httpx.HTTPStatusError as e:
        detail: dict = {}
        try:
            detail = e.response.json().get("detail") or {}
        except Exception:
            detail = {"message": e.response.text[:200] if e.response is not None else str(e)}
        logger.warning("elevenlabs clone failed: %s — response: %s", e, detail)
        # Re-raise with the parsed payload so the router can format the response
        raise RuntimeError(json.dumps({"provider_error": detail, "status_code": e.response.status_code if e.response is not None else 500}))
    except Exception as e:
        logger.warning("elevenlabs clone failed: %s", e)
        return None


async def elevenlabs_delete_voice(*, voice_id: str, api_key: Optional[str] = None) -> bool:
    api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not (api_key and voice_id):
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.delete(
                f"{_ELEVENLABS_BASE}/voices/{voice_id}",
                headers={"xi-api-key": api_key},
            )
            return r.status_code in (200, 204)
    except Exception:
        return False
