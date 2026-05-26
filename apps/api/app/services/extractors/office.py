"""Office formats — DOCX, PPTX, XLSX, HTML, EPUB, RTF. One adapter
class but it delegates to `unstructured.io` if available."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ExtractedBlock

logger = logging.getLogger(__name__)


class OfficeExtractor:
    method = "office"

    async def extract(
        self, *, blob_path: str, content_type: str | None = None
    ) -> list[ExtractedBlock]:
        try:
            from unstructured.partition.auto import partition
        except ImportError:
            logger.info("unstructured not installed; office extractor disabled")
            return []
        ext = Path(blob_path).suffix.lower().lstrip(".")
        blocks: list[ExtractedBlock] = []
        try:
            elements = partition(filename=blob_path)
        except Exception:
            logger.exception("unstructured partition failed for %s", blob_path)
            return []
        offset = 0
        for i, el in enumerate(elements):
            text = str(el).strip()
            if not text:
                continue
            md = getattr(el, "metadata", None)
            page = getattr(md, "page_number", None) if md is not None else None
            blocks.append(
                ExtractedBlock(
                    text=text,
                    block_type=type(el).__name__,
                    page=page,
                    paragraph_idx=i,
                    char_offset_start=offset,
                    char_offset_end=offset + len(text),
                    metadata={"extractor": self.method, "ext": ext},
                )
            )
            offset += len(text) + 1
        return blocks
