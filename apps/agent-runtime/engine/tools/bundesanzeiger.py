"""Bundesanzeiger publication-portal scraper for DE-incorporated entities.

The German federal publication portal (Bundesanzeiger) has no JSON API.
Its full-text search returns paginated HTML. This tool issues the public
search query and parses the result list for Jahresabschluss (annual
report) filings and Geschaeftsberichte. No mock data — empty result if
the portal returns nothing.

Source: https://www.bundesanzeiger.de
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)

BA_SEARCH_URL = "https://www.bundesanzeiger.de/pub/de/start"
USER_AGENT = "AgentForge filings-refresh contact@agentforge.local"
REQUEST_TIMEOUT = 30.0


PUB_DATE_RE = re.compile(r"\b(\d{2}\.\d{2}\.\d{4})\b")
FILING_TYPE_TOKENS = {
    "Jahresabschluss": "annual_accounts",
    "Konzernabschluss": "consolidated_accounts",
    "Geschäftsbericht": "annual_report",
    "Lagebericht": "management_report",
    "Halbjahresfinanzbericht": "interim_report",
}


def _to_iso(d: str) -> str | None:
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})$", d)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


class BundesanzeigerTool(BaseTool):
    name = "bundesanzeiger_filings"
    description = (
        "Search Bundesanzeiger for filings linked to a DE-incorporated "
        "counterparty. Returns the result-list of annual accounts and "
        "management reports with publication date + HTML detail-page link. "
        "No mock data — returns no_matches if the search yields nothing."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "legal_name": {"type": "string"},
            "max_results": {
                "type": "integer",
                "default": 25,
                "minimum": 1,
                "maximum": 100,
            },
        },
        "required": ["legal_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        legal_name = (arguments.get("legal_name") or "").strip()
        max_results = int(arguments.get("max_results") or 25)
        if not legal_name:
            return ToolResult(content="legal_name required", is_error=True)

        params = {"fulltextSearchInput": legal_name, "btnSearch.button": "Suchen"}
        url = f"{BA_SEARCH_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                r = await client.get(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                    },
                )
                r.raise_for_status()
                html = r.text
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps(
                    {"status": "fetch_error", "reason": str(e), "url": url}
                ),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        filings: list[dict[str, Any]] = []
        link_re = re.compile(
            r'<a[^>]+href="(?P<href>[^"]*)"[^>]*>(?P<text>(?:(?!</a>).)*)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in link_re.finditer(html):
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group("text"))).strip()
            href = m.group("href") or ""
            if not text or not href:
                continue
            ftype = None
            for token, label in FILING_TYPE_TOKENS.items():
                if token in text:
                    ftype = label
                    break
            if ftype is None:
                continue
            window = html[max(0, m.start() - 250) : m.end() + 250]
            date_m = PUB_DATE_RE.search(window)
            pub_date = _to_iso(date_m.group(1)) if date_m else None
            link = (
                href
                if href.startswith("http")
                else f"https://www.bundesanzeiger.de{href}"
            )
            filings.append(
                {
                    "filing_type": ftype,
                    "title": text,
                    "publication_date": pub_date,
                    "source_url": link,
                }
            )
            if len(filings) >= max_results:
                break

        if not filings:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "no_matches",
                        "reason": "Bundesanzeiger returned no filings for this entity",
                        "search_url": url,
                        "legal_name": legal_name,
                    }
                ),
                is_error=False,
                metadata={"status": "no_matches"},
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "legal_name": legal_name,
                    "filings": filings,
                    "search_url": url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            ),
            is_error=False,
            metadata={"status": "ok", "n_filings": len(filings)},
        )


__all__ = ["BundesanzeigerTool"]
