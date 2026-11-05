from __future__ import annotations

from typing import Any

from engine.tools import _duckduckgo as duckduckgo
from engine.tools.base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    name = "web_search"
    risk_tier = "low"
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

        warnings = [
            "This searched DuckDuckGo, which returns fewer and older results than a "
            "keyed provider. tavily_search uses a key when one is configured."
        ]
        try:
            rows = await duckduckgo.search("text", query, max_results)
        except Exception as e:
            return ToolResult(
                content=f"DuckDuckGo search failed, so nothing was searched. {e}",
                is_error=True,
                metadata={"provider": "duckduckgo", "warnings": warnings},
            )

        if not rows:
            return ToolResult(
                content=f"No results found for {query}. {duckduckgo.EMPTY_NOTE}",
                metadata={
                    "provider": "duckduckgo",
                    "result_count": 0,
                    "warnings": warnings,
                },
            )

        lines = []
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. {r.get('title', '')}")
            lines.append(f"   URL: {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')}")
            lines.append("")

        return ToolResult(
            content="\n".join(lines),
            metadata={
                "provider": "duckduckgo",
                "backend": rows[0].get("backend"),
                "result_count": len(rows),
                "warnings": warnings,
            },
        )
