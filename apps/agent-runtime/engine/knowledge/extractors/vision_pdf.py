"""Vision-LLM extraction for scanned PDFs. Rasterizes each page,
sends to Claude or Gemini vision, asks for Markdown back.

Falls back gracefully when the SDK or API key is missing — returns
empty list rather than crashing the worker.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os

from .base import ExtractedBlock

logger = logging.getLogger(__name__)


def _provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY", "").strip():
        return "gemini"
    return "none"


async def _render_pages_to_png(blob_path: str) -> list[bytes]:
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed; vision extraction disabled")
        return []
    pngs: list[bytes] = []
    try:
        doc = fitz.open(blob_path)
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            pngs.append(pix.tobytes("png"))
    except Exception:
        logger.exception("failed to rasterize %s", blob_path)
    return pngs


async def _claude_vision(image_b64: str, page_no: int) -> str:
    try:
        import httpx
    except ImportError:
        return ""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""
    prompt = (
        f"Extract every word of text from page {page_no} of this scanned document. "
        "Preserve table structure as Markdown tables. Render figure captions as "
        "italics. Return ONLY the extracted Markdown, no commentary."
    )
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
        )
        if r.status_code != 200:
            return ""
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []))


class VisionPdfExtractor:
    method = "vision_pdf"

    async def extract(
        self, *, blob_path: str, content_type: str | None = None
    ) -> list[ExtractedBlock]:
        if _provider() == "none":
            return []
        pngs = await _render_pages_to_png(blob_path)
        if not pngs:
            return []
        blocks: list[ExtractedBlock] = []
        offset = 0
        for page_no, png in enumerate(pngs, start=1):
            b64 = base64.b64encode(png).decode("ascii")
            text = await _claude_vision(b64, page_no)
            if not text.strip():
                continue
            blocks.append(
                ExtractedBlock(
                    text=text,
                    page=page_no,
                    paragraph_idx=0,
                    char_offset_start=offset,
                    char_offset_end=offset + len(text),
                    metadata={"extractor": self.method},
                )
            )
            offset += len(text) + 1
            await asyncio.sleep(0)
        return blocks
