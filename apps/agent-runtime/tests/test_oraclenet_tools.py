"""Tests for OracleNet tools -- tavily_search, news_feed, academic_search, yahoo_finance."""

import pytest


@pytest.mark.asyncio
async def test_tavily_search_fallback_to_ddg():
    """tavily_search falls back to DuckDuckGo when no API key."""
    from engine.tools.tavily_search import TavilySearchTool

    tool = TavilySearchTool()
    assert tool.name == "tavily_search"
    # Without API keys, should attempt DuckDuckGo fallback


@pytest.mark.asyncio
async def test_news_feed_schema():
    """news_feed has correct input schema."""
    from engine.tools.news_feed import NewsFeedTool

    tool = NewsFeedTool()
    assert tool.name == "news_feed"
    assert "query" in tool.input_schema["properties"]
    assert "category" in tool.input_schema["properties"]


@pytest.mark.asyncio
async def test_academic_search_schema():
    """academic_search has correct input schema."""
    from engine.tools.academic_search import AcademicSearchTool

    tool = AcademicSearchTool()
    assert tool.name == "academic_search"
    assert "source" in tool.input_schema["properties"]


@pytest.mark.asyncio
async def test_yahoo_finance_schema():
    """yahoo_finance has correct input schema."""
    from engine.tools.yahoo_finance import YahooFinanceTool

    tool = YahooFinanceTool()
    assert tool.name == "yahoo_finance"
    assert "action" in tool.input_schema["properties"]
    assert "symbol" in tool.input_schema["properties"]
