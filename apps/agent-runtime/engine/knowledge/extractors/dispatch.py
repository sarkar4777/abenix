"""Pick the right extractor for a file. Strategy:

  1. PDF → text_pdf for every page, then OCR for the pages with under
     50 characters. KB_OCR_MODE picks Tesseract or the vision model.
  2. DOCX / PPTX / XLSX / HTML / EPUB / RTF → office (unstructured).
  3. CSV / TSV / JSON / TXT / MD → plain UTF-8 read.
  4. PNG / JPG / TIFF → the same OCR choice, one image.
  5. Anything else → read as UTF-8 text.

DOCX falls back to python-docx when unstructured is not installed.

Returns (`blocks`, `method`, `quality_score`) where quality_score is
[0,1] indicating how confident we are that we got the full content.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ExtractedBlock

logger = logging.getLogger(__name__)


_MIME_EXT = {
    "pdf": "pdf",
    "vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "plain": "txt",
    "markdown": "md",
}


_ZIP_CONTAINERS = ("docx", "pptx", "xlsx", "odt", "epub")
_ARCHIVES = ("zip", "tar", "tgz", "gz", "bz2", "xz", "7z", "rar")


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


async def _read_docx(blob_path: str) -> list[ExtractedBlock]:
    try:
        from docx import Document
    except ImportError:
        return []
    try:
        doc = Document(blob_path)
    except Exception:
        logger.exception("python-docx could not open %s", blob_path)
        return []
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not text.strip():
        return []
    return [
        ExtractedBlock(
            text=text,
            paragraph_idx=0,
            char_offset_start=0,
            char_offset_end=len(text),
            metadata={"extractor": "docx"},
        )
    ]


def _pdf_page_count(blob_path: str) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(blob_path).pages)
    except Exception:
        return 0


async def _read_pdf(
    blob_path: str, content_type: str | None
) -> tuple[list[ExtractedBlock], str, float]:
    """Text where the PDF has it, OCR for only the pages that are scans."""
    from . import ocr
    from .text_pdf import TextPdfExtractor

    blocks = await TextPdfExtractor().extract(
        blob_path=blob_path, content_type=content_type
    )
    total = _pdf_page_count(blob_path)
    rich = {
        b.page
        for b in blocks
        if b.page is not None and len(b.text) >= ocr.SCANNED_PAGE_CHARS
    }
    scanned = [p for p in range(1, total + 1) if p not in rich]
    read, using = await ocr.read_pages(blob_path, scanned) if scanned else ([], None)
    if read:
        replaced = {b.page for b in read}
        blocks = sorted(
            [b for b in blocks if b.page not in replaced] + read,
            key=lambda b: b.page or 0,
        )
        _reindex(blocks)
    if not blocks:
        return [], "text_pdf", 0.0
    if not read:
        pages = max(1, total or max((b.page or 0) for b in blocks))
        average = sum(len(b.text) for b in blocks) / pages
        return blocks, "text_pdf", min(1.0, average / 1500)
    if len(read) == len(blocks):
        return blocks, "vision_pdf" if using == ocr.VISION else "ocr_pdf", 0.8
    return blocks, f"text_pdf+{'vision' if using == ocr.VISION else 'ocr'}", 0.8


def _reindex(blocks: list[ExtractedBlock]) -> None:
    offset = 0
    for b in blocks:
        b.char_offset_start, b.char_offset_end = offset, offset + len(b.text)
        offset += len(b.text) + 1


async def _read_image_file(
    blob_path: str, content_type: str | None
) -> tuple[list[ExtractedBlock], str]:
    from . import ocr

    using = ocr.engine()
    if using == ocr.TESSERACT:
        with open(blob_path, "rb") as fh:
            text = await ocr.read_image(fh.read(), 1, using)
        if text:
            return (
                [
                    ExtractedBlock(
                        text=text, page=1, metadata={"extractor": "ocr_tesseract"}
                    )
                ],
                "ocr_image",
            )
        return [], "ocr_image"
    if using == ocr.VISION:
        with open(blob_path, "rb") as fh:
            text = await ocr.read_image(fh.read(), 1, using)
        if text:
            return (
                [
                    ExtractedBlock(
                        text=text, page=1, metadata={"extractor": "ocr_vision"}
                    )
                ],
                "vision_image",
            )
    return [], "vision_image"


def _plain_office(blob_path: str, ext: str) -> list[ExtractedBlock]:
    from .streaming import office_blocks

    # office formats also work when unstructured is not in the image
    return [
        ExtractedBlock(text=t, page=p, metadata={"extractor": ext})
        for t, p, _continued in office_blocks(blob_path, ext)
    ]


async def extract_document(
    blob_path: str,
    content_type: str | None = None,
    file_type: str | None = None,
) -> tuple[list[ExtractedBlock], str, float]:
    """file_type (the stored extension) wins over the path suffix, which a temp download may lack."""
    hint = (file_type or "").lower().rsplit("/", 1)[-1].lstrip(".")
    ext = _MIME_EXT.get(hint, hint) or _ext(blob_path)
    blocks: list[ExtractedBlock] = []
    method = "unknown"
    quality = 0.0

    from engine.archive_guard import UnsafeArchive, check_zip

    if ext in _ARCHIVES:
        raise UnsafeArchive(
            "Archives are not ingested, unpack it and add the files inside."
        )
    if ext in _ZIP_CONTAINERS:
        check_zip(blob_path, "This document")

    if ext == "pdf":
        blocks, method, quality = await _read_pdf(blob_path, content_type)
    elif ext in ("docx", "pptx", "xlsx", "html", "htm", "epub", "rtf", "odt"):
        from .office import OfficeExtractor

        blocks = await OfficeExtractor().extract(
            blob_path=blob_path, content_type=content_type
        )
        method = "office"
        quality = 0.9 if blocks else 0.0
        if not blocks and ext == "docx":
            blocks = await _read_docx(blob_path)
            method = "docx"
            quality = 0.85 if blocks else 0.0
        if not blocks and ext in ("pptx", "xlsx", "html", "htm"):
            blocks = _plain_office(blob_path, ext)
            method = ext
            quality = 0.85 if blocks else 0.0
    elif ext == "msg":
        blocks = _plain_office(blob_path, ext)
        method = "msg"
        quality = 0.85 if blocks else 0.0
    elif ext in ("txt", "md", "json", "csv", "tsv", "log"):
        blocks = await _read_text(blob_path)
        method = "text_plain"
        quality = 1.0 if blocks else 0.0
    elif ext in ("png", "jpg", "jpeg", "tiff", "bmp"):
        blocks, method = await _read_image_file(blob_path, content_type)
        quality = 0.7 if blocks else 0.0
    else:
        blocks = await _read_text(blob_path)
        method = "text_plain"
        quality = 0.5 if blocks else 0.0

    return blocks, method, quality
