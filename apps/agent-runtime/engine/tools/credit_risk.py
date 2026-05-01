"""Counterparty credit-risk assessment tool."""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_FMP_BASE = "https://financialmodelingprep.com/api/v3"
_TIMEOUT = 20.0  # seconds per HTTP call


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Return *numerator / denominator* or ``None`` when the division is
    undefined (missing operand, zero denominator, etc.)."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def _fmt(value: float | None, decimals: int = 4) -> float | None:
    """Round a float for JSON serialisation, preserving ``None``."""
    if value is None:
        return None
    return round(value, decimals)


class CreditRiskTool(BaseTool):
    name = "credit_risk"
    description = (
        "Assess counterparty credit risk for publicly-listed companies. "
        "Uses the Financial Modeling Prep (FMP) API to fetch credit ratings "
        "(A++ to D-), financial ratios (debt/equity, current ratio, interest "
        "coverage, net debt/EBITDA, ROE), balance sheet and income statement "
        "data. Computes Altman Z-Score (Safe/Grey/Distress zones) and "
        "probability of default. Returns a comprehensive credit risk report. "
        "Requires FMP_API_KEY env var (free tier: 250 calls/day at "
        "financialmodelingprep.com)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "Company name to look up (e.g. 'Apple Inc' or 'TSLA').",
            },
            "operation": {
                "type": "string",
                "enum": ["full_assessment", "quick_score", "financial_ratios"],
                "default": "full_assessment",
                "description": (
                    "Assessment depth: 'full_assessment' (default) returns "
                    "everything; 'quick_score' returns Altman Z and PD only; "
                    "'financial_ratios' returns key ratios only."
                ),
            },
        },
        "required": ["company_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        company_name = (arguments.get("company_name") or "").strip()
        operation = (arguments.get("operation") or "full_assessment").strip()

        if not company_name:
            return ToolResult(
                content="Error: 'company_name' is required.",
                is_error=True,
            )

        api_key = os.environ.get("FMP_API_KEY", "")
        if not api_key:
            return ToolResult(
                content=(
                    "Error: FMP_API_KEY environment variable is not set. "
                    "Get a free key at https://financialmodelingprep.com/ "
                    "and set it with: export FMP_API_KEY=your_key"
                ),
                is_error=True,
            )

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # 1. Resolve company name -> ticker
                ticker, resolved_name = await self._resolve_ticker(
                    client,
                    api_key,
                    company_name,
                )
                if ticker is None:
                    return ToolResult(
                        content=f"Could not find a matching company for '{company_name}'.",
                        is_error=True,
                    )

                # 2. Fetch data in parallel based on operation
                if operation == "financial_ratios":
                    report = await self._ratios_report(
                        client,
                        api_key,
                        ticker,
                        resolved_name,
                    )
                elif operation == "quick_score":
                    report = await self._quick_score_report(
                        client,
                        api_key,
                        ticker,
                        resolved_name,
                    )
                else:
                    report = await self._full_assessment(
                        client,
                        api_key,
                        ticker,
                        resolved_name,
                    )

                return ToolResult(
                    content=json.dumps(report, indent=2),
                    metadata={"ticker": ticker, "operation": operation},
                )

        except httpx.TimeoutException:
            return ToolResult(
                content="Error: FMP API request timed out. Please try again.",
                is_error=True,
            )
        except Exception as exc:
            logger.exception("credit_risk tool error")
            return ToolResult(
                content=f"Error assessing credit risk for '{company_name}': {exc}",
                is_error=True,
            )

    @staticmethod
    async def _fmp_get(
        client: httpx.AsyncClient,
        path: str,
        api_key: str,
        params: dict[str, str] | None = None,
    ) -> Any:
        """GET from FMP and return the parsed JSON (list or dict)."""
        url = f"{_FMP_BASE}{path}"
        all_params = {"apikey": api_key}
        if params:
            all_params.update(params)
        resp = await client.get(url, params=all_params)
        resp.raise_for_status()
        return resp.json()

    async def _resolve_ticker(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        query: str,
    ) -> tuple[str | None, str]:
        """Return ``(ticker, company_name)`` or ``(None, "")``."""
        results = await self._fmp_get(
            client,
            "/search",
            api_key,
            {"query": query, "limit": "5"},
        )
        if not results:
            return None, ""
        # Prefer exact-ish match on name, fall back to first result
        best = results[0]
        query_lower = query.lower()
        for item in results:
            if item.get("name", "").lower() == query_lower:
                best = item
                break
            if item.get("symbol", "").lower() == query_lower:
                best = item
                break
        return best.get("symbol"), best.get("name", query)

    async def _fetch_rating(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
    ) -> dict[str, Any]:
        data = await self._fmp_get(client, f"/rating/{ticker}", api_key)
        if isinstance(data, list) and data:
            return data[0]
        return {}

    async def _fetch_ratios(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
    ) -> dict[str, Any]:
        data = await self._fmp_get(
            client,
            f"/ratios/{ticker}",
            api_key,
            {"limit": "1"},
        )
        if isinstance(data, list) and data:
            return data[0]
        return {}

    async def _fetch_balance_sheet(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
    ) -> dict[str, Any]:
        data = await self._fmp_get(
            client,
            f"/balance-sheet-statement/{ticker}",
            api_key,
            {"limit": "1"},
        )
        if isinstance(data, list) and data:
            return data[0]
        return {}

    async def _fetch_income_statement(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
    ) -> dict[str, Any]:
        data = await self._fmp_get(
            client,
            f"/income-statement/{ticker}",
            api_key,
            {"limit": "1"},
        )
        if isinstance(data, list) and data:
            return data[0]
        return {}

    @staticmethod
    def _compute_altman_z(
        bs: dict[str, Any],
        inc: dict[str, Any],
        market_cap: float | None,
    ) -> dict[str, Any]:
        """Compute Altman Z-Score from balance-sheet and income-statement"""

        total_assets = bs.get("totalAssets")
        total_liabilities = bs.get("totalLiabilities")
        current_assets = bs.get("totalCurrentAssets")
        current_liabilities = bs.get("totalCurrentLiabilities")
        retained_earnings = bs.get("retainedEarnings")
        revenue = inc.get("revenue")
        ebit = inc.get("operatingIncome")  # FMP uses operatingIncome for EBIT

        # Working capital
        working_capital: float | None = None
        if current_assets is not None and current_liabilities is not None:
            working_capital = current_assets - current_liabilities

        # Individual Z-Score components
        x1 = _safe_div(working_capital, total_assets)
        x2 = _safe_div(retained_earnings, total_assets)
        x3 = _safe_div(ebit, total_assets)
        x4 = _safe_div(market_cap, total_liabilities)
        x5 = _safe_div(revenue, total_assets)

        components = {
            "x1_wc_ta": x1,
            "x2_re_ta": x2,
            "x3_ebit_ta": x3,
            "x4_mktcap_tl": x4,
            "x5_rev_ta": x5,
        }

        z_score: float | None = None
        if all(v is not None for v in (x1, x2, x3, x4, x5)):
            z_score = (
                1.2 * x1  # type: ignore[operator]
                + 1.4 * x2  # type: ignore[operator]
                + 3.3 * x3  # type: ignore[operator]
                + 0.6 * x4  # type: ignore[operator]
                + 1.0 * x5  # type: ignore[operator]
            )

        # Zone classification
        if z_score is not None:
            if z_score > 2.99:
                zone = "Safe"
            elif z_score >= 1.81:
                zone = "Grey"
            else:
                zone = "Distress"
        else:
            zone = "Unavailable"

        # Probability of default (logistic mapping centred at 1.81)
        pd_pct: float | None = None
        if z_score is not None:
            pd_pct = round(100.0 / (1.0 + math.exp(5.0 * (z_score - 1.81))), 2)

        return {
            "altman_z_score": _fmt(z_score),
            "z_score_zone": zone,
            "probability_of_default_pct": pd_pct,
            "components": {k: _fmt(v) for k, v in components.items()},
        }

    async def _full_assessment(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
        company_name: str,
    ) -> dict[str, Any]:
        """Full credit-risk assessment: rating + ratios + Z-Score + PD."""

        # Fetch all four endpoints concurrently
        import asyncio

        rating_coro = self._fetch_rating(client, api_key, ticker)
        ratios_coro = self._fetch_ratios(client, api_key, ticker)
        bs_coro = self._fetch_balance_sheet(client, api_key, ticker)
        inc_coro = self._fetch_income_statement(client, api_key, ticker)

        rating, ratios, bs, inc = await asyncio.gather(
            rating_coro,
            ratios_coro,
            bs_coro,
            inc_coro,
        )

        # Market cap from balance-sheet + rating data
        market_cap = (
            bs.get("marketCap") or rating.get("ratingDetailsDCFRecommendation") or None
        )
        # FMP /rating has marketCap on the profile; fall back to enterprise estimate
        # A more reliable source: try the profile endpoint if needed
        if market_cap is None:
            try:
                profile = await self._fmp_get(
                    client,
                    f"/profile/{ticker}",
                    api_key,
                )
                if isinstance(profile, list) and profile:
                    market_cap = profile[0].get("mktCap")
                    sector = profile[0].get("sector", "")
                else:
                    sector = ""
            except Exception:
                sector = ""
        else:
            sector = ""

        # Try to get sector from profile if we haven't yet
        if not sector:
            try:
                profile = await self._fmp_get(
                    client,
                    f"/profile/{ticker}",
                    api_key,
                )
                if isinstance(profile, list) and profile:
                    sector = profile[0].get("sector", "")
                    if market_cap is None:
                        market_cap = profile[0].get("mktCap")
            except Exception:
                pass

        z_data = self._compute_altman_z(bs, inc, market_cap)

        # Build key-ratios block
        key_ratios = self._extract_key_ratios(ratios)

        # Risk summary text
        risk_summary = self._build_risk_summary(
            company_name,
            ticker,
            z_data,
            rating,
            key_ratios,
        )

        return {
            "company_name": company_name,
            "ticker": ticker,
            "sector": sector or "N/A",
            "market_cap": market_cap,
            "fmp_rating": rating.get("ratingRecommendation", "N/A"),
            "fmp_score": rating.get("ratingScore"),
            "altman_z_score": z_data["altman_z_score"],
            "z_score_zone": z_data["z_score_zone"],
            "probability_of_default_pct": z_data["probability_of_default_pct"],
            "z_score_components": z_data["components"],
            "key_ratios": key_ratios,
            "risk_summary": risk_summary,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    async def _quick_score_report(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
        company_name: str,
    ) -> dict[str, Any]:
        """Lightweight report: Z-Score + PD only."""
        import asyncio

        bs_coro = self._fetch_balance_sheet(client, api_key, ticker)
        inc_coro = self._fetch_income_statement(client, api_key, ticker)
        bs, inc = await asyncio.gather(bs_coro, inc_coro)

        # Grab market cap from profile
        market_cap: float | None = None
        try:
            profile = await self._fmp_get(
                client,
                f"/profile/{ticker}",
                api_key,
            )
            if isinstance(profile, list) and profile:
                market_cap = profile[0].get("mktCap")
        except Exception:
            pass

        z_data = self._compute_altman_z(bs, inc, market_cap)

        return {
            "company_name": company_name,
            "ticker": ticker,
            "altman_z_score": z_data["altman_z_score"],
            "z_score_zone": z_data["z_score_zone"],
            "probability_of_default_pct": z_data["probability_of_default_pct"],
            "z_score_components": z_data["components"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    async def _ratios_report(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        ticker: str,
        company_name: str,
    ) -> dict[str, Any]:
        """Key financial ratios only."""
        ratios = await self._fetch_ratios(client, api_key, ticker)
        key_ratios = self._extract_key_ratios(ratios)

        return {
            "company_name": company_name,
            "ticker": ticker,
            "key_ratios": key_ratios,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_key_ratios(ratios: dict[str, Any]) -> dict[str, Any]:
        """Pull the five headline ratios from FMP /ratios response."""
        return {
            "debt_equity": _fmt(ratios.get("debtEquityRatio")),
            "current_ratio": _fmt(ratios.get("currentRatio")),
            "interest_coverage": _fmt(ratios.get("interestCoverage")),
            "net_debt_to_ebitda": _fmt(
                ratios.get("netDebtToEBITDA") or ratios.get("debtRatio")
            ),
            "roe": _fmt(ratios.get("returnOnEquity")),
        }

    @staticmethod
    def _build_risk_summary(
        company_name: str,
        ticker: str,
        z_data: dict[str, Any],
        rating: dict[str, Any],
        key_ratios: dict[str, Any],
    ) -> str:
        """Produce a short human-readable risk summary."""
        parts: list[str] = []

        zone = z_data["z_score_zone"]
        z = z_data["altman_z_score"]
        pd = z_data["probability_of_default_pct"]

        if z is not None:
            parts.append(
                f"{company_name} ({ticker}) has an Altman Z-Score of {z:.2f}, "
                f"placing it in the '{zone}' zone."
            )
        else:
            parts.append(
                f"{company_name} ({ticker}): insufficient financial data to "
                "compute an Altman Z-Score."
            )

        if pd is not None:
            parts.append(f"Estimated probability of default: {pd:.1f}%.")

        fmp_rec = rating.get("ratingRecommendation")
        fmp_score = rating.get("ratingScore")
        if fmp_rec:
            parts.append(f"FMP rating recommendation: {fmp_rec} (score {fmp_score}).")

        de = key_ratios.get("debt_equity")
        cr = key_ratios.get("current_ratio")
        if de is not None:
            if de > 2.0:
                parts.append(f"Debt/Equity of {de:.2f} is elevated — leverage risk.")
            else:
                parts.append(f"Debt/Equity of {de:.2f} is within normal range.")
        if cr is not None:
            if cr < 1.0:
                parts.append(
                    f"Current ratio of {cr:.2f} is below 1 — potential liquidity concern."
                )
            else:
                parts.append(f"Current ratio of {cr:.2f} indicates adequate liquidity.")

        return " ".join(parts)
