"""A Google key alone gives vision text, proven against a fake HTTP transport and not against Google."""

from __future__ import annotations

import base64
import json
import os
from unittest.mock import patch

import httpx
import pytest

from engine import claude_subscription as cs
from engine import credentials, gemini_vision
from engine.knowledge.extractors import vision_pdf
from engine.tools import kyc_met_pdf_extractor as kyc

IMAGE = base64.b64encode(b"png").decode()
OFF = cs.SubscriptionConfig(
    enabled=False, token="", default_model="claude-haiku-4-5", exclusive=False
)


def _fake_google(monkeypatch, status=200, body=None):
    seen: list[httpx.Request] = []
    answer = body or {
        "candidates": [
            {"content": {"parts": [{"text": "page "}, {"text": "text"}]}},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=answer)

    monkeypatch.setattr(gemini_vision, "_TRANSPORT", httpx.MockTransport(handler))
    return seen


def _assert_well_formed(request: httpx.Request, key: str) -> None:
    assert request.method == "POST"
    assert request.url.host == "generativelanguage.googleapis.com"
    assert request.url.path.endswith(f"/{gemini_vision.MODEL}:generateContent")
    assert request.headers["x-goog-api-key"] == key
    assert key not in str(request.url)
    parts = json.loads(request.content)["contents"][0]["parts"]
    assert parts[0]["inlineData"] == {"mimeType": "image/png", "data": IMAGE}
    assert parts[1]["text"]


@pytest.mark.parametrize("name", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
async def test_vision_pdf_reads_a_page_with_only_a_google_key(monkeypatch, name):
    seen = _fake_google(monkeypatch)
    with (
        patch.dict(os.environ, {name: "g-key"}, clear=True),
        patch.object(cs, "get_config", return_value=OFF),
    ):
        assert vision_pdf._provider() == "gemini"
        assert await vision_pdf._read_page(IMAGE, 1) == "page text"
    _assert_well_formed(seen[0], "g-key")


async def test_vision_pdf_extract_returns_blocks_with_only_a_google_key(monkeypatch):
    _fake_google(monkeypatch)

    async def one_page(_path):
        return [b"png"]

    monkeypatch.setattr(vision_pdf, "_render_pages_to_png", one_page)
    with (
        patch.dict(os.environ, {"GOOGLE_API_KEY": "g-key"}, clear=True),
        patch.object(cs, "get_config", return_value=OFF),
    ):
        blocks = await vision_pdf.VisionPdfExtractor().extract(blob_path="x.pdf")
    assert [b.text for b in blocks] == ["page text"]


async def test_kyc_reads_a_page_with_only_a_google_key(monkeypatch):
    seen = _fake_google(monkeypatch)
    keys = {"ANTHROPIC_API_KEY": "", "GOOGLE_API_KEY": "g-key"}
    with (
        patch.dict(os.environ, {}, clear=True),
        credentials.override(keys),
        patch.object(cs, "get_config", return_value=OFF),
    ):
        assert kyc._provider() == "gemini"
        assert await kyc._vision_extract(IMAGE, 1) == "page text"
    _assert_well_formed(seen[0], "g-key")


@pytest.mark.parametrize(
    "status,body",
    [
        (403, {"error": {"message": "key rejected"}}),
        (200, {"candidates": []}),
        (200, {"promptFeedback": {"blockReason": "SAFETY"}}),
    ],
)
async def test_a_refusal_gives_empty_text_so_the_text_fallback_runs(
    monkeypatch, status, body
):
    _fake_google(monkeypatch, status=status, body=body)
    assert await gemini_vision.vision_text(IMAGE, "read", "g-key") == ""


async def test_a_transport_failure_gives_empty_text(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("no route")

    monkeypatch.setattr(gemini_vision, "_TRANSPORT", httpx.MockTransport(handler))
    assert await gemini_vision.vision_text(IMAGE, "read", "g-key") == ""


async def test_no_key_makes_no_call(monkeypatch):
    seen = _fake_google(monkeypatch)
    assert await gemini_vision.vision_text(IMAGE, "read", "") == ""
    assert seen == []
