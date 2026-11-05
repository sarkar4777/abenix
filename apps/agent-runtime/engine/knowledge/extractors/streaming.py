"""Extract a file as a stream of blocks, so a large file stays out of memory."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

logger = logging.getLogger(__name__)

TEXT_WINDOW = 256 * 1024
PDF_SAMPLE_PAGES = 20
SCANNED_PAGE_CHARS = 50
# pypdf keeps parsed objects until the reader goes away
PDF_READER_PAGES = 200
XLSX_ROWS_PER_BLOCK = 500
TEXT_EXTENSIONS = ("txt", "md", "json", "csv", "tsv", "log")
STREAMED_OFFICE = ("xlsx", "pptx", "html", "htm", "msg")


@dataclass
class StreamInfo:
    method: str = "unknown"
    quality: float = 0.0
    ocr_pages: int = 0


# text, page, and whether it continues the previous block with no break
Block = tuple[str, int | None, bool]


def iter_text(path: str) -> Iterator[Block]:
    first = True
    with open(path, encoding="utf-8", errors="replace") as fh:
        while piece := fh.read(TEXT_WINDOW):
            yield piece, 1, not first
            first = False


class _HtmlText(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "head"}
    _BREAK = {"p", "div", "li", "br", "tr", "section", "article", "table", "ul", "ol"}
    _BREAK |= {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BREAK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.out.append(data)


def iter_html(path: str) -> Iterator[Block]:
    parser = _HtmlText()
    first = True
    with open(path, encoding="utf-8", errors="replace") as fh:
        while piece := fh.read(TEXT_WINDOW):
            parser.feed(piece)
            text = "".join(parser.out)
            parser.out.clear()
            if text.strip():
                yield text, None, not first
                first = False
    parser.close()
    text = "".join(parser.out)
    if text.strip():
        yield text, None, not first


def iter_xlsx(path: str) -> Iterator[Block]:
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for number, sheet in enumerate(book.worksheets, start=1):
            rows: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(cells):
                    rows.append("\t".join(cells))
                if len(rows) >= XLSX_ROWS_PER_BLOCK:
                    yield "\n".join(rows) + "\n", number, False
                    rows = []
            if rows:
                yield "\n".join(rows) + "\n", number, False
    finally:
        book.close()


def iter_pptx(path: str) -> Iterator[Block]:
    from pptx import Presentation

    deck = Presentation(path)
    for number, slide in enumerate(deck.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text:
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    parts.append("\t".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text
            if notes.strip():
                parts.append(notes)
        text = "\n".join(p for p in parts if p.strip())
        if text:
            yield text, number, False


def _msg_stream(ole, prop: str) -> str:
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp1252")):
        name = f"__substg1.0_{prop}{suffix}"
        if ole.exists(name):
            raw = ole.openstream(name).read()
            return raw.decode(encoding, errors="replace").rstrip("\x00 ").strip()
    return ""


def iter_msg(path: str) -> Iterator[Block]:
    import olefile

    ole = olefile.OleFileIO(path)
    try:
        header = [
            ("Subject", _msg_stream(ole, "0037")),
            ("From", _msg_stream(ole, "0C1A") or _msg_stream(ole, "5D01")),
            ("To", _msg_stream(ole, "0E04")),
            ("Cc", _msg_stream(ole, "0E03")),
        ]
        lines = [f"{k}: {v}" for k, v in header if v]
        body = _msg_stream(ole, "1000")
    finally:
        ole.close()
    text = "\n".join(lines) + ("\n\n" + body if body else "")
    if text.strip():
        yield text, None, False


def iter_pdf(path: str, info: StreamInfo) -> Iterator[Block] | None:
    """None when the first pages hold too little text, a scan needs the vision path."""
    from pypdf import PdfReader

    reader = PdfReader(path)
    total = len(reader.pages)
    sample: list[Block] = []
    for i in range(min(PDF_SAMPLE_PAGES, total)):
        text = _page_text(reader, i)
        if text:
            sample.append((text, i + 1, False))
    pages = max(1, min(PDF_SAMPLE_PAGES, total))
    average = sum(len(b[0]) for b in sample) / pages
    if average < 50:
        return None
    info.quality = min(1.0, average / 1500)
    sample = _with_scanned_pages(path, sample, min(PDF_SAMPLE_PAGES, total), info)

    def rest() -> Iterator[Block]:
        yield from sample
        current = reader
        for i in range(PDF_SAMPLE_PAGES, total):
            if (i - PDF_SAMPLE_PAGES) % PDF_READER_PAGES == 0:
                current = PdfReader(path)
            text = _page_text(current, i)
            if len(text) < SCANNED_PAGE_CHARS:
                text = _scanned_text(path, i + 1, info) or text
            if text:
                yield text, i + 1, False

    return rest()


def _with_scanned_pages(
    path: str, sample: list[Block], count: int, info: StreamInfo
) -> list[Block]:
    """A mostly text PDF can still hold scanned pages, read those too."""
    by_page = {b[1]: b for b in sample}
    out: list[Block] = []
    for page in range(1, count + 1):
        block = by_page.get(page)
        if block is None or len(block[0]) < SCANNED_PAGE_CHARS:
            text = _scanned_text(path, page, info)
            if text:
                block = (text, page, False)
        if block is not None:
            out.append(block)
    return out


def _scanned_text(path: str, page: int, info: StreamInfo) -> str:
    from .ocr import max_pages, read_page_sync

    if info.ocr_pages >= max_pages():
        return ""
    try:
        text = read_page_sync(path, page)
    except Exception:
        logger.exception("OCR failed on page %d of %s", page, path)
        return ""
    if text:
        info.ocr_pages += 1
        info.method = "text_pdf+ocr"
    return text


def _page_text(reader, index: int) -> str:
    try:
        return (reader.pages[index].extract_text() or "").strip()
    except Exception:
        return ""


_OFFICE = {
    "xlsx": ("xlsx", iter_xlsx),
    "pptx": ("pptx", iter_pptx),
    "html": ("html", iter_html),
    "htm": ("html", iter_html),
    "msg": ("msg", iter_msg),
}


def extension(path: str, file_type: str | None) -> str:
    hint = (file_type or "").lower().rsplit("/", 1)[-1].lstrip(".")
    return hint or Path(path).suffix.lower().lstrip(".")


def iter_document(
    path: str, file_type: str | None = None
) -> tuple[Iterator[Block], StreamInfo] | None:
    """A block stream and what produced it, or None when only the whole file path can read it."""
    ext = extension(path, file_type)
    info = StreamInfo()
    if ext in TEXT_EXTENSIONS or ext == "plain" or ext == "markdown":
        info.method, info.quality = "text_plain", 1.0
        return iter_text(path), info
    if ext in _OFFICE:
        name, fn = _OFFICE[ext]
        info.method, info.quality = name, 0.9
        return fn(path), info
    if ext == "pdf":
        info.method = "text_pdf"
        stream = iter_pdf(path, info)
        return (stream, info) if stream is not None else None
    return None


def office_blocks(path: str, ext: str) -> list[Block]:
    """Whole file form of the same readers, for callers that want a list."""
    entry = _OFFICE.get(ext)
    if entry is None:
        return []
    try:
        return list(entry[1](path))
    except ImportError as exc:
        logger.warning("%s reader is not installed: %s", ext, exc)
    except Exception:
        logger.exception("could not read %s", os.path.basename(path))
    return []
