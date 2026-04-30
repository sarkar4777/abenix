from __future__ import annotations

import os
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

# Provider configuration: name -> (env var for API key, base URL)
_PROVIDERS = [
    ("tavily", "TAVILY_API_KEY", "https://api.tavily.com/search"),
    ("brave", "BRAVE_SEARCH_API_KEY", "https://api.search.brave.com/res/v1/web/search"),
    ("serpapi", "SERPAPI_API_KEY", "https://serpapi.com/search"),
    ("serper", "SERPER_API_KEY", "https://google.serper.dev/search"),
]


class TavilySearchTool(BaseTool):
    name = "tavily_search"
    description = (
        "Advanced web search with AI-generated answers. "
        "Supports Tavily, Brave, SerpAPI, and Serper providers."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (1-6 words optimal)",
            },
            "max_results": {"type": "integer", "default": 5},
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "default": "basic",
            },
            "topic": {
                "type": "string",
                "enum": ["general", "news", "finance"],
                "default": "general",
            },
            "time_range": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": "Optional time filter",
            },
            "include_answer": {
                "type": "boolean",
                "default": True,
                "description": "Include AI-generated answer (Tavily only)",
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        max_results = arguments.get("max_results", 5)
        search_depth = arguments.get("search_depth", "basic")
        topic = arguments.get("topic", "general")
        time_range = arguments.get("time_range")
        include_answer = arguments.get("include_answer", True)

        # Determine provider order: preferred provider first, then fallback chain
        preferred = os.environ.get("SEARCH_PROVIDER", "tavily").lower()
        ordered = self._build_provider_order(preferred)

        for provider_name, env_key, url in ordered:
            api_key = os.environ.get(env_key, "")
            if not api_key:
                continue
            try:
                return await self._call_provider(
                    provider_name, url, api_key,
                    query=query,
                    max_results=max_results,
                    search_depth=search_depth,
                    topic=topic,
                    time_range=time_range,
                    include_answer=include_answer,
                )
            except Exception:
                continue

        # Final fallback: DuckDuckGo (no API key needed)
        return await self._ddg_fallback(query, max_results)

    @staticmethod
    def _build_provider_order(preferred: str) -> list[tuple[str, str, str]]:
        """Return provider list with the preferred one first."""
        ordered: list[tuple[str, str, str]] = []
        rest: list[tuple[str, str, str]] = []
        for entry in _PROVIDERS:
            if entry[0] == preferred:
                ordered.insert(0, entry)
            else:
                rest.append(entry)
        return ordered + rest

    async def _call_provider(
        self,
        provider: str,
        url: str,
        api_key: str,
        *,
        query: str,
        max_results: int,
        search_depth: str,
        topic: str,
        time_range: str | None,
        include_answer: bool,
    ) -> ToolResult:
        async with httpx.AsyncClient(timeout=30) as client:
            if provider == "tavily":
                return await self._tavily(
                    client, url, api_key, query, max_results,
                    search_depth, topic, time_range, include_answer,
                )
            if provider == "brave":
                return await self._brave(client, url, api_key, query, max_results)
            if provider == "serpapi":
                return await self._serpapi(client, url, api_key, query, max_results)
            if provider == "serper":
                return await self._serper(client, url, api_key, query, max_results)
        return ToolResult(content=f"Unknown provider: {provider}", is_error=True)

    async def _tavily(
        self,
        client: httpx.AsyncClient,
        url: str,
        api_key: str,
        query: str,
        max_results: int,
        search_depth: str,
        topic: str,
        time_range: str | None,
        include_answer: bool,
    ) -> ToolResult:
        payload: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "topic": topic,
            "include_answer": include_answer,
        }
        if time_range:
            payload["time_range"] = time_range

        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        answer = data.get("answer", "")

        return self._format_results(
            results=[
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
                for r in results
            ],
            answer=answer,
            provider="Tavily",
        )

    async def _brave(
        self, client: httpx.AsyncClient, url: str, api_key: str,
        query: str, max_results: int,
    ) -> ToolResult:
        resp = await client.get(
            url,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

        web = data.get("web", {}).get("results", [])
        return self._format_results(
            results=[
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
                for r in web
            ],
            provider="Brave",
        )

    async def _serpapi(
        self, client: httpx.AsyncClient, url: str, api_key: str,
        query: str, max_results: int,
    ) -> ToolResult:
        resp = await client.get(
            url,
            params={"q": query, "api_key": api_key, "num": max_results, "engine": "google"},
        )
        resp.raise_for_status()
        data = resp.json()

        organic = data.get("organic_results", [])
        return self._format_results(
            results=[
                {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                for r in organic
            ],
            provider="SerpAPI",
        )

    async def _serper(
        self, client: httpx.AsyncClient, url: str, api_key: str,
        query: str, max_results: int,
    ) -> ToolResult:
        resp = await client.post(
            url,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
        )
        resp.raise_for_status()
        data = resp.json()

        organic = data.get("organic", [])
        return self._format_results(
            results=[
                {"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
                for r in organic
            ],
            provider="Serper",
        )

    @staticmethod
    async def _ddg_fallback(query: str, max_results: int) -> ToolResult:
        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })

            if not results:
                return ToolResult(content=f"No results found for: {query}")

            lines = ["[Provider: DuckDuckGo (fallback)]", ""]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   URL: {r['url']}")
                lines.append(f"   {r['snippet']}")
                lines.append("")

            return ToolResult(
                content="\n".join(lines),
                metadata={"provider": "duckduckgo", "result_count": len(results)},
            )
        except Exception as e:
            return ToolResult(
                content=f"All search providers failed. DuckDuckGo error: {e}",
                is_error=True,
            )

    @staticmethod
    def _format_results(
        results: list[dict[str, str]],
        provider: str,
        answer: str = "",
    ) -> ToolResult:
        if not results and not answer:
            return ToolResult(content="No results found.")

        lines = [f"[Provider: {provider}]", ""]
        if answer:
            lines.append(f"AI Answer: {answer}")
            lines.append("")

        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            lines.append(f"   {r['snippet']}")
            lines.append("")

        return ToolResult(
            content="\n".join(lines),
            metadata={"provider": provider.lower(), "result_count": len(results)},
        )
