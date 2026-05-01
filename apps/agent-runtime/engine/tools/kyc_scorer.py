"""KYC risk scorer — deterministic aggregation for the MET-style header."""
from __future__ import annotations

import json
import logging
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


def _indicator_i_score_from_cpi(cpi_rank: float | int | None) -> tuple[int, str]:
    """MET Indicator I — Country of Domicile Corruption Index rank."""
    if cpi_rank is None:
        return 10, "CPI rank unknown — default mid-band (10)"
    r = int(cpi_rank)
    if r <= 20:
        return 2, f"CPI rank {r} — very low corruption"
    if r <= 40:
        return 5, f"CPI rank {r} — low corruption"
    if r <= 60:
        return 7, f"CPI rank {r} — moderate corruption"
    if r <= 80:
        return 10, f"CPI rank {r} — elevated corruption"
    if r <= 100:
        return 13, f"CPI rank {r} — high corruption"
    if r <= 120:
        return 17, f"CPI rank {r} — very high corruption"
    if r <= 140:
        return 20, f"CPI rank {r} — severe corruption"
    return 25, f"CPI rank {r} — extreme corruption"


def _indicator_ii_score_from_volume(notional_usd: float | None) -> tuple[int, str]:
    """MET Indicator II — Annual Contracted Volume / Notional."""
    if notional_usd is None:
        return 15, "Volume unknown — default mid-band (15)"
    v = float(notional_usd)
    if v < 500_000:
        return 5, f"Notional ${v:,.0f} — immaterial (<$0.5M)"
    if v < 5_000_000:
        return 10, f"Notional ${v:,.0f} — small (<$5M)"
    if v < 50_000_000:
        return 20, f"Notional ${v:,.0f} — medium ($5M–$50M)"
    if v < 250_000_000:
        return 30, f"Notional ${v:,.0f} — large ($50M–$250M)"
    if v < 1_000_000_000:
        return 40, f"Notional ${v:,.0f} — very large ($250M–$1B)"
    return 50, f"Notional ${v:,.0f} — material (≥$1B)"


# Industry risk class is informed by FATF NRA findings, Basel AML index
# sector exposure, and Wolfsberg sector risk ratings.
_INDUSTRY_SCORES: dict[str, tuple[int, str]] = {
    # Higher-risk sectors (laundering, sanctions evasion, bribery exposure)
    "arms_defence": (30, "Arms & defence — extreme sanctions exposure, end-user risk"),
    "gambling_casinos": (30, "Gambling / casinos — frequent STR filings, cash-intensive"),
    "crypto_vasp": (28, "Virtual Asset Service Provider — FATF R.15 enhanced DD"),
    "mining_extractives": (25, "Mining / extractives — Transparency PWYP exposure"),
    "oil_gas": (22, "Oil & gas — sanctions and corruption risk"),
    "shipping_maritime": (22, "Shipping — flag-of-convenience and sanctions evasion"),
    "cash_intensive_retail": (22, "Cash-intensive retail"),
    "money_service_business": (28, "MSB — FATF-designated higher risk"),
    "real_estate": (20, "Real estate — FATF NRA flags layering via property"),
    "precious_metals_stones": (25, "Precious metals/stones — smurfing and laundering"),
    "construction": (18, "Construction — sub-contractor and invoice fraud risk"),
    "telecoms": (15, "Telecoms — moderate PEP and sanctions exposure"),
    # Medium risk
    "energy_trading": (16.25, "Energy trading — MET reference template score"),
    "manufacturing": (12, "Manufacturing — moderate risk"),
    "wholesale_distribution": (12, "Wholesale / distribution"),
    "professional_services": (10, "Professional services"),
    "agriculture": (10, "Agriculture / agri-commodities"),
    "wood_furniture_paper": (16.25, "Wood, furniture & paper manufacturing — MET reference template"),
    # Lower risk
    "utility_regulated": (6, "Regulated utility — subject to national oversight"),
    "public_sector": (3, "Public sector / government-owned entity"),
    "education": (4, "Education"),
    "healthcare_regulated": (5, "Regulated healthcare"),
    "technology_saas": (7, "Technology / SaaS"),
    "insurance_regulated": (6, "Regulated insurance"),
    "banking_regulated": (8, "Regulated bank — subject to prudential supervision"),
    "other": (12, "Other — default mid-band"),
}


def _indicator_iii_score_from_industry(industry_key: str | None) -> tuple[int, str]:
    if not industry_key:
        return 12, "Industry not specified — default (12)"
    key = industry_key.strip().lower().replace(" ", "_").replace("&", "and")
    # Try exact, then substring
    if key in _INDUSTRY_SCORES:
        score, desc = _INDUSTRY_SCORES[key]
        return int(score), desc
    for k, (score, desc) in _INDUSTRY_SCORES.items():
        if k in key or key in k:
            return int(score), desc
    return _INDUSTRY_SCORES["other"][0], _INDUSTRY_SCORES["other"][1]


def _check_type_from_aggregate(agg: float, extra_signals_triggered: bool) -> str:
    """Map aggregated score to check type."""
    base = "Simplified" if agg <= 15 else "Standard" if agg <= 60 else "Enhanced"
    if extra_signals_triggered:
        if base == "Simplified":
            return "Standard"
        if base == "Standard":
            return "Enhanced"
    return base


class KYCScorerTool(BaseTool):
    name = "kyc_scorer"
    description = (
        "Deterministic KYC risk scorer — turns the three header indicators "
        "(Country Corruption Index rank, Annual Contracted Volume / Notional, "
        "Industry Segment) plus any adverse signals from sanctions, PEP, "
        "adverse-media, UBO-gap, or legal-existence checks into an "
        "Aggregated Score, a Type of Check (Simplified / Standard / "
        "Enhanced) and a top-line L/M/H KYC grade. Uses published guidance "
        "from FATF, ESA Joint Guidelines (JC 2017 37) and the Wolfsberg "
        "DDQ. Industry rubric covers 20+ sectors — arms/defence, crypto "
        "VASP, gambling, mining/extractives, oil & gas, shipping, MSB, "
        "real estate, precious metals, construction, energy trading, "
        "wood/furniture/paper, manufacturing, utilities, regulated banks/"
        "insurers/healthcare, public sector, etc. Volume bands align with "
        "common banking templates ($500k, $5M, $50M, $250M, $1B cut-offs). "
        "Extra-signal logic: any sanctions hit, PEP match, adverse-media H-"
        "grade, critical legal-existence red flag, or UBO discovery gap "
        "auto-bumps the Type of Check one level. Stateless and "
        "explainable — every output includes the rubric text that drove "
        "each score, suitable for audit. Use this as the final step of "
        "a KYC workflow or standalone for rapid 'what check type does "
        "this counterparty need?' decisions."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "cpi_rank": {
                "type": "number",
                "description": "Transparency International CPI rank (1 = cleanest, ~180 = most corrupt). Get via `country_risk_index` tool.",
            },
            "annual_notional_usd": {
                "type": "number",
                "description": "Expected annual contracted volume or notional in USD.",
            },
            "industry_segment": {
                "type": "string",
                "description": (
                    "Industry key — use one of: arms_defence, gambling_casinos, "
                    "crypto_vasp, mining_extractives, oil_gas, shipping_maritime, "
                    "cash_intensive_retail, money_service_business, real_estate, "
                    "precious_metals_stones, construction, telecoms, energy_trading, "
                    "wood_furniture_paper, manufacturing, wholesale_distribution, "
                    "professional_services, agriculture, utility_regulated, "
                    "public_sector, education, healthcare_regulated, technology_saas, "
                    "insurance_regulated, banking_regulated, other. "
                    "Free-text also accepted — we'll fuzzy match."
                ),
            },
            "sanctions_hit": {"type": "boolean", "description": "Has a sanctions match been found?"},
            "pep_match": {"type": "boolean", "description": "Is the counterparty or UBO a PEP / family / associate?"},
            "adverse_media_grade": {
                "type": "string",
                "enum": ["L", "M", "H", "unknown"],
                "description": "Output grade from `adverse_media` tool.",
            },
            "legal_existence_red_flags": {
                "type": "array", "items": {"type": "string"},
                "description": "Red-flag codes from `legal_existence_verifier`.",
            },
            "ubo_discovery_gaps": {
                "type": "integer",
                "description": "Count of unresolved UBO chain gaps.",
            },
        },
        "required": ["cpi_rank", "annual_notional_usd", "industry_segment"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        cpi = arguments.get("cpi_rank")
        vol = arguments.get("annual_notional_usd")
        industry = arguments.get("industry_segment")

        sanctions_hit = bool(arguments.get("sanctions_hit", False))
        pep_match = bool(arguments.get("pep_match", False))
        adverse_grade = (arguments.get("adverse_media_grade") or "unknown").upper()
        legal_flags = arguments.get("legal_existence_red_flags") or []
        ubo_gaps = int(arguments.get("ubo_discovery_gaps") or 0)

        ind_i_score, ind_i_rationale = _indicator_i_score_from_cpi(cpi)
        ind_ii_score, ind_ii_rationale = _indicator_ii_score_from_volume(vol)
        ind_iii_score, ind_iii_rationale = _indicator_iii_score_from_industry(industry)

        aggregate = round(ind_i_score + ind_ii_score + ind_iii_score, 2)

        # Extra signals
        extra_triggers: list[str] = []
        if sanctions_hit:
            extra_triggers.append("Sanctions match present — Enhanced DD mandatory under FATF R.6")
        if pep_match:
            extra_triggers.append("PEP / family / close-associate match — Enhanced DD under FATF R.12")
        if adverse_grade == "H":
            extra_triggers.append("High-grade adverse media — manual legal review recommended")
        critical_legal = {"dissolved_or_struck_off", "no_registry_match"}
        if any(f in critical_legal for f in legal_flags):
            extra_triggers.append("Legal-existence critical red flag — onboarding should be blocked pending manual verification")
        if ubo_gaps >= 2:
            extra_triggers.append("≥2 UBO discovery gaps — require shareholder register copy")

        extra_signals_triggered = bool(extra_triggers)
        check_type = _check_type_from_aggregate(aggregate, extra_signals_triggered)

        # KYC grade
        if sanctions_hit or "dissolved_or_struck_off" in legal_flags:
            grade = "H"
        elif pep_match or adverse_grade == "H" or check_type == "Enhanced":
            grade = "H" if check_type == "Enhanced" else "M"
        elif aggregate >= 45 or adverse_grade == "M":
            grade = "M"
        else:
            grade = "L"

        return ToolResult(
            content=json.dumps({
                "inputs": {
                    "cpi_rank": cpi, "annual_notional_usd": vol,
                    "industry_segment": industry,
                    "sanctions_hit": sanctions_hit, "pep_match": pep_match,
                    "adverse_media_grade": adverse_grade,
                    "legal_existence_red_flags": legal_flags,
                    "ubo_discovery_gaps": ubo_gaps,
                },
                "indicator_i": {"score": ind_i_score, "rationale": ind_i_rationale,
                                 "title": "Country of Domicile Corruption Index Rank"},
                "indicator_ii": {"score": ind_ii_score, "rationale": ind_ii_rationale,
                                  "title": "Annual Contracted Volume / Notional Value"},
                "indicator_iii": {"score": ind_iii_score, "rationale": ind_iii_rationale,
                                   "title": "Industry Segment"},
                "aggregated_score": aggregate,
                "type_of_check": check_type,
                "extra_signal_triggers": extra_triggers,
                "kyc_risk_grade": grade,
                "rubric_version": "2026.04",
                "explainer": (
                    "Aggregated = Indicator I + II + III. Base check type: "
                    "≤15 Simplified, 16-60 Standard, >60 Enhanced. Any "
                    "extra-signal trigger bumps the type one level. KYC "
                    "grade is then the worst of check-type and signal "
                    "severity. Override in firm policy where required."
                ),
            }, indent=2, default=str),
            metadata={"grade": grade, "check_type": check_type, "aggregate": aggregate},
        )
