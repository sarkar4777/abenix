"""Read one page image with Gemini over its REST API."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"
_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_TRANSPORT: httpx.AsyncBaseTransport | None = None


async def vision_text(
    image_b64: str, prompt: str, api_key: str, timeout: float = 60.0
) -> str:
    """The page text, empty on any failure so callers can use their text fallback."""
    if not api_key:
        return ""
    body = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": "image/png", "data": image_b64}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {"maxOutputTokens": 4096, "temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=_TRANSPORT) as client:
            # the key goes in a header so it never lands in a logged URL
            resp = await client.post(
                f"{_BASE}/{MODEL}:generateContent",
                headers={"x-goog-api-key": api_key},
                json=body,
            )
    except httpx.HTTPError as exc:
        logger.warning("Gemini vision call failed %s", type(exc).__name__)
        return ""
    if resp.status_code != 200:
        logger.warning(
            "Gemini vision returned %s, %s", resp.status_code, resp.text[:200]
        )
        return ""
    try:
        candidates = resp.json().get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or []
    except (ValueError, AttributeError, IndexError):
        return ""
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
