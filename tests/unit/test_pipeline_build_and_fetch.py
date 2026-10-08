"""AI-built web pipelines: step references, price extraction, plain fetch errors."""

from __future__ import annotations

import asyncio
import socket

import aiohttp
import pytest

from engine.pipeline import _extract_field, _resolve_templates
from engine.tools.http_client import HttpClientTool, plain_error
from engine.tools.regex_extractor import RegexExtractorTool

HTTP_OUT = {"status": 200, "headers": {}, "body": "<p>£12.50</p>"}


def test_response_on_http_client_reads_the_body():
    assert _extract_field(HTTP_OUT, "response") == "<p>£12.50</p>"


def test_response_on_document_parser_reads_the_text():
    assert _extract_field({"text": "hello", "char_count": 5}, "response") == "hello"


def test_response_path_reads_fields_of_a_dict_output():
    stats = {"count": 3, "average": 4.5}
    assert _extract_field(stats, "response.average") == 4.5
    assert _extract_field(stats, "response") == stats


def test_response_path_reads_into_a_json_body():
    out = {"status": 200, "body": {"prices": [1, 2]}}
    assert _extract_field(out, "response.prices") == [1, 2]


def test_real_response_field_still_wins():
    assert _extract_field({"response": "hi", "text": "no"}, "response") == "hi"


def test_plain_string_output_answers_response():
    assert _extract_field("just text", "response") == "just text"
    assert _extract_field("just text", "other") is None


def test_unknown_field_is_still_not_available():
    out = _resolve_templates({"x": "{{a.nope}}"}, {"a": HTTP_OUT})
    assert out["x"] == "[not available]"


def test_template_with_response_reaches_the_page():
    out = _resolve_templates({"text": "{{fetch.response}}"}, {"fetch": HTTP_OUT})
    assert out["text"] == "<p>£12.50</p>"


def test_currency_preset_reads_any_symbol_and_keeps_repeats():
    page = "<p>£51.77</p><p>£51.77</p><p>$3.10</p><p>€1,200.50</p>"
    out = RegexExtractorTool()._extract_preset(page, {"preset": "currency"})
    got = out["extracted"]["currency"]
    assert got["count"] == 4
    assert got["values"] == ["£51.77", "£51.77", "$3.10", "€1,200.50"]
    assert len(got["unique"]) == 3


def test_dns_failure_reads_plainly():
    key = aiohttp.client_reqrep.ConnectionKey(
        "nowhere.invalid", 443, True, True, None, None, None
    )
    e = aiohttp.ClientConnectorError(key, socket.gaierror(-2, "Name not known"))
    msg = plain_error(e, "nowhere.invalid", 15)
    assert msg.startswith("This server cannot find nowhere.invalid")
    assert "gaierror" not in msg and "ssl:default" not in msg


def test_refused_connection_reads_plainly():
    key = aiohttp.client_reqrep.ConnectionKey(
        "books.example", 443, True, True, None, None, None
    )
    e = aiohttp.ClientConnectorError(key, ConnectionRefusedError(111, "refused"))
    assert plain_error(e, "books.example", 15).startswith(
        "This server cannot reach books.example"
    )


def test_timeout_reads_plainly():
    assert (
        plain_error(asyncio.TimeoutError(), "slow.example", 15)
        == "slow.example did not answer within 15 seconds."
    )


@pytest.mark.asyncio
async def test_tool_returns_the_plain_message(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def request(self, *a, **k):
            raise asyncio.TimeoutError()

    monkeypatch.setattr(aiohttp, "ClientSession", Boom)
    res = await HttpClientTool().execute(
        {"url": "https://slow.example/x", "timeout": 5}
    )
    assert res.is_error
    assert res.content == "slow.example did not answer within 5 seconds."


def test_builder_guide_reads_as_the_model_should_write_it():
    from app.routers import ai_builder

    guide = ai_builder.PIPELINE_FEATURES
    assert "{{{{" not in guide
    assert "{{fetch.body}}" in guide
    assert '{"id": "trends"' in guide
    assert "fetch_prices.response" not in guide


def _node(status, output, tool):
    from engine.pipeline import NodeResult

    return NodeResult(node_id="n", status=status, output=output, tool_name=tool)


EXPORT = {
    "status": "success",
    "file_path": "/data/exports/r.json",
    "download_url": "/api/files/export/r.json",
    "filename": "r.json",
}


def test_run_ending_in_a_file_still_answers_with_the_summary():
    from engine.pipeline import _answer_with_saved_file

    results = {
        "fetch": _node("completed", {"status": 200, "body": "<html>"}, "http_client"),
        "summary": _node(
            "completed", {"response": "19 prices, average 34.29."}, "llm_call"
        ),
        "save": _node("completed", EXPORT, "data_exporter"),
    }
    out = _answer_with_saved_file(EXPORT, ["fetch", "summary", "save"], results)
    assert out["response"].startswith("19 prices, average 34.29.")
    assert out["response"].endswith("Saved r.json: /api/files/export/r.json")
    assert out["download_url"] == EXPORT["download_url"]


def test_run_ending_in_a_file_with_no_written_text_is_unchanged():
    from engine.pipeline import _answer_with_saved_file

    results = {
        "fetch": _node("completed", {"status": 200, "body": "<html>"}, "http_client"),
        "save": _node("completed", EXPORT, "data_exporter"),
    }
    assert _answer_with_saved_file(EXPORT, ["fetch", "save"], results) == EXPORT


def test_ordinary_final_output_is_untouched():
    from engine.pipeline import _answer_with_saved_file

    assert _answer_with_saved_file({"response": "hi"}, ["a"], {}) == {"response": "hi"}
    assert _answer_with_saved_file({"total": 3}, ["a"], {}) == {"total": 3}
