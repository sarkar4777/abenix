from __future__ import annotations

from typing import Any

from engine.tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information. Returns a list of results "
        "with titles, URLs, and snippets."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        max_results = arguments.get("max_results", 5)

        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        try:
            from duckduckgo_search import DDGS

            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        }
                    )

            if not results:
                return ToolResult(content=f"No results found for: {query}")

            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   URL: {r['url']}")
                lines.append(f"   {r['snippet']}")
                lines.append("")

            return ToolResult(
                content="\n".join(lines),
                metadata={"result_count": len(results)},
            )
        except Exception as e:
            return ToolResult(content=f"Search failed: {str(e)}", is_error=True)
