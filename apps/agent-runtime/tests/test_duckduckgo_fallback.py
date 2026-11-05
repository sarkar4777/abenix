"""The keyless search tools go through ddgs, off the event loop, and tell empty apart from broken."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from ddgs.base import BaseSearchEngine
from ddgs.ddgs import DDGS
from ddgs.exceptions import DDGSException

from engine.tools import _duckduckgo as duckduckgo
from engine.tools.news_feed import NewsFeedTool
from engine.tools.tavily_search import TavilySearchTool
from engine.tools.web_search import WebSearchTool

ROOT = Path(__file__).resolve().parents[3]


def _install(monkeypatch, answers, otherwise=()):
    """answers maps an engine name to rows or an exception, otherwise covers the rest."""
    calls: list[dict] = []
    real_search = DDGS._search_sync

    def recording(self, category, query, *args, **kwargs):
        calls.append(
            {
                "kind": category,
                "backend": kwargs.get("backend"),
                "thread": threading.current_thread(),
            }
        )
        return real_search(self, category, query, *args, **kwargs)

    def engine_search(self, query, **_kw):
        answer = answers.get(self.name, otherwise)
        if isinstance(answer, Exception):
            raise answer
        return [self.result_type(**row) for row in answer]

    monkeypatch.setattr(DDGS, "_search_sync", recording)
    monkeypatch.setattr(BaseSearchEngine, "search", engine_search)
    return calls


TEXT_ROW = {"title": "Paris", "href": "https://p.example", "body": "capital"}
NEWS_ROW = {
    "title": "Launch",
    "url": "https://n.example",
    "source": "Wire",
    "date": "2026-11-05T00:00:00Z",
    "body": "story",
}
BROKEN = DDGSException("https://html.duckduckgo.com/html 403 Ratelimit")


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for key in (
        "TAVILY_API_KEY",
        "BRAVE_SEARCH_API_KEY",
        "SERPAPI_API_KEY",
        "SERPER_API_KEY",
        "NEWS_API_KEY",
        "MEDIASTACK_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("tool_cls", [WebSearchTool, TavilySearchTool])
async def test_text_results_carry_the_fallback_warning(monkeypatch, tool_cls):
    calls = _install(monkeypatch, {"duckduckgo": [TEXT_ROW]})
    result = await tool_cls().execute({"query": "capital of France"})
    assert not result.is_error
    assert "Paris" in result.content and "https://p.example" in result.content
    assert result.metadata["provider"] == "duckduckgo"
    assert result.metadata["backend"] == "duckduckgo"
    assert result.metadata["result_count"] == 1
    assert "DuckDuckGo" in result.metadata["warnings"][0]
    assert [c["backend"] for c in calls] == ["duckduckgo"]


async def test_news_results_carry_the_fallback_warning(monkeypatch):
    _install(monkeypatch, {"duckduckgo": [NEWS_ROW]})
    result = await NewsFeedTool().execute({"query": "launch"})
    assert not result.is_error
    assert "Launch" in result.content and "Wire" in result.content
    assert "DuckDuckGo news" in result.metadata["warnings"][0]


async def test_the_blocking_client_runs_off_the_event_loop(monkeypatch):
    calls = _install(monkeypatch, {"duckduckgo": [TEXT_ROW]})
    await WebSearchTool().execute({"query": "q"})
    assert calls[0]["thread"] is not threading.current_thread()


@pytest.mark.parametrize("tool_cls", [WebSearchTool, TavilySearchTool, NewsFeedTool])
async def test_no_results_is_an_answer_and_not_an_error(monkeypatch, tool_cls):
    calls = _install(monkeypatch, {})
    result = await tool_cls().execute({"query": "zzqx"})
    assert not result.is_error
    assert "No " in result.content and "found" in result.content
    assert result.metadata["result_count"] == 0
    assert result.metadata["warnings"]
    kind = "news" if tool_cls is NewsFeedTool else "text"
    assert tuple(c["backend"] for c in calls) == duckduckgo.BACKENDS[kind]


@pytest.mark.parametrize("tool_cls", [WebSearchTool, TavilySearchTool, NewsFeedTool])
async def test_a_broken_provider_is_an_error_that_says_why(monkeypatch, tool_cls):
    _install(monkeypatch, {}, otherwise=BROKEN)
    result = await tool_cls().execute({"query": "q"})
    assert result.is_error
    assert "DuckDuckGo" in result.content and "Ratelimit" in result.content


async def test_a_failing_backend_retries_on_the_alternate(monkeypatch):
    calls = _install(monkeypatch, {"duckduckgo": BROKEN, "yahoo": [TEXT_ROW]})
    result = await WebSearchTool().execute({"query": "q"})
    assert not result.is_error and "Paris" in result.content
    assert result.metadata["backend"] == "yahoo"
    assert [c["backend"] for c in calls] == ["duckduckgo", "yahoo"]


async def test_one_empty_answer_among_broken_backends_is_not_an_error(monkeypatch):
    _install(monkeypatch, {"duckduckgo": BROKEN, "brave": BROKEN})
    result = await WebSearchTool().execute({"query": "q"})
    assert not result.is_error and result.metadata["result_count"] == 0


def test_the_real_package_says_empty_the_way_the_tools_expect(monkeypatch):
    _install(monkeypatch, {})
    with pytest.raises(DDGSException) as err:
        DDGS().text("q", backend="duckduckgo")
    assert duckduckgo._is_empty_answer(err.value)


async def test_a_missing_package_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "ddgs", None)
    result = await WebSearchTool().execute({"query": "q"})
    assert result.is_error and "ddgs package is not installed" in result.content


@pytest.mark.parametrize(
    "path",
    ["requirements.txt", "apps/agent-runtime/requirements.txt"],
)
def test_requirements_name_the_renamed_package(path):
    text = (ROOT / path).read_text()
    assert "ddgs>=" in text
    assert "duckduckgo-search" not in text
    assert "duckduckgo_search" not in text
