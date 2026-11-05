"""Scanned pages reach OCR behind KB_OCR_MODE, and only the pages that need it."""

from __future__ import annotations

import pytest

fitz = pytest.importorskip("fitz")

from engine.knowledge.extractors import (
    dispatch,
    ocr,
    streaming,
    vision_pdf,
)  # noqa: E402


def _pdf(tmp_path, pages) -> str:
    """pages is a list of str for real text, None for a scan with text only in the image."""
    doc = fitz.open()
    for content in pages:
        page = doc.new_page()
        if content is not None:
            page.insert_text((72, 72), content)
        else:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 100), False)
            pix.clear_with(200)
            page.insert_image(fitz.Rect(72, 72, 272, 172), pixmap=pix)
    path = tmp_path / "doc.pdf"
    doc.save(str(path))
    return str(path)


TEXT = "Plain text on this page is long enough to count as a real page of content."


@pytest.fixture
def fake_tesseract(monkeypatch):
    seen = []

    def read(image: bytes) -> str:
        seen.append(image)
        return f"scanned words {len(seen)}"

    monkeypatch.setattr(ocr, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr, "_tesseract_text", read)
    monkeypatch.setenv("KB_OCR_MODE", "tesseract")
    return seen


@pytest.mark.asyncio
async def test_a_wholly_scanned_pdf_is_read_with_ocr(tmp_path, fake_tesseract):
    path = _pdf(tmp_path, [None, None])
    blocks, method, quality = await dispatch.extract_document(path, file_type="pdf")
    assert [b.page for b in blocks] == [1, 2]
    assert method == "ocr_pdf" and quality == 0.8
    assert blocks[0].text == "scanned words 1"
    assert fake_tesseract[0].startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_only_the_scanned_pages_of_a_mixed_pdf_go_to_ocr(
    tmp_path, fake_tesseract
):
    path = _pdf(tmp_path, [TEXT, None, TEXT])
    blocks, method, _q = await dispatch.extract_document(path, file_type="pdf")
    assert len(fake_tesseract) == 1
    assert [b.page for b in blocks] == [1, 2, 3]
    assert blocks[1].text.startswith("scanned") and method == "text_pdf+ocr"
    assert blocks[0].char_offset_end < blocks[1].char_offset_start


@pytest.mark.asyncio
async def test_a_blank_page_costs_nothing(tmp_path, fake_tesseract):
    path = _pdf(tmp_path, [TEXT, ""])
    blocks, method, _q = await dispatch.extract_document(path, file_type="pdf")
    assert fake_tesseract == [] and method == "text_pdf" and len(blocks) == 1


@pytest.mark.asyncio
async def test_the_setting_turns_it_off(tmp_path, fake_tesseract, monkeypatch):
    monkeypatch.setenv("KB_OCR_MODE", "off")
    path = _pdf(tmp_path, [None])
    blocks, method, quality = await dispatch.extract_document(path, file_type="pdf")
    assert blocks == [] and fake_tesseract == [] and quality == 0.0
    assert method == "text_pdf"


@pytest.mark.asyncio
async def test_the_vision_setting_uses_the_vision_model(tmp_path, monkeypatch):
    seen = []

    async def read_page(image_b64: str, page_no: int) -> str:
        seen.append(page_no)
        return "vision words"

    monkeypatch.setattr(vision_pdf, "_provider", lambda: "gemini")
    monkeypatch.setattr(vision_pdf, "_read_page", read_page)
    monkeypatch.setenv("KB_OCR_MODE", "vision")
    path = _pdf(tmp_path, [None, TEXT])
    blocks, method, _q = await dispatch.extract_document(path, file_type="pdf")
    assert seen == [1] and method == "text_pdf+vision"
    assert [b.text for b in blocks][0] == "vision words"


def test_auto_prefers_the_free_local_engine(monkeypatch):
    monkeypatch.delenv("KB_OCR_MODE", raising=False)
    monkeypatch.setattr(vision_pdf, "_provider", lambda: "gemini")
    monkeypatch.setattr(ocr, "tesseract_available", lambda: True)
    assert ocr.engine() == ocr.TESSERACT
    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    assert ocr.engine() == ocr.VISION
    monkeypatch.setattr(vision_pdf, "_provider", lambda: "none")
    assert ocr.engine() is None and "KB_OCR_MODE" in ocr.why_unavailable()


def test_the_streaming_reader_also_reads_a_scan_inside_a_text_pdf(
    tmp_path, fake_tesseract
):
    path = _pdf(tmp_path, [TEXT] * 3 + [None] + [TEXT] * 20 + [None])
    info = streaming.StreamInfo()
    stream = streaming.iter_pdf(path, info)
    blocks = list(stream)
    assert {b[1] for b in blocks} == set(range(1, 26))
    assert len(fake_tesseract) == 2 and info.method == "text_pdf+ocr"
    assert any(b[0].startswith("scanned") and b[1] == 25 for b in blocks)


def test_ocr_stops_at_the_page_cap(tmp_path, fake_tesseract, monkeypatch):
    monkeypatch.setenv("KB_OCR_MAX_PAGES", "1")
    path = _pdf(tmp_path, [TEXT * 3] * 3 + [None, None])
    blocks = list(streaming.iter_pdf(path, streaming.StreamInfo()))
    assert len(fake_tesseract) == 1 and len(blocks) == 4


def test_the_worker_image_declares_what_extraction_needs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "apps" / "worker"
    project = (root / "pyproject.toml").read_text()
    docker = (root / "Dockerfile").read_text()
    for needed in ("PyMuPDF", "pytesseract", "unstructured[", "neo4j"):
        assert needed in project
    assert "tesseract-ocr" in docker and "libmagic1" in docker
