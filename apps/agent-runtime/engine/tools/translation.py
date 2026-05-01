"""Text translation via DeepL (preferred) with LibreTranslate fallback."""

from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


class TranslationTool(BaseTool):
    name = "translation"
    description = (
        "Translate text to a target language. Uses DeepL when DEEPL_API_KEY "
        "is set (best quality), falls back to LibreTranslate via "
        "LIBRETRANSLATE_URL. With no provider configured it returns an "
        "empty translation and a clear 'skipped' status — the caller "
        "agent should treat that as a recoverable condition."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to translate."},
            "target_lang": {
                "type": "string",
                "description": "ISO 639-1 code: 'en', 'de', 'fr', 'es', 'ja', 'zh', etc.",
            },
            "source_lang": {
                "type": "string",
                "description": "Optional source language (auto-detect if omitted).",
            },
            "formality": {
                "type": "string",
                "enum": ["default", "more", "less", "prefer_more", "prefer_less"],
                "description": "DeepL only — formality hint.",
            },
        },
        "required": ["text", "target_lang"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        target = (arguments.get("target_lang") or "").lower().strip()
        source = (arguments.get("source_lang") or "").lower().strip() or None
        formality = arguments.get("formality")
        if not text or not target:
            return ToolResult(
                content="text and target_lang are required", is_error=True
            )

        deepl_key = os.environ.get("DEEPL_API_KEY", "").strip()
        libre_url = os.environ.get("LIBRETRANSLATE_URL", "").strip()
        libre_key = os.environ.get("LIBRETRANSLATE_API_KEY", "").strip()

        try:
            if deepl_key:
                # DeepL Free uses api-free.deepl.com; Pro uses api.deepl.com.
                # The :fx suffix on free keys is the canonical signal.
                base = (
                    "https://api-free.deepl.com"
                    if deepl_key.endswith(":fx")
                    else "https://api.deepl.com"
                )
                payload: dict[str, Any] = {
                    "text": [text],
                    "target_lang": target.upper(),
                }
                if source:
                    payload["source_lang"] = source.upper()
                if formality:
                    payload["formality"] = formality
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.post(
                        f"{base}/v2/translate",
                        headers={"Authorization": f"DeepL-Auth-Key {deepl_key}"},
                        data=payload,
                    )
                    r.raise_for_status()
                    out = r.json().get("translations") or []
                if not out:
                    return ToolResult(
                        content="DeepL returned no translation.", is_error=True
                    )
                tr = out[0]
                return ToolResult(
                    content=tr.get("text", ""),
                    metadata={
                        "provider": "deepl",
                        "detected_source": tr.get("detected_source_language"),
                        "target_lang": target,
                    },
                )

            if libre_url:
                payload = {
                    "q": text,
                    "target": target,
                    "source": source or "auto",
                    "format": "text",
                }
                if libre_key:
                    payload["api_key"] = libre_key
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.post(f"{libre_url.rstrip('/')}/translate", json=payload)
                    r.raise_for_status()
                    data = r.json()
                return ToolResult(
                    content=data.get("translatedText", ""),
                    metadata={
                        "provider": "libretranslate",
                        "target_lang": target,
                        "detected_source": (data.get("detectedLanguage") or {}).get(
                            "language"
                        ),
                    },
                )

            return ToolResult(
                content=text,
                metadata={
                    "provider": "none",
                    "skipped": True,
                    "reason": "No translation provider configured. Set DEEPL_API_KEY or LIBRETRANSLATE_URL.",
                    "target_lang": target,
                },
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"Translation HTTP {e.response.status_code}: {e.response.text[:200]}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"Translation error: {e}", is_error=True)
