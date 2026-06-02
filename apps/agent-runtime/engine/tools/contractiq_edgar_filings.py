"""SEC EDGAR XBRL filings tool for ContractIQ counterparty refresh.

Pulls the last N fiscal years of GAAP/IFRS-mapped financial data for any
US-listed issuer (10-K, 20-F, 40-F). Output shape matches the
`contractiq_financial_statements` table line-items dictionary.

Source: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
Ticker→CIK: https://www.sec.gov/files/company_tickers.json
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult


logger = logging.getLogger(__name__)

EDGAR_USER_AGENT = "ContractIQ (E&C-Copilot) contact@contractiq.local"
TICKERS_INDEX_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
EDGAR_FILINGS_BASE = "https://www.sec.gov/cgi-bin/browse-edgar"
REQUEST_TIMEOUT = 30.0


_TICKERS_CACHE: dict[str, int] | None = None
_TICKERS_LOCK = asyncio.Lock()


CONCEPT_MAP: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "interest_expense": [
        "InterestExpense",
        "InterestExpenseDebt",
    ],
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "long_term_debt": [
        "LongTermDebt",
        "LongTermDebtNoncurrent",
    ],
    "total_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
}


async def _load_tickers_index(client: httpx.AsyncClient) -> dict[str, int]:
    global _TICKERS_CACHE
    if _TICKERS_CACHE is not None:
        return _TICKERS_CACHE
    async with _TICKERS_LOCK:
        if _TICKERS_CACHE is not None:
            return _TICKERS_CACHE
        r = await client.get(
            TICKERS_INDEX_URL, headers={"User-Agent": EDGAR_USER_AGENT}
        )
        r.raise_for_status()
        raw = r.json()
        idx: dict[str, int] = {}
        for _, row in raw.items():
            t = str(row.get("ticker", "")).upper().strip()
            cik = int(row.get("cik_str") or 0)
            if t and cik:
                idx[t] = cik
        _TICKERS_CACHE = idx
        return idx


def _pick_annual(
    concept_payload: dict[str, Any],
    n_years: int,
) -> list[dict[str, Any]]:
    units = concept_payload.get("units") or {}
    candidates = units.get("USD") or next(iter(units.values()), [])
    annuals = [
        e
        for e in candidates
        if isinstance(e, dict)
        and (e.get("fp") == "FY" or (e.get("form") in ("10-K", "20-F", "40-F")))
        and e.get("end")
    ]
    seen: dict[int, dict[str, Any]] = {}
    for entry in annuals:
        try:
            end_dt = datetime.fromisoformat(entry["end"])
        except Exception:
            continue
        year = end_dt.year
        cur = seen.get(year)
        if cur is None or entry.get("filed", "") > cur.get("filed", ""):
            seen[year] = entry
    sorted_entries = sorted(seen.values(), key=lambda e: e["end"], reverse=True)
    return sorted_entries[:n_years]


def _extract_concept(
    facts: dict[str, Any],
    concept_names: list[str],
    n_years: int,
) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    us_gaap = facts.get("us-gaap") or {}
    ifrs = facts.get("ifrs-full") or {}
    for cn in concept_names:
        block = us_gaap.get(cn) or ifrs.get(cn)
        if not block:
            continue
        for entry in _pick_annual(block, n_years):
            try:
                end_dt = datetime.fromisoformat(entry["end"])
            except Exception:
                continue
            year = end_dt.year
            if year in out:
                continue
            out[year] = {
                "value": float(entry["val"]),
                "end": entry["end"],
                "form": entry.get("form"),
                "accn": entry.get("accn"),
                "filed": entry.get("filed"),
                "concept": cn,
            }
        if out:
            break
    return out


def _build_statements(
    facts: dict[str, Any],
    n_years: int,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, str]]]:
    raw: dict[str, dict[int, dict[str, Any]]] = {
        key: _extract_concept(facts, names, n_years)
        for key, names in CONCEPT_MAP.items()
    }
    statements: dict[int, dict[str, Any]] = {}
    provenance: dict[int, dict[str, str]] = {}

    years: set[int] = set()
    for key_data in raw.values():
        years.update(key_data.keys())
    if not years:
        return statements, provenance

    for year in sorted(years, reverse=True)[:n_years]:
        row: dict[str, Any] = {}
        prov: dict[str, str] = {}
        for key, key_data in raw.items():
            entry = key_data.get(year)
            if entry is None:
                continue
            row[key] = entry["value"]
            prov[key] = (
                f"{entry.get('concept')} · {entry.get('form')} · {entry.get('accn')}"
            )

        ebit = row.get("net_income")
        if ebit is not None:
            ebit = (
                ebit
                + (row.get("interest_expense") or 0)
                + (row.get("income_tax_expense") or 0)
            )
        dep = row.get("depreciation_amortization") or 0
        if ebit is not None:
            row["ebitda"] = ebit + dep
            prov["ebitda"] = (
                "computed: net_income + interest_expense + income_tax_expense + D&A"
            )

        ocf = row.get("operating_cash_flow")
        capex = row.get("capital_expenditure")
        if ocf is not None and capex is not None:
            row["free_cash_flow"] = ocf - capex
            prov["free_cash_flow"] = (
                "computed: operating_cash_flow - capital_expenditure"
            )

        for to_M in (
            "revenue",
            "net_income",
            "ebitda",
            "interest_expense",
            "total_assets",
            "current_assets",
            "cash_and_equivalents",
            "total_liabilities",
            "current_liabilities",
            "long_term_debt",
            "total_equity",
            "operating_cash_flow",
            "free_cash_flow",
        ):
            v = row.get(to_M)
            if v is not None:
                row[to_M] = v / 1_000_000.0

        if row:
            statements[year] = row
            provenance[year] = prov

    return statements, provenance


class ContractIQEdgarFilingsTool(BaseTool):
    name = "edgar_filings"
    description = (
        "Fetch the last 5 fiscal years of GAAP/IFRS-mapped financial statements "
        "for a US-listed issuer from SEC EDGAR XBRL company-facts API. Input: "
        "ticker (e.g. 'XOM') or cik (10-digit int). Output: statements keyed by "
        "fiscal year with revenue / EBITDA / net income / balance-sheet / cash-flow line "
        "items in USD millions, plus per-concept provenance citing the XBRL concept + "
        "filing accession number."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Stock ticker (case-insensitive). Use this OR cik.",
            },
            "cik": {
                "type": "integer",
                "description": "SEC Central Index Key (10-digit int). Use this OR ticker.",
            },
            "n_years": {"type": "integer", "default": 5, "minimum": 1, "maximum": 10},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        ticker = (arguments.get("ticker") or "").strip().upper() or None
        cik_arg = arguments.get("cik")
        n_years = int(arguments.get("n_years") or 5)

        if not ticker and not cik_arg:
            return ToolResult(content="provide either 'ticker' or 'cik'", is_error=True)

        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            try:
                if ticker and not cik_arg:
                    idx = await _load_tickers_index(client)
                    cik = idx.get(ticker)
                    if cik is None:
                        return ToolResult(
                            content=json.dumps(
                                {
                                    "status": "not_available",
                                    "reason": f"ticker {ticker} not found in SEC tickers index — likely non-US-listed",
                                    "ticker_searched": ticker,
                                }
                            ),
                            is_error=False,
                            metadata={"status": "not_available"},
                        )
                else:
                    cik = int(cik_arg)  # type: ignore[arg-type]

                url = COMPANYFACTS_URL.format(cik=cik)
                r = await client.get(url, headers={"User-Agent": EDGAR_USER_AGENT})
                if r.status_code == 404:
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "not_available",
                                "reason": f"no XBRL company-facts for CIK {cik} — issuer may file paper-only or be deregistered",
                                "cik": cik,
                            }
                        ),
                        is_error=False,
                        metadata={"status": "not_available"},
                    )
                r.raise_for_status()
                payload = r.json()
            except httpx.HTTPError as e:
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "fetch_error",
                            "reason": f"EDGAR request failed: {e}",
                        }
                    ),
                    is_error=True,
                    metadata={"status": "fetch_error"},
                )

        entity_name = payload.get("entityName") or payload.get("cik")
        facts = payload.get("facts") or {}
        statements, provenance = _build_statements(facts, n_years)

        if not statements:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "no_xbrl_data",
                        "reason": "EDGAR has filings but no XBRL company-facts coverage for the concepts we map",
                        "entity_name": entity_name,
                        "cik": cik,
                    }
                ),
                is_error=False,
                metadata={"status": "no_xbrl_data"},
            )

        result = {
            "status": "ok",
            "entity_name": entity_name,
            "cik": cik,
            "ticker": ticker,
            "years": sorted(statements.keys()),
            "currency": "USD",
            "unit": "millions",
            "statements": statements,
            "provenance": provenance,
            "source_url_template": COMPANYFACTS_URL.format(cik=cik),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return ToolResult(
            content=json.dumps(result, default=str),
            is_error=False,
            metadata={"status": "ok", "n_years": len(statements)},
        )


__all__ = ["ContractIQEdgarFilingsTool"]
