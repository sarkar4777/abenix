from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


class NewsFeedTool(BaseTool):
    name = "news_feed"
    description = (
        "Search recent news articles from multiple providers. "
        "Use for current events, market news, and trend monitoring."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "News search query",
            },
            "category": {
                "type": "string",
                "enum": ["business", "technology", "science", "health", "general"],
                "default": "general",
            },
            "language": {"type": "string", "default": "en"},
            "from_date": {
                "type": "string",
                "description": "Start date (YYYY-MM-DD)",
            },
            "max_results": {"type": "integer", "default": 10},
            "sort_by": {
                "type": "string",
                "enum": ["relevancy", "popularity", "publishedAt"],
                "default": "relevancy",
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        category = arguments.get("category", "general")
        language = arguments.get("language", "en")
        from_date = arguments.get("from_date")
        max_results = arguments.get("max_results", 10)
        sort_by = arguments.get("sort_by", "relevancy")

        # Try NewsAPI.ai (Event Registry) first — uses the same NEWS_API_KEY env var
        news_api_key = os.environ.get("NEWS_API_KEY", "")
        if news_api_key:
            # Detect if it's a newsapi.ai key (UUID format) vs newsapi.org key (short hex)
            is_event_registry = len(news_api_key) > 30 and "-" in news_api_key
            try:
                if is_event_registry:
                    return await self._newsapi_ai(
                        news_api_key, query, language, max_results,
                    )
                else:
                    return await self._newsapi(
                        news_api_key, query, category, language,
                        from_date, max_results, sort_by,
                    )
            except Exception:
                # Try the other format as fallback
                try:
                    if is_event_registry:
                        return await self._newsapi(
                            news_api_key, query, category, language,
                            from_date, max_results, sort_by,
                        )
                    else:
                        return await self._newsapi_ai(
                            news_api_key, query, language, max_results,
                        )
                except Exception:
                    pass

        # Try MediaStack
        mediastack_key = os.environ.get("MEDIASTACK_API_KEY", "")
        if mediastack_key:
            try:
                return await self._mediastack(
                    mediastack_key, query, category, language, max_results,
                )
            except Exception:
                pass

        # Fallback to DuckDuckGo news
        return await self._ddg_news(query, max_results)

    @staticmethod
    def _format_articles(articles: list[dict[str, str]], provider: str) -> ToolResult:
        if not articles:
            return ToolResult(content=f"No news found (provider: {provider})")
        lines = [f"[Provider: {provider}]", ""]
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. {a.get('title', 'Untitled')}")
            if a.get('source'):
                lines.append(f"   Source: {a['source']} | {a.get('published', '')}")
            if a.get('url'):
                lines.append(f"   URL: {a['url']}")
            if a.get('description'):
                lines.append(f"   {a['description'][:300]}")
            lines.append("")
        return ToolResult(
            content="\n".join(lines),
            metadata={"provider": provider.lower(), "result_count": len(articles)},
        )

    async def _newsapi(
        self,
        api_key: str,
        query: str,
        category: str,
        language: str,
        from_date: str | None,
        max_results: int,
        sort_by: str,
    ) -> ToolResult:
        params: dict[str, Any] = {
            "q": query,
            "apiKey": api_key,
            "language": language,
            "sortBy": sort_by,
            "pageSize": max_results,
        }
        if from_date:
            params["from"] = from_date

        # Use /v2/everything for keyword searches; /v2/top-headlines for category
        if category != "general":
            url = "https://newsapi.org/v2/top-headlines"
            params["category"] = category
        else:
            url = "https://newsapi.org/v2/everything"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("articles", [])
        return self._format_articles(
            articles=[
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", {}).get("name", ""),
                    "published": a.get("publishedAt", ""),
                    "description": a.get("description", "") or "",
                }
                for a in articles
            ],
            provider="NewsAPI",
        )

    async def _newsapi_ai(
        self,
        api_key: str,
        query: str,
        language: str,
        max_results: int,
    ) -> ToolResult:
        """Event Registry API at newsapi.ai — uses UUID-format API keys."""
        params: dict[str, Any] = {
            "apiKey": api_key,
            "keyword": query,
            "lang": language[:2],  # "en" not "eng"
            "articlesCount": min(max_results, 50),
            "resultType": "articles",
            "articlesSortBy": "date",
            "includeArticleBody": "true",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://newsapi.ai/api/v1/article/getArticles",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("articles", {}).get("results", [])
        return self._format_articles(
            articles=[
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", {}).get("title", "") if isinstance(a.get("source"), dict) else str(a.get("source", "")),
                    "published": a.get("dateTime", a.get("date", "")),
                    "description": (a.get("body", "") or "")[:500],
                }
                for a in results
            ],
            provider="NewsAPI.ai (Event Registry)",
        )

    async def _mediastack(
        self,
        api_key: str,
        query: str,
        category: str,
        language: str,
        max_results: int,
    ) -> ToolResult:
        params: dict[str, Any] = {
            "access_key": api_key,
            "keywords": query,
            "languages": language,
            "limit": max_results,
        }
        if category != "general":
            params["categories"] = category

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "http://api.mediastack.com/v1/news", params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        articles = data.get("data", [])
        return self._format_articles(
            articles=[
                {
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "source": a.get("source", ""),
                    "published": a.get("published_at", ""),
                    "description": a.get("description", "") or "",
                }
                for a in articles
            ],
            provider="MediaStack",
        )

    @staticmethod
    async def _ddg_news(query: str, max_results: int) -> ToolResult:
        try:
            from duckduckgo_search import DDGS

            articles = []
            with DDGS() as ddgs:
                for r in ddgs.news(query, max_results=max_results):
                    articles.append({
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "source": r.get("source", ""),
                        "published": r.get("date", ""),
                        "description": r.get("body", ""),
                    })

            if not articles:
                return ToolResult(content=f"No news found for: {query}")

            lines = ["[Provider: DuckDuckGo News (fallback)]", ""]
            for i, a in enumerate(articles, 1):
                lines.append(f"{i}. {a['title']}")
                lines.append(f"   Source: {a['source']} | {a['published']}")
                lines.append(f"   URL: {a['url']}")
                lines.append(f"   {a['description']}")
                lines.append("")

            return ToolResult(
                content="\n".join(lines),
                metadata={"provider": "duckduckgo", "result_count": len(articles)},
            )
        except Exception as e:
            return ToolResult(
                content=f"All news providers failed. DuckDuckGo error: {e}",
                is_error=True,
            )

    @staticmethod
    def _format_articles(
        articles: list[dict[str, str]], provider: str,
    ) -> ToolResult:
        if not articles:
            return ToolResult(content="No news articles found.")

        lines = [f"[Provider: {provider}]", ""]
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. {a['title']}")
            lines.append(f"   Source: {a['source']} | {a['published']}")
            lines.append(f"   URL: {a['url']}")
            lines.append(f"   {a['description']}")
            lines.append("")

        return ToolResult(
            content="\n".join(lines),
            metadata={"provider": provider.lower(), "result_count": len(articles)},
        )
