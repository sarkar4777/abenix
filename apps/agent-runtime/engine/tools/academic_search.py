from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx

from engine.tools.base import BaseTool, ToolResult

_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


class AcademicSearchTool(BaseTool):
    name = "academic_search"
    description = (
        "Search academic papers and research publications. "
        "Uses Semantic Scholar and arXiv APIs."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Research query",
            },
            "source": {
                "type": "string",
                "enum": ["semantic_scholar", "arxiv", "both"],
                "default": "both",
            },
            "year_from": {
                "type": "integer",
                "description": "Filter papers from this year",
            },
            "year_to": {
                "type": "integer",
                "description": "Filter papers to this year",
            },
            "max_results": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        if not query:
            return ToolResult(content="Error: query is required", is_error=True)

        source = arguments.get("source", "both")
        year_from = arguments.get("year_from")
        year_to = arguments.get("year_to")
        max_results = arguments.get("max_results", 10)

        all_papers: list[dict[str, Any]] = []
        errors: list[str] = []

        if source in ("semantic_scholar", "both"):
            try:
                papers = await self._semantic_scholar(
                    query, max_results, year_from, year_to
                )
                all_papers.extend(papers)
            except Exception as e:
                errors.append(f"Semantic Scholar error: {e}")

        if source in ("arxiv", "both"):
            try:
                papers = await self._arxiv(query, max_results, year_from, year_to)
                all_papers.extend(papers)
            except Exception as e:
                errors.append(f"arXiv error: {e}")

        if not all_papers:
            msg = "No academic papers found."
            if errors:
                msg += " Errors: " + "; ".join(errors)
            return ToolResult(content=msg, is_error=bool(errors))

        # Sort by citation count descending (papers without counts go last)
        all_papers.sort(key=lambda p: p.get("citations", 0) or 0, reverse=True)

        # Limit total results when querying both sources
        if source == "both":
            all_papers = all_papers[:max_results]

        lines = self._format_papers(all_papers)
        if errors:
            lines.append("---")
            lines.append("Warnings: " + "; ".join(errors))

        return ToolResult(
            content="\n".join(lines),
            metadata={"result_count": len(all_papers)},
        )

    @staticmethod
    async def _semantic_scholar(
        query: str,
        max_results: int,
        year_from: int | None,
        year_to: int | None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "query": query,
            "fields": "title,abstract,year,citationCount,authors,url,venue",
            "limit": max_results,
        }
        if year_from and year_to:
            params["year"] = f"{year_from}-{year_to}"
        elif year_from:
            params["year"] = f"{year_from}-"
        elif year_to:
            params["year"] = f"-{year_to}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        papers: list[dict[str, Any]] = []
        for item in data.get("data", []):
            authors = [a.get("name", "") for a in item.get("authors", [])]
            papers.append(
                {
                    "title": item.get("title", ""),
                    "abstract": item.get("abstract", "") or "",
                    "year": item.get("year"),
                    "citations": item.get("citationCount", 0),
                    "authors": authors,
                    "url": item.get("url", ""),
                    "venue": item.get("venue", ""),
                    "source": "Semantic Scholar",
                }
            )
        return papers

    @staticmethod
    async def _arxiv(
        query: str,
        max_results: int,
        year_from: int | None,
        year_to: int | None,
    ) -> list[dict[str, Any]]:
        encoded_query = quote(query)
        url = (
            f"http://export.arxiv.org/api/query"
            f"?search_query=all:{encoded_query}"
            f"&max_results={max_results}"
            f"&sortBy=relevance&sortOrder=descending"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        papers: list[dict[str, Any]] = []

        for entry in root.findall("atom:entry", _ARXIV_NS):
            title_el = entry.find("atom:title", _ARXIV_NS)
            summary_el = entry.find("atom:summary", _ARXIV_NS)
            published_el = entry.find("atom:published", _ARXIV_NS)
            link_el = entry.find("atom:id", _ARXIV_NS)

            title = (title_el.text or "").strip() if title_el is not None else ""
            abstract = (summary_el.text or "").strip() if summary_el is not None else ""
            published = (published_el.text or "") if published_el is not None else ""
            paper_url = (link_el.text or "") if link_el is not None else ""

            year = None
            if published and len(published) >= 4:
                try:
                    year = int(published[:4])
                except ValueError:
                    pass

            # Apply year filter
            if year_from and year and year < year_from:
                continue
            if year_to and year and year > year_to:
                continue

            authors = []
            for author_el in entry.findall("atom:author", _ARXIV_NS):
                name_el = author_el.find("atom:name", _ARXIV_NS)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text.strip())

            papers.append(
                {
                    "title": title,
                    "abstract": abstract[:500] if abstract else "",
                    "year": year,
                    "citations": None,
                    "authors": authors,
                    "url": paper_url,
                    "venue": "arXiv",
                    "source": "arXiv",
                }
            )

        return papers

    @staticmethod
    def _format_papers(papers: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for i, p in enumerate(papers, 1):
            author_str = ", ".join(p["authors"][:3])
            if len(p["authors"]) > 3:
                author_str += " et al."

            lines.append(f"{i}. {p['title']}")
            lines.append(f"   Authors: {author_str}")
            if p.get("year"):
                lines.append(f"   Year: {p['year']}")
            if p.get("venue"):
                lines.append(f"   Venue: {p['venue']}")
            if p.get("citations") is not None:
                lines.append(f"   Citations: {p['citations']}")
            lines.append(f"   URL: {p['url']}")
            lines.append(f"   Source: {p['source']}")
            if p.get("abstract"):
                abstract = p["abstract"]
                if len(abstract) > 200:
                    abstract = abstract[:200] + "..."
                lines.append(f"   Abstract: {abstract}")
            lines.append("")

        return lines
