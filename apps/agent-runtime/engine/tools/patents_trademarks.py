"""USPTO PatentsView — US patent search (free, no key)."""

from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_BASE = "https://search.patentsview.org/api/v1/patent"


class PatentsTrademarksTool(BaseTool):
    name = "patents_trademarks"
    description = (
        "Search granted US patents via USPTO PatentsView. Free, no API key. "
        "Filter by query text, assignee, inventor, date range. Returns "
        "title, abstract, grant date, assignee, and patent number."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text search of patent titles + abstracts.",
            },
            "assignee": {
                "type": "string",
                "description": "Optional company / organization name filter.",
            },
            "inventor": {
                "type": "string",
                "description": "Optional inventor name filter.",
            },
            "from_date": {
                "type": "string",
                "description": "Earliest grant date YYYY-MM-DD.",
            },
            "to_date": {
                "type": "string",
                "description": "Latest grant date YYYY-MM-DD.",
            },
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        assignee = (arguments.get("assignee") or "").strip()
        inventor = (arguments.get("inventor") or "").strip()
        from_date = arguments.get("from_date")
        to_date = arguments.get("to_date")
        limit = int(arguments.get("limit", 10))

        if not (query or assignee or inventor):
            return ToolResult(
                content="At least one of query, assignee, inventor is required",
                is_error=True,
            )

        # Build the PatentsView 'q' object (boolean AND of present filters).
        clauses: list[dict[str, Any]] = []
        if query:
            clauses.append({"_text_any": {"patent_title": query}})
        if assignee:
            clauses.append({"_contains": {"assignees.assignee_organization": assignee}})
        if inventor:
            clauses.append({"_contains": {"inventors.inventor_name_last": inventor}})
        if from_date:
            clauses.append({"_gte": {"patent_date": from_date}})
        if to_date:
            clauses.append({"_lte": {"patent_date": to_date}})
        q = clauses[0] if len(clauses) == 1 else {"_and": clauses}

        body = {
            "q": q,
            "f": [
                "patent_id",
                "patent_title",
                "patent_date",
                "patent_abstract",
                "assignees.assignee_organization",
                "inventors.inventor_name_first",
                "inventors.inventor_name_last",
            ],
            "s": [{"patent_date": "desc"}],
            "o": {"size": limit},
        }
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post(_BASE, json=body)
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"PatentsView HTTP {e.response.status_code}: {e.response.text[:200]}",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(content=f"PatentsView error: {e}", is_error=True)

        patents = data.get("patents") or []
        if not patents:
            return ToolResult(content="No matching patents.")

        lines = [
            f"USPTO patents — {len(patents)} result{'s' if len(patents) != 1 else ''}:"
        ]
        compact = []
        for p in patents:
            assignees = (
                ", ".join(
                    a.get("assignee_organization", "")
                    for a in (p.get("assignees") or [])
                    if a.get("assignee_organization")
                )
                or "(unassigned)"
            )
            inventors = ", ".join(
                f"{i.get('inventor_name_first', '')} {i.get('inventor_name_last', '')}".strip()
                for i in (p.get("inventors") or [])
            )
            abstract = (p.get("patent_abstract") or "").strip().replace("\n", " ")
            lines.append("")
            lines.append(f"  US{p.get('patent_id')} — granted {p.get('patent_date')}")
            lines.append(f"    Title: {p.get('patent_title')}")
            lines.append(f"    Assignee: {assignees}")
            if inventors:
                lines.append(f"    Inventors: {inventors[:200]}")
            if abstract:
                lines.append(f"    Abstract: {abstract[:300]}")
            compact.append(
                {
                    "patent_id": p.get("patent_id"),
                    "title": p.get("patent_title"),
                    "date": p.get("patent_date"),
                    "assignees": assignees,
                    "abstract": abstract[:500],
                }
            )
        return ToolResult(content="\n".join(lines), metadata={"patents": compact})
