from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, ToolResult


class NewsFeedTool(BaseTool):
    name = "news_feed"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "MEDIASTACK_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="MediaStack",
            signup_url="https://mediastack.com/signup",
        ),
        ConfigField(
            "NEWS_API_KEY",
            label="API key",
            kind="secret",
            required=False,
            group="NewsAPI",
            signup_url="https://newsapi.org/register",
        ),
    )

    @classmethod
    async def config_test(
        cls, values: dict[str, str], key: str | None = None
    ) -> tuple[bool, str] | None:
        from engine.tools._config_probe import probe

        v = values.get(key or "", "")
        if key == "NEWS_API_KEY":
            if len(v) > 30 and "-" in v:
                return await probe(
                    "GET",
                    "https://eventregistry.org/api/v1/article/getArticles",
                    params={"apiKey": v, "keyword": "ping", "articlesCount": 1},
                    accepted="newsapi.ai accepted the key",
                )
            return await probe(
                "GET",
                "https://newsapi.org/v2/top-headlines",
                params={"apiKey": v, "country": "us", "pageSize": 1},
                accepted="newsapi.org accepted the key",
            )
        if key == "MEDIASTACK_API_KEY":
            return await probe(
                "GET",
                "http://api.mediastack.com/v1/news",
                params={"access_key": v, "limit": 1},
                accepted="MediaStack accepted the key",
            )
        return None

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
        # A rejected key used to be swallowed by a bare except and the user was
        # told there was no news. A 401 or 403 is a configuration problem and
        # is reported as one. Other failures still fall through.
        rejected: list[str] = []
        errors: list[str] = []

        news_api_key = self.cfg("NEWS_API_KEY")
        if news_api_key:
            # newsapi.ai keys are UUIDs, newsapi.org keys are short hex
            is_event_registry = len(news_api_key) > 30 and "-" in news_api_key
            order = ("ai", "org") if is_event_registry else ("org", "ai")
            for fmt in order:
                try:
                    if fmt == "ai":
                        return await self._newsapi_ai(
                            news_api_key, query, language, max_results
                        )
                    return await self._newsapi(
                        news_api_key,
                        query,
                        category,
                        language,
                        from_date,
                        max_results,
                        sort_by,
                    )
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    if code in (401, 403):
                        rejected.append(f"NewsAPI rejected NEWS_API_KEY (HTTP {code})")
                        break
                    errors.append(f"NewsAPI {fmt}: HTTP {code}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"NewsAPI {fmt}: {exc.__class__.__name__}")

        mediastack_key = self.cfg("MEDIASTACK_API_KEY")
        if mediastack_key:
            try:
                return await self._mediastack(
                    mediastack_key, query, category, language, max_results
                )
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in (401, 403):
                    rejected.append(
                        f"MediaStack rejected MEDIASTACK_API_KEY (HTTP {code})"
                    )
                else:
                    errors.append(f"MediaStack: HTTP {code}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"MediaStack: {exc.__class__.__name__}")

        if rejected:
            return ToolResult(
                content=(
                    "; ".join(rejected)
                    + ". The key is present but the provider does not accept it. "
                    "An admin can update it under Admin -> Tool Configuration."
                ),
                is_error=True,
                metadata={
                    "rejected": rejected,
                    "needs_configuration": (
                        "NEWS_API_KEY"
                        if rejected[0].startswith("NewsAPI")
                        else "MEDIASTACK_API_KEY"
                    ),
                },
            )

        # Fallback to DuckDuckGo news, and say why
        result = await self._ddg_news(query, max_results)
        if not (news_api_key or mediastack_key):
            why = "No news provider key is configured (NEWS_API_KEY or MEDIASTACK_API_KEY)"
        else:
            why = "The configured news providers failed: " + "; ".join(errors)
        if isinstance(result.metadata, dict):
            result.metadata.setdefault("warnings", []).append(
                why + ", used DuckDuckGo news instead"
            )
        return result

    @staticmethod
    def _format_articles(articles: list[dict[str, str]], provider: str) -> ToolResult:
        if not articles:
            return ToolResult(content=f"No news found (provider: {provider})")
        lines = [f"[Provider: {provider}]", ""]
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. {a.get('title', 'Untitled')}")
            if a.get("source"):
                lines.append(f"   Source: {a['source']} | {a.get('published', '')}")
            if a.get("url"):
                lines.append(f"   URL: {a['url']}")
            if a.get("description"):
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
                    "source": (
                        a.get("source", {}).get("title", "")
                        if isinstance(a.get("source"), dict)
                        else str(a.get("source", ""))
                    ),
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
                "http://api.mediastack.com/v1/news",
                params=params,
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
                    articles.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "source": r.get("source", ""),
                            "published": r.get("date", ""),
                            "description": r.get("body", ""),
                        }
                    )

            if not articles:
                # Empty result from the fallback provider after all
                # paid providers also missed = real backend issue, not
                # a successful "no matches". Surface as is_error so the
                # /executions row records a failure_code.
                return ToolResult(
                    content=(
                        f"news_feed could not retrieve any articles for '{query}'. "
                        "All configured news providers returned empty or failed. "
                        "Check NEWS_API_KEY / MEDIASTACK_API_KEY in env, or the "
                        "provider quota."
                    ),
                    is_error=True,
                )

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
        articles: list[dict[str, str]],
        provider: str,
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
