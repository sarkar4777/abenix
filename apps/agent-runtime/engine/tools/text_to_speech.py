"""Text to Speech Tool — generate audio from text using OpenAI TTS."""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class TextToSpeechTool(BaseTool):
    name = "text_to_speech"
    description = (
        "Generate speech audio from text using OpenAI TTS. "
        "Voices: alloy, echo, fable, onyx, nova, shimmer. "
        "Returns MP3 audio as base64 or saves to file."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to convert to speech (max 4096 chars)",
            },
            "voice": {
                "type": "string",
                "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                "default": "alloy",
            },
            "output_path": {
                "type": "string",
                "description": "File path to save audio (optional, returns base64 if omitted)",
            },
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        voice = arguments.get("voice", "alloy")
        output_path = arguments.get("output_path")

        if not text:
            return ToolResult(content="Error: text is required", is_error=True)
        if len(text) > 4096:
            text = text[:4096]

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return ToolResult(content="Error: OPENAI_API_KEY required for text-to-speech", is_error=True)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": "tts-1", "input": text, "voice": voice, "response_format": "mp3"},
                )

                if resp.status_code != 200:
                    return ToolResult(content=f"TTS API error: {resp.text[:500]}", is_error=True)

                audio_data = resp.content

                if output_path:
                    from pathlib import Path
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(audio_data)
                    return ToolResult(content=json.dumps({
                        "status": "success",
                        "output_path": output_path,
                        "size_bytes": len(audio_data),
                        "voice": voice,
                    }))
                else:
                    return ToolResult(content=json.dumps({
                        "status": "success",
                        "audio_base64": base64.b64encode(audio_data).decode()[:10000] + "...",
                        "size_bytes": len(audio_data),
                        "voice": voice,
                        "format": "mp3",
                    }))

        except ImportError:
            return ToolResult(content="Error: httpx not installed", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Text-to-speech error: {str(e)[:500]}", is_error=True)
