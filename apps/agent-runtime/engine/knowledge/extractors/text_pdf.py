"""Cheap text-only extraction. Returns one block per non-empty page.

If `extract_text()` produces less than 50 chars per page on average,
mark the document low-quality so `dispatch` falls back to vision."""

from __future__ import annotations

from .base import ExtractedBlock


class TextPdfExtractor:
    method = "text_pdf"

    async def extract(
        self, *, blob_path: str, content_type: str | None = None
    ) -> list[ExtractedBlock]:
        try:
            from pypdf import PdfReader
        except Exception:
            return []
        blocks: list[ExtractedBlock] = []
        try:
            reader = PdfReader(blob_path)
        except Exception:
            return []
        offset = 0
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if not text:
                continue
            blocks.append(
                ExtractedBlock(
                    text=text,
                    page=i,
                    paragraph_idx=0,
                    char_offset_start=offset,
                    char_offset_end=offset + len(text),
                    metadata={"extractor": self.method},
                )
            )
            offset += len(text) + 1
        return blocks
