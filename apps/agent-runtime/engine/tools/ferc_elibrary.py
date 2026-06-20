"""FERC eLibrary search tool for counterparty permit refresh.

Hits FERC's public eLibrary "Quick Search" endpoint and parses the HTML
response for dockets that look like Market-Based Rate authority
(ER-prefix dockets, electric tariff form types). FERC publishes no JSON
API for eLibrary, but the search endpoint is stable and rate-limit-free.

Source: https://elibrary.ferc.gov/eLibrary/search
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, quote_plus

import httpx

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)

FERC_SEARCH_URL = "https://elibrary.ferc.gov/eLibrary/search"
FERC_DOCKET_URL = (
    "https://elibrary.ferc.gov/eLibrary/docketsheet?docket_number={docket}"
)
USER_AGENT = "AgentForge counterparty-refresh contact@agentforge.local"
REQUEST_TIMEOUT = 30.0


DOCKET_RE = re.compile(r"\b((?:ER|EL|ES|RM|RT|PR|QF|DI|DOE)\d{1,2}-\d+(?:-\d+)?)\b")
DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2}|0?[1-9]/[0-3]?\d/20\d{2})\b")


PERMIT_CLASSIFIER: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^ER\d{2}-"), "FERC_MBR"),
    (re.compile(r"^EL\d{2}-"), "FERC_ENFORCE"),
    (re.compile(r"^QF\d{2}-"), "FERC_QF"),
    (re.compile(r"^ES\d{2}-"), "FERC_SECURITIES"),
    (re.compile(r"^PR\d{2}-"), "FERC_PR"),
]


def _classify(docket: str) -> str:
    for pat, label in PERMIT_CLASSIFIER:
        if pat.match(docket):
            return label
    return "FERC_OTHER"


def _normalise_iso(s: str) -> str | None:
    if not s:
        return None
    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        mo, da, yr = m.groups()
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    return None


class FercElibraryTool(BaseTool):
    name = "ferc_elibrary"
    description = (
        "Search FERC eLibrary for filings linked to a counterparty name. "
        "Returns matching dockets (ER, EL, QF, ES, PR types) with filing "
        "dates and a source URL into the docket sheet. Classifies dockets "
        "into permit categories (MBR, enforcement, qualifying facility). "
        "No mock data — empty if FERC returns no matches. "
        "Source: https://elibrary.ferc.gov/eLibrary/search"
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
            "from_date": {
                "type": "string",
                "description": "ISO YYYY-MM-DD; default = 5y ago",
            },
        },
        "required": ["legal_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        legal_name = (arguments.get("legal_name") or "").strip()
        max_results = int(arguments.get("max_results") or 25)
        from_date = arguments.get("from_date") or f"{datetime.now().year - 5}-01-01"

        if not legal_name:
            return ToolResult(content="legal_name required", is_error=True)

        params = {
            "searchString": legal_name,
            "fromDate": from_date,
            "category": "All",
            "sortBy": "fileDate",
            "sortDirection": "desc",
        }
        url = f"{FERC_SEARCH_URL}?{urlencode(params)}"

        try:
            async with httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=True
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
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

        seen: dict[str, dict[str, Any]] = {}
        for m in DOCKET_RE.finditer(html):
            docket = m.group(1)
            if docket in seen:
                continue
            window = html[max(0, m.start() - 200) : m.end() + 200]
            date_m = DATE_RE.search(window)
            file_date = _normalise_iso(date_m.group(1)) if date_m else None
            seen[docket] = {
                "docket": docket,
                "license_type": _classify(docket),
                "issuer": "FERC",
                "identifier": docket,
                "status": "active",
                "valid_from": file_date,
                "valid_to": None,
                "source_url": FERC_DOCKET_URL.format(docket=quote_plus(docket)),
                "source_filing": f"FERC eLibrary · docket {docket}"
                + (f" · filed {file_date}" if file_date else ""),
                "source_tool": "ferc_elibrary",
            }
            if len(seen) >= max_results:
                break

        permits = sorted(
            seen.values(),
            key=lambda p: (p["valid_from"] or "", p["docket"]),
            reverse=True,
        )

        if not permits:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "no_matches",
                        "reason": "FERC eLibrary returned no dockets for this entity name in the requested window",
                        "search_url": url,
                        "legal_name": legal_name,
                    }
                ),
                is_error=False,
                metadata={"status": "no_matches"},
            )

        result = {
            "status": "ok",
            "legal_name": legal_name,
            "search_url": url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "permits": permits,
            "counts_by_type": {
                t: sum(1 for p in permits if p["license_type"] == t)
                for t in {p["license_type"] for p in permits}
            },
        }
        return ToolResult(
            content=json.dumps(result, default=str),
            is_error=False,
            metadata={"status": "ok", "n_permits": len(permits)},
        )


__all__ = ["FercElibraryTool"]
