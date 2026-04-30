"""US government data — SEC EDGAR (free, no key) for company filings."""
from __future__ import annotations

from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_HEADERS = {
    # SEC requires a contact UA. This identifies our platform; replace with
    # operator email when deploying multi-tenant.
    "User-Agent": "Abenix admin@abenix.dev",
    "Accept": "application/json",
}


class GovDataUSTool(BaseTool):
    name = "gov_data_us"
    description = (
        "US government data: SEC EDGAR company filings lookup. Free, no key. "
        "Operations: lookup_company (CIK + recent filings by name/ticker), "
        "get_filing_text (pull a specific filing's body for LLM analysis)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string", "enum": ["lookup_company", "get_filing_text"],
                "default": "lookup_company",
            },
            "query": {
                "type": "string",
                "description": "Company name or ticker for lookup_company; CIK for get_filing_text.",
            },
            "form_type": {
                "type": "string",
                "description": "Optional filter for lookup_company (e.g. '10-K', '10-Q', '8-K').",
            },
            "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "accession_number": {
                "type": "string",
                "description": "For get_filing_text — the accession number from lookup_company.",
            },
            "primary_document": {
                "type": "string",
                "description": "For get_filing_text — the primary document filename.",
            },
        },
        "required": ["operation"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        op = arguments.get("operation", "lookup_company")
        try:
            async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
                if op == "lookup_company":
                    return await self._lookup(client, arguments)
                if op == "get_filing_text":
                    return await self._get_filing(client, arguments)
                return ToolResult(content=f"Unknown operation: {op}", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"SEC HTTP {e.response.status_code}: {e.response.text[:200]}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"SEC error: {e}", is_error=True)

    async def _lookup(self, client: httpx.AsyncClient, args: dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(content="query is required for lookup_company", is_error=True)
        form_type = (args.get("form_type") or "").upper().strip()
        limit = int(args.get("limit", 10))

        # Step 1: resolve query -> CIK via the ticker map.
        r = await client.get(_TICKERS_URL)
        r.raise_for_status()
        tickers = r.json()
        # tickers is a dict keyed by integer index -> {cik_str, ticker, title}
        q_lower = query.lower()
        match = None
        for entry in tickers.values():
            if entry.get("ticker", "").lower() == q_lower or q_lower in entry.get("title", "").lower():
                match = entry
                break
        if not match:
            return ToolResult(content=f"No company matched '{query}' on SEC EDGAR.")
        cik = int(match["cik_str"])

        # Step 2: pull recent submissions for that CIK.
        r = await client.get(_SUBMISSIONS_URL.format(cik=cik))
        r.raise_for_status()
        sub = r.json()
        recent = sub.get("filings", {}).get("recent", {}) or {}
        forms = recent.get("form", [])
        accession = recent.get("accessionNumber", [])
        filing_date = recent.get("filingDate", [])
        primary = recent.get("primaryDocument", [])

        rows = []
        for i, form in enumerate(forms):
            if form_type and form != form_type:
                continue
            rows.append({
                "form": form,
                "filing_date": filing_date[i] if i < len(filing_date) else None,
                "accession_number": accession[i] if i < len(accession) else None,
                "primary_document": primary[i] if i < len(primary) else None,
            })
            if len(rows) >= limit:
                break

        lines = [
            f"SEC EDGAR — {match.get('title')} ({match.get('ticker')}, CIK {cik})",
            f"Recent filings: {len(rows)}" + (f" (filtered to {form_type})" if form_type else ""),
            "",
        ]
        for r in rows:
            lines.append(f"  {r['filing_date']}  {r['form']:<10}  {r['accession_number']}")
        return ToolResult(
            content="\n".join(lines),
            metadata={"cik": cik, "company": match, "filings": rows},
        )

    async def _get_filing(self, client: httpx.AsyncClient, args: dict[str, Any]) -> ToolResult:
        cik_raw = (args.get("query") or "").strip()
        accession = (args.get("accession_number") or "").strip().replace("-", "")
        primary = (args.get("primary_document") or "").strip()
        if not (cik_raw and accession and primary):
            return ToolResult(
                content="get_filing_text needs query (CIK), accession_number, and primary_document",
                is_error=True,
            )
        try:
            cik = int(cik_raw)
        except ValueError:
            return ToolResult(content="query must be a numeric CIK for get_filing_text", is_error=True)

        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary}"
        r = await client.get(url)
        r.raise_for_status()
        body = r.text
        # Strip HTML tags very crudely; LLM downstream will reason on plain text.
        import re
        plain = re.sub(r"<[^>]+>", " ", body)
        plain = re.sub(r"\s+", " ", plain).strip()
        return ToolResult(
            content=f"SEC filing — CIK {cik} / {primary}\n\n{plain[:8000]}",
            metadata={"cik": cik, "url": url, "length": len(plain)},
        )
