"""Read scanned pages, with Tesseract on the worker or the vision model. KB_OCR_MODE picks."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import shutil

from .base import ExtractedBlock

logger = logging.getLogger(__name__)

SCANNED_PAGE_CHARS = 50
RENDER_DPI = 200
TESSERACT = "tesseract"
VISION = "vision"


def max_pages() -> int:
    return int(os.environ.get("KB_OCR_MAX_PAGES", "2000"))


def tesseract_available() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def _vision_available() -> bool:
    from . import vision_pdf

    return vision_pdf._provider() != "none"


def engine() -> str | None:
    """off, tesseract, vision, or auto which prefers the local and free one."""
    mode = os.environ.get("KB_OCR_MODE", "auto").strip().lower()
    if mode == "off":
        return None
    if mode == TESSERACT:
        return TESSERACT if tesseract_available() else None
    if mode == VISION:
        return VISION if _vision_available() else None
    if tesseract_available():
        return TESSERACT
    return VISION if _vision_available() else None


def why_unavailable() -> str:
    mode = os.environ.get("KB_OCR_MODE", "auto")
    return (
        f"Scanned pages cannot be read with KB_OCR_MODE={mode}. Install Tesseract on "
        "the worker or set a vision model key."
    )


def render_page(path: str, page_no: int, dpi: int = RENDER_DPI) -> bytes | None:
    """One page as PNG, None for a page with nothing drawn on it."""
    try:
        import pymupdf
    except ImportError:
        logger.warning("PyMuPDF is not installed, scanned pages cannot be read")
        return None
    with pymupdf.open(path) as doc:
        page = doc[page_no - 1]
        if not page.get_images() and not page.get_drawings():
            return None
        return page.get_pixmap(dpi=dpi).tobytes("png")


def _tesseract_text(image: bytes) -> str:
    import pytesseract
    from PIL import Image

    lang = os.environ.get("KB_OCR_LANGUAGES", "eng")
    return pytesseract.image_to_string(Image.open(io.BytesIO(image)), lang=lang)


async def read_image(image: bytes, page_no: int = 1, using: str | None = None) -> str:
    using = using or engine()
    if using == TESSERACT:
        return (await asyncio.to_thread(_tesseract_text, image)).strip()
    if using == VISION:
        from . import vision_pdf

        encoded = base64.b64encode(image).decode("ascii")
        return (await vision_pdf._read_page(encoded, page_no)).strip()
    return ""


async def read_pages(
    path: str, pages: list[int]
) -> tuple[list[ExtractedBlock], str | None]:
    """Blocks for the pages that yielded text, one page in memory at a time."""
    using = engine()
    if using is None:
        logger.warning(why_unavailable())
        return [], None
    limit = max_pages()
    if len(pages) > limit:
        logger.warning("OCR stops at %d of %d scanned pages", limit, len(pages))
    blocks: list[ExtractedBlock] = []
    for page_no in pages[:limit]:
        png = await asyncio.to_thread(render_page, path, page_no)
        if not png:
            continue
        text = await read_image(png, page_no, using)
        if text:
            blocks.append(
                ExtractedBlock(
                    text=text, page=page_no, metadata={"extractor": f"ocr_{using}"}
                )
            )
    return blocks, using


def read_page_sync(path: str, page_no: int) -> str:
    """For the streaming reader, which walks a PDF outside any event loop."""
    using = engine()
    if using is None:
        return ""
    png = render_page(path, page_no)
    if not png:
        return ""
    if using == TESSERACT:
        return _tesseract_text(png).strip()
    return asyncio.run(read_image(png, page_no, using))
