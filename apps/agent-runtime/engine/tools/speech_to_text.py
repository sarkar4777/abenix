"""Speech to Text Tool — transcribe audio using OpenAI Whisper API.

Supports: MP3, MP4, WAV, M4A, WebM. Max 25MB file size.
"""
from __future__ import annotations

import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class SpeechToTextTool(BaseTool):
    name = "speech_to_text"
    description = (
        "Transcribe audio files to text using OpenAI Whisper. "
        "Supports MP3, WAV, M4A, WebM. Returns transcription with timestamps."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "audio_url": {
                "type": "string",
                "description": "URL or file path to audio file",
            },
            "language": {
                "type": "string",
                "description": "Language code (e.g., 'en', 'es', 'fr'). Auto-detected if omitted.",
            },
        },
        "required": ["audio_url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        audio_url = arguments.get("audio_url", "")
        language = arguments.get("language")

        if not audio_url:
            return ToolResult(content="Error: audio_url is required", is_error=True)

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(content="Error: OPENAI_API_KEY required for speech-to-text", is_error=True)

        try:
            import httpx
            from pathlib import Path

            # Load audio file
            if audio_url.startswith(("http://", "https://")):
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(audio_url)
                    audio_data = resp.content
                    filename = audio_url.split("/")[-1].split("?")[0] or "audio.mp3"
            else:
                path = Path(audio_url)
                if not path.exists():
                    return ToolResult(content=f"Error: File not found: {audio_url}", is_error=True)
                audio_data = path.read_bytes()
                filename = path.name

            if len(audio_data) > 25 * 1024 * 1024:
                return ToolResult(content="Error: Audio file exceeds 25MB limit", is_error=True)

            # Call Whisper API
            async with httpx.AsyncClient(timeout=120) as client:
                files = {"file": (filename, audio_data)}
                data: dict[str, Any] = {"model": "whisper-1", "response_format": "verbose_json"}
                if language:
                    data["language"] = language

                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=files,
                    data=data,
                )

                if resp.status_code != 200:
                    return ToolResult(content=f"Whisper API error: {resp.text[:500]}", is_error=True)

                result = resp.json()
                return ToolResult(content=json.dumps({
                    "status": "success",
                    "text": result.get("text", ""),
                    "language": result.get("language", ""),
                    "duration_seconds": result.get("duration"),
                    "segments": result.get("segments", [])[:20],  # First 20 segments
                }))

        except ImportError:
            return ToolResult(content="Error: httpx not installed", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Speech-to-text error: {str(e)[:500]}", is_error=True)
