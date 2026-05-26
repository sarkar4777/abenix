"""Pick the right extractor for a file. Strategy:

  1. PDF → try text_pdf first; if average chars/page < 50 fall back
     to vision_pdf (scanned doc heuristic).
  2. DOCX / PPTX / XLSX / HTML / EPUB / RTF → office (unstructured).
  3. CSV / TSV / JSON / TXT / MD → plain UTF-8 read.
  4. PNG / JPG / TIFF → vision_pdf single page.
  5. Audio (MP3 / WAV / M4A) → audio extractor (Whisper).

Returns (`blocks`, `method`, `quality_score`) where quality_score is
[0,1] indicating how confident we are that we got the full content.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ExtractedBlock

logger = logging.getLogger(__name__)


def _ext(blob_path: str) -> str:
    return Path(blob_path).suffix.lower().lstrip(".")


async def _read_text(blob_path: str) -> list[ExtractedBlock]:
    try:
        with open(blob_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:
        return []
    if not text.strip():
        return []
    return [
        ExtractedBlock(
            text=text,
            page=1,
            paragraph_idx=0,
            char_offset_start=0,
            char_offset_end=len(text),
            metadata={"extractor": "text_plain"},
        )
    ]


async def extract_document(
    blob_path: str, content_type: str | None = None
) -> tuple[list[ExtractedBlock], str, float]:
    ext = _ext(blob_path)
    blocks: list[ExtractedBlock] = []
    method = "unknown"
    quality = 0.0

    if ext == "pdf":
        from .text_pdf import TextPdfExtractor

        blocks = await TextPdfExtractor().extract(
            blob_path=blob_path, content_type=content_type
        )
        method = "text_pdf"
        if blocks:
            total_chars = sum(len(b.text) for b in blocks)
            pages = max(1, max((b.page or 0) for b in blocks))
            avg = total_chars / pages
            quality = min(1.0, avg / 1500)
            if avg < 50:
                from .vision_pdf import VisionPdfExtractor

                vision_blocks = await VisionPdfExtractor().extract(
                    blob_path=blob_path, content_type=content_type
                )
                if vision_blocks:
                    blocks = vision_blocks
                    method = "vision_pdf"
                    quality = 0.8
        else:
            from .vision_pdf import VisionPdfExtractor

            blocks = await VisionPdfExtractor().extract(
                blob_path=blob_path, content_type=content_type
            )
            method = "vision_pdf"
            quality = 0.8 if blocks else 0.0
    elif ext in ("docx", "pptx", "xlsx", "html", "htm", "epub", "rtf", "odt"):
        from .office import OfficeExtractor

        blocks = await OfficeExtractor().extract(
            blob_path=blob_path, content_type=content_type
        )
        method = "office"
        quality = 0.9 if blocks else 0.0
    elif ext in ("txt", "md", "json", "csv", "tsv", "log"):
        blocks = await _read_text(blob_path)
        method = "text_plain"
        quality = 1.0 if blocks else 0.0
    elif ext in ("png", "jpg", "jpeg", "tiff", "bmp"):
        from .vision_pdf import VisionPdfExtractor

        blocks = await VisionPdfExtractor().extract(
            blob_path=blob_path, content_type=content_type
        )
        method = "vision_image"
        quality = 0.7 if blocks else 0.0
    else:
        logger.warning("no extractor for ext=%s path=%s", ext, blob_path)

    return blocks, method, quality
