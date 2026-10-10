"""LLM request bodies never reach the logs unless ABENIX_LOG_LLM_CONTENT is set."""

from __future__ import annotations

import logging

import pytest

from engine import log_redaction as lr

SECRET = "my card is 4111 1111 1111 1111 and the key is sk-live-abc"


@pytest.fixture(autouse=True)
def _no_opt_in(monkeypatch):
    monkeypatch.delenv(lr.OPT_IN_ENV, raising=False)


def _record(name, msg, *args):
    return logging.LogRecord(name, logging.DEBUG, __file__, 1, msg, args, None)


def _options():
    return {
        "method": "post",
        "url": "/v1/messages",
        "json_data": {
            "model": "claude-sonnet-4-5",
            "system": "You are a bank agent. " + SECRET,
            "messages": [
                {"role": "user", "content": SECRET},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "again " + SECRET},
            ],
            "tools": [{"name": "lookup_account", "input_schema": {}}],
        },
    }


def test_sdk_request_options_are_summarised():
    rec = _record("anthropic._base_client", "Request options: %s", _options())
    assert lr.LLMContentFilter().filter(rec)
    out = rec.getMessage()
    assert SECRET not in out and "bank agent" not in out
    assert "model=claude-sonnet-4-5" in out
    assert "messages=3" in out
    assert "tools=[lookup_account]" in out
    assert "est_tokens=" in out


def test_openai_shaped_tools_are_named():
    body = {
        "json_data": {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": SECRET}],
            "tools": [
                {"type": "function", "function": {"name": "search", "parameters": {}}}
            ],
        }
    }
    rec = _record("openai._base_client", "Request options: %s", body)
    lr.LLMContentFilter().filter(rec)
    assert SECRET not in rec.getMessage()
    assert "tools=[search]" in rec.getMessage()


def test_our_own_records_are_left_alone():
    rec = _record("engine.llm_router", "picked %s", {"messages": ["x"]})
    lr.LLMContentFilter().filter(rec)
    assert rec.msg == "picked %s"


def test_sdk_records_without_a_body_are_left_alone():
    rec = _record(
        "anthropic._base_client", "Sending HTTP Request: %s %s", "POST", "/v1"
    )
    lr.LLMContentFilter().filter(rec)
    assert rec.getMessage() == "Sending HTTP Request: POST /v1"


def test_opt_in_keeps_the_full_body(monkeypatch):
    monkeypatch.setenv(lr.OPT_IN_ENV, "1")
    rec = _record("anthropic._base_client", "Request options: %s", _options())
    lr.LLMContentFilter().filter(rec)
    assert SECRET in rec.getMessage()


def test_install_warns_when_opted_in(monkeypatch, caplog):
    monkeypatch.setenv(lr.OPT_IN_ENV, "true")
    with caplog.at_level(logging.WARNING, logger=lr.__name__):
        lr.install()
    assert any(lr.OPT_IN_ENV in r.getMessage() for r in caplog.records)


def test_install_is_quiet_by_default(caplog):
    with caplog.at_level(logging.WARNING, logger=lr.__name__):
        lr.install()
    assert not caplog.records


def test_real_anthropic_client_debug_log_is_redacted(caplog):
    anthropic = pytest.importorskip("anthropic")
    from anthropic._models import FinalRequestOptions

    lr.install()
    client = anthropic.Anthropic(api_key="sk-ant-test")
    opts = FinalRequestOptions.construct(
        method="post", url="/v1/messages", json_data=_options()["json_data"]
    )
    with caplog.at_level(logging.DEBUG, logger="anthropic"):
        client._build_request(opts)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "LLM request model=claude-sonnet-4-5 messages=3" in text
    assert SECRET not in text
