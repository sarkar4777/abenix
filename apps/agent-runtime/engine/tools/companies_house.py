"""UK Companies House REST tool for counterparty refresh.

Companies House publishes a JSON REST API covering UK-incorporated entities:
filings index, officer list, beneficial owners, accounting periods. Free
with API-key (signup at developer.company-information.service.gov.uk).

If COMPANIES_HOUSE_API_KEY is unset, the tool returns
status=needs_configuration with the instructions — never a mock.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, ToolResult


logger = logging.getLogger(__name__)

CH_API_BASE = "https://api.company-information.service.gov.uk"
USER_AGENT = "AgentForge counterparty-refresh contact@agentforge.local"
REQUEST_TIMEOUT = 30.0


class CompaniesHouseTool(BaseTool):
    name = "companies_house"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "COMPANIES_HOUSE_API_KEY",
            label="API key",
            kind="secret",
            required=True,
            group="Companies House",
            signup_url="https://developer.company-information.service.gov.uk/",
        ),
    )

    @classmethod
    async def config_test(
        cls, values: dict[str, str], key: str | None = None
    ) -> tuple[bool, str] | None:
        from engine.tools._config_probe import probe

        return await probe(
            "GET",
            f"{CH_API_BASE}/search/companies",
            params={"q": "test", "items_per_page": 1},
            auth=(values.get("COMPANIES_HOUSE_API_KEY", ""), ""),
            headers={"User-Agent": USER_AGENT},
            accepted="Companies House accepted the key",
        )

    description = (
        "Look up a UK-incorporated counterparty in Companies House. "
        "Returns the company profile (incorporation date, status, SIC codes, "
        "registered office) and filing index for recent annual accounts. "
        "Needs COMPANIES_HOUSE_API_KEY, set under Admin -> Tool Configuration (free signup at "
        "developer.company-information.service.gov.uk); returns "
        "needs_configuration if unset — never mocked data."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "company_number": {
                "type": "string",
                "description": "Companies House 8-digit number (preferred)",
            },
            "legal_name": {
                "type": "string",
                "description": "Used to search if company_number not provided",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        api_key = self.cfg("COMPANIES_HOUSE_API_KEY", required=True).strip()
        company_number = (arguments.get("company_number") or "").strip()
        legal_name = (arguments.get("legal_name") or "").strip()

        if not company_number and not legal_name:
            return ToolResult(
                content="company_number or legal_name required", is_error=True
            )

        auth = base64.b64encode(f"{api_key}:".encode()).decode()
        headers = {
            "Authorization": f"Basic {auth}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                if not company_number:
                    r = await client.get(
                        f"{CH_API_BASE}/search/companies",
                        params={"q": legal_name, "items_per_page": 5},
                        headers=headers,
                    )
                    r.raise_for_status()
                    items = (r.json() or {}).get("items") or []
                    if not items:
                        return ToolResult(
                            content=json.dumps(
                                {
                                    "status": "not_found",
                                    "reason": f"no UK Companies House match for '{legal_name}'",
                                }
                            ),
                            is_error=False,
                            metadata={"status": "not_found"},
                        )
                    company_number = items[0].get("company_number")
                    if not company_number:
                        return ToolResult(
                            content=json.dumps(
                                {
                                    "status": "not_found",
                                    "reason": "Companies House search returned items without numbers",
                                }
                            ),
                            is_error=False,
                            metadata={"status": "not_found"},
                        )

                prof = await client.get(
                    f"{CH_API_BASE}/company/{company_number}", headers=headers
                )
                if prof.status_code == 404:
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "not_found",
                                "reason": f"company number {company_number} not found",
                            }
                        ),
                        is_error=False,
                        metadata={"status": "not_found"},
                    )
                prof.raise_for_status()
                profile = prof.json()

                fil = await client.get(
                    f"{CH_API_BASE}/company/{company_number}/filing-history",
                    params={"items_per_page": 25, "category": "accounts"},
                    headers=headers,
                )
                fil.raise_for_status()
                filings = (fil.json() or {}).get("items") or []
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps({"status": "fetch_error", "reason": str(e)}),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        return ToolResult(
            content=json.dumps(
                {
                    "status": "ok",
                    "company_number": company_number,
                    "profile": {
                        "name": profile.get("company_name"),
                        "status": profile.get("company_status"),
                        "incorporated_on": profile.get("date_of_creation"),
                        "company_type": profile.get("type"),
                        "sic_codes": profile.get("sic_codes"),
                        "jurisdiction": profile.get("jurisdiction"),
                        "registered_office": profile.get("registered_office_address"),
                        "accounts": profile.get("accounts"),
                    },
                    "filings": [
                        {
                            "date": f.get("date"),
                            "description": f.get("description"),
                            "type": f.get("type"),
                            "transaction_id": f.get("transaction_id"),
                            "source_url": f"https://find-and-update.company-information.service.gov.uk/company/{company_number}/filing-history/{f.get('transaction_id')}",
                        }
                        for f in filings
                    ],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                default=str,
            ),
            is_error=False,
            metadata={"status": "ok"},
        )


__all__ = ["CompaniesHouseTool"]
