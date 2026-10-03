"""S&P Global Ratings API tool for issuer rating refresh.

Configurable shell. Hits S&P Capital IQ Ratings Xpress when the operator
sets $SPG_RATINGS_API_KEY + $SPG_RATINGS_API_URL. If unset, returns
status=needs_configuration with explicit setup instructions — never a
mocked rating.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ConfigField, ToolResult


logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0
USER_AGENT = "AgentForge issuer-rating-refresh contact@agentforge.local"


class SPGRatingsTool(BaseTool):
    name = "spg_ratings_api"
    risk_tier = "low"
    config_fields = (
        ConfigField(
            "SPG_RATINGS_API_KEY",
            label="API key",
            kind="secret",
            required=True,
            group="S&P Global Ratings",
        ),
        ConfigField(
            "SPG_RATINGS_API_URL",
            label="API URL",
            kind="url",
            required=False,
            group="S&P Global Ratings",
        ),
    )
    description = (
        "Fetch current issuer credit rating + outlook from S&P Global Ratings. "
        "Needs SPG_RATINGS_API_KEY and SPG_RATINGS_API_URL, set under Admin -> Tool Configuration, "
        "(provided by S&P under a Capital IQ contract). Without keys the "
        "tool returns needs_configuration; never fabricates a rating."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "legal_name": {"type": "string"},
            "ticker": {"type": "string"},
            "lei": {"type": "string", "description": "20-char Legal Entity Identifier"},
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        api_key = self.cfg("SPG_RATINGS_API_KEY", required=True).strip()
        api_url = self.cfg("SPG_RATINGS_API_URL").strip()

        if not api_url:
            return ToolResult(
                content=json.dumps(
                    {
                        "status": "needs_configuration",
                        "tool": "spg_ratings_api",
                        "instructions": (
                            "S&P Global Ratings access requires a Capital IQ contract. "
                            "Once procured, set SPG_RATINGS_API_KEY (Bearer token) + "
                            "SPG_RATINGS_API_URL (e.g. https://api.capitaliq.com/ratings/v1) "
                            "under Admin -> Tool Configuration. The tool will pull the current "
                            "issuer rating + outlook + last action date on every refresh. "
                            "No mocked data is returned without the key."
                        ),
                        "vendor_url": "https://www.spglobal.com/ratings/en/products-benefits/products/credit-ratings",
                    }
                ),
                is_error=False,
                metadata={"status": "needs_configuration"},
            )

        legal_name = (arguments.get("legal_name") or "").strip()
        ticker = (arguments.get("ticker") or "").strip()
        lei = (arguments.get("lei") or "").strip()
        if not (legal_name or ticker or lei):
            return ToolResult(
                content="legal_name, ticker, or lei required", is_error=True
            )

        params: dict[str, Any] = {}
        if lei:
            params["lei"] = lei
        elif ticker:
            params["ticker"] = ticker
        else:
            params["name"] = legal_name

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                r = await client.get(
                    f"{api_url.rstrip('/')}/issuer-rating",
                    params=params,
                    headers=headers,
                )
                if r.status_code == 401:
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "auth_error",
                                "reason": "S&P returned 401 — check SPG_RATINGS_API_KEY validity",
                            }
                        ),
                        is_error=True,
                        metadata={"status": "auth_error"},
                    )
                if r.status_code == 404:
                    return ToolResult(
                        content=json.dumps(
                            {
                                "status": "not_found",
                                "reason": "S&P has no rating record for this entity",
                                "search": params,
                            }
                        ),
                        is_error=False,
                        metadata={"status": "not_found"},
                    )
                r.raise_for_status()
                payload = r.json()
        except httpx.HTTPError as e:
            return ToolResult(
                content=json.dumps({"status": "fetch_error", "reason": str(e)}),
                is_error=True,
                metadata={"status": "fetch_error"},
            )

        result = {
            "status": "ok",
            "ratings": [
                {
                    "agency": "S&P",
                    "rating": payload.get("rating") or payload.get("longTermRating"),
                    "outlook": payload.get("outlook"),
                    "as_of": payload.get("ratingActionDate") or payload.get("asOf"),
                    "issuer": payload.get("issuerName") or legal_name,
                    "source_url": payload.get("sourceUrl")
                    or "https://www.spglobal.com/ratings/",
                }
            ],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return ToolResult(
            content=json.dumps(result, default=str),
            is_error=False,
            metadata={"status": "ok"},
        )


__all__ = ["SPGRatingsTool"]
