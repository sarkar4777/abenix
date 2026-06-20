"""Industry segment risk lookup — maps any NACE/NAICS-style label to a 5-25 score."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# Calibrated lookup table. Score is 5-25 (clamped to align all three KYC
# indicators on the same scale). Rationale text references the published source
# (FATF NRA, Basel AML Index, Wolfsberg sector ratings).
_INDUSTRY_TABLE: dict[str, dict[str, Any]] = {
    "arms_defence": {
        "score": 25,
        "fatf_class": "very_high",
        "rationale": "Arms & defence — extreme sanctions and end-user-control exposure",
        "source_citation": "FATF NRA Section 4 + Wolfsberg DDQ 2022",
        "source_url": "https://www.fatf-gafi.org/en/topics/proliferation-financing.html",
        "aliases": ["arms", "defence", "defense", "weapons", "military equipment"],
        "nace_codes": ["25.40", "30.40"],
    },
    "gambling_casinos": {
        "score": 24,
        "fatf_class": "very_high",
        "rationale": "Gambling / casinos — cash-intensive, high STR rate (FATF R.22)",
        "source_citation": "FATF Casinos Guidance 2019",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Rba-casinos.html",
        "aliases": ["casino", "gambling", "betting", "gaming"],
        "nace_codes": ["92.00"],
    },
    "crypto_vasp": {
        "score": 24,
        "fatf_class": "very_high",
        "rationale": "Virtual Asset Service Provider — FATF R.15 enhanced DD mandatory",
        "source_citation": "FATF Recommendation 15 Guidance 2021",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Guidance-rba-virtual-assets-2021.html",
        "aliases": ["crypto", "vasp", "virtual asset", "bitcoin", "exchange digital"],
        "nace_codes": ["64.99"],
    },
    "money_service_business": {
        "score": 24,
        "fatf_class": "very_high",
        "rationale": "MSB / money remitter — FATF-designated higher risk",
        "source_citation": "FATF Guidance MVTS 2016",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Rba-money-value-transfer-services.html",
        "aliases": ["msb", "money service", "remittance", "money transmitter"],
        "nace_codes": ["64.19"],
    },
    "precious_metals_stones": {
        "score": 22,
        "fatf_class": "high",
        "rationale": "Precious metals/stones — DPMS designated by FATF R.22",
        "source_citation": "FATF DPMS Guidance",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Rba-dealers-precious-metal-stones.html",
        "aliases": ["dpms", "precious metals", "gold dealer", "diamond"],
        "nace_codes": ["47.77"],
    },
    "mining_extractives": {
        "score": 21,
        "fatf_class": "high",
        "rationale": "Mining / extractives — Transparency PWYP exposure",
        "source_citation": "EITI Standard 2023",
        "source_url": "https://eiti.org/eiti-standard",
        "aliases": ["mining", "extractive", "minerals", "metal mining"],
        "nace_codes": ["07", "08"],
    },
    "oil_gas": {
        "score": 20,
        "fatf_class": "high",
        "rationale": "Oil & gas — sanctions and corruption exposure (FCPA-prone)",
        "source_citation": "OECD Bribery Convention monitoring",
        "source_url": "https://www.oecd.org/corruption/oecdantibriberyconvention.htm",
        "aliases": ["oil", "gas", "petroleum", "upstream", "lng", "midstream"],
        "nace_codes": ["06"],
    },
    "shipping_maritime": {
        "score": 20,
        "fatf_class": "high",
        "rationale": "Shipping — flag-of-convenience and sanctions-evasion vector",
        "source_citation": "OFAC Maritime Advisory 2020",
        "source_url": "https://ofac.treasury.gov/media/1186/download?inline",
        "aliases": ["shipping", "maritime", "tanker", "vessel"],
        "nace_codes": ["50"],
    },
    "cash_intensive_retail": {
        "score": 19,
        "fatf_class": "high",
        "rationale": "Cash-intensive retail — placement-stage layering risk",
        "source_citation": "Wolfsberg DDQ Annex 2",
        "source_url": "https://www.wolfsberg-principles.com/wolfsberg-group-correspondent-banking-due-diligence-questionnaire-cbddq",
        "aliases": ["cash retail", "convenience store"],
        "nace_codes": ["47"],
    },
    "real_estate": {
        "score": 18,
        "fatf_class": "high",
        "rationale": "Real estate — FATF NRA flags layering via property",
        "source_citation": "FATF Real Estate Guidance 2022",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Guidance-rba-real-estate-sector.html",
        "aliases": ["real estate", "property", "construction broker"],
        "nace_codes": ["41", "68"],
    },
    "construction": {
        "score": 17,
        "fatf_class": "medium",
        "rationale": "Construction — sub-contractor and invoice fraud risk",
        "source_citation": "Basel AML Index 2024",
        "source_url": "https://index.baselgovernance.org/",
        "aliases": ["construction", "civil works", "infrastructure builder"],
        "nace_codes": ["41", "42", "43"],
    },
    "wood_furniture_paper": {
        "score": 16,
        "fatf_class": "medium",
        "rationale": "Wood, furniture & paper manufacturing — moderate baseline",
        "source_citation": "Internal calibration based on FATF guidance",
        "source_url": "https://www.fatf-gafi.org/en/publications/Methodsandtrends.html",
        "aliases": ["wood", "furniture", "paper", "lumber", "timber", "pulp"],
        "nace_codes": ["16", "17", "31"],
    },
    "energy_trading": {
        "score": 16,
        "fatf_class": "medium",
        "rationale": "Energy trading — moderate baseline (commodity-trading exposure)",
        "source_citation": "Internal calibration based on FATF guidance",
        "source_url": "https://www.fatf-gafi.org/en/publications/Methodsandtrends/Documents/Trade-based-money-laundering.html",
        "aliases": ["energy trading", "power trading", "commodity trading energy"],
        "nace_codes": ["35", "46.71"],
    },
    "manufacturing": {
        "score": 14,
        "fatf_class": "medium",
        "rationale": "General manufacturing — moderate baseline risk",
        "source_citation": "Basel AML Index 2024",
        "source_url": "https://index.baselgovernance.org/",
        "aliases": ["manufacturing", "industrial production"],
        "nace_codes": [
            "10",
            "11",
            "13",
            "14",
            "15",
            "16",
            "17",
            "18",
            "19",
            "20",
            "21",
            "22",
            "23",
            "24",
            "25",
            "26",
            "27",
            "28",
            "29",
            "30",
            "31",
            "32",
            "33",
        ],
    },
    "wholesale_distribution": {
        "score": 14,
        "fatf_class": "medium",
        "rationale": "Wholesale / distribution — moderate trade-finance exposure",
        "source_citation": "Wolfsberg Trade Finance Principles",
        "source_url": "https://www.wolfsberg-principles.com/wolfsberg-trade-finance-principles",
        "aliases": ["wholesale", "distribution", "trading company"],
        "nace_codes": ["46"],
    },
    "professional_services": {
        "score": 12,
        "fatf_class": "medium",
        "rationale": "Professional services — moderate gatekeeper risk",
        "source_citation": "FATF Lawyer/Accountant Guidance",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Rba-legal-professionals.html",
        "aliases": ["professional services", "consulting", "law firm", "accounting"],
        "nace_codes": ["69", "70", "71"],
    },
    "agriculture": {
        "score": 11,
        "fatf_class": "medium",
        "rationale": "Agriculture / agri-commodities — moderate baseline",
        "source_citation": "Basel AML Index 2024",
        "source_url": "https://index.baselgovernance.org/",
        "aliases": ["agriculture", "farming", "agri", "crop"],
        "nace_codes": ["01", "02", "03"],
    },
    "telecoms": {
        "score": 11,
        "fatf_class": "medium",
        "rationale": "Telecoms — moderate PEP and sanctions exposure",
        "source_citation": "Wolfsberg DDQ Annex 2",
        "source_url": "https://www.wolfsberg-principles.com/wolfsberg-group-correspondent-banking-due-diligence-questionnaire-cbddq",
        "aliases": ["telecom", "telco", "mobile network"],
        "nace_codes": ["61"],
    },
    "technology_saas": {
        "score": 9,
        "fatf_class": "low",
        "rationale": "Technology / SaaS — lower baseline risk",
        "source_citation": "Wolfsberg DDQ Annex 2",
        "source_url": "https://www.wolfsberg-principles.com/wolfsberg-group-correspondent-banking-due-diligence-questionnaire-cbddq",
        "aliases": ["technology", "saas", "software", "tech", "it services"],
        "nace_codes": ["62", "63"],
    },
    "banking_regulated": {
        "score": 9,
        "fatf_class": "low",
        "rationale": "Regulated bank — subject to prudential AML supervision",
        "source_citation": "Basel Core Principles",
        "source_url": "https://www.bis.org/bcbs/publ/d563.htm",
        "aliases": ["bank", "banking", "credit institution"],
        "nace_codes": ["64.19"],
    },
    "insurance_regulated": {
        "score": 8,
        "fatf_class": "low",
        "rationale": "Regulated insurance — subject to IAIS standards",
        "source_citation": "IAIS ICP 22",
        "source_url": "https://www.iaisweb.org/uploads/2022/01/191115-IAIS-ICPs-and-ComFrame-adopted-in-November-2019.pdf",
        "aliases": ["insurance", "insurer", "reinsurance"],
        "nace_codes": ["65"],
    },
    "utility_regulated": {
        "score": 7,
        "fatf_class": "low",
        "rationale": "Regulated utility — subject to national oversight",
        "source_citation": "Internal calibration based on FATF guidance",
        "source_url": "https://www.fatf-gafi.org/en/topics/methods-and-trends.html",
        "aliases": ["utility", "water utility", "regulated power"],
        "nace_codes": ["35", "36"],
    },
    "healthcare_regulated": {
        "score": 7,
        "fatf_class": "low",
        "rationale": "Regulated healthcare — subject to medical oversight",
        "source_citation": "Wolfsberg DDQ Annex 2",
        "source_url": "https://www.wolfsberg-principles.com/wolfsberg-group-correspondent-banking-due-diligence-questionnaire-cbddq",
        "aliases": ["healthcare", "hospital", "medical"],
        "nace_codes": ["86", "87", "88"],
    },
    "education": {
        "score": 6,
        "fatf_class": "low",
        "rationale": "Education — lower baseline risk",
        "source_citation": "Internal calibration based on FATF guidance",
        "source_url": "https://www.fatf-gafi.org/en/topics/methods-and-trends.html",
        "aliases": ["education", "school", "university"],
        "nace_codes": ["85"],
    },
    "public_sector": {
        "score": 5,
        "fatf_class": "low",
        "rationale": "Public sector / government-owned entity",
        "source_citation": "FATF PEP Guidance 2013",
        "source_url": "https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Peps-r12-r22.html",
        "aliases": ["government", "public sector", "ministry", "agency state"],
        "nace_codes": ["84"],
    },
    "other": {
        "score": 13,
        "fatf_class": "medium",
        "rationale": "Other / unclassified — default mid-band",
        "source_citation": "Internal calibration based on FATF guidance",
        "source_url": "https://www.fatf-gafi.org/en/topics/methods-and-trends.html",
        "aliases": [],
        "nace_codes": [],
    },
}


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _match_industry(label: str) -> tuple[str, dict[str, Any]]:
    """Best-effort fuzzy match against the table — specific wins over general."""
    if not label:
        return "other", _INDUSTRY_TABLE["other"]
    key = _normalise(label)
    # Exact key match
    if key in _INDUSTRY_TABLE:
        return key, _INDUSTRY_TABLE[key]
    # Try NACE code
    nace_match = re.match(r"^(\d{2})\.?(\d{2})?$", label.strip())
    if nace_match:
        prefix = nace_match.group(1)
        for k, v in _INDUSTRY_TABLE.items():
            if any(c.split(".")[0] == prefix for c in v.get("nace_codes", [])):
                return k, v
    label_lc = label.lower()
    # Score-weighted alias match: each alias scores by length, but a multi-word
    # match (e.g. "wood furniture paper") beats a single generic word ("manufacturing")
    # even though both substrings are present. Prefer aliases with more matched tokens.
    best_score = 0.0
    best_key = "other"
    for k, v in _INDUSTRY_TABLE.items():
        for alias in v.get("aliases", []) + [k.replace("_", " ")]:
            al = alias.lower().strip()
            if not al:
                continue
            tokens = al.split()
            hit_tokens = [t for t in tokens if t in label_lc]
            if hit_tokens:
                # token-multiplier: prefer aliases where MORE of their tokens land.
                s = sum(len(t) for t in hit_tokens) * len(hit_tokens)
                if s > best_score:
                    best_score = s
                    best_key = k
    if best_key != "other":
        return best_key, _INDUSTRY_TABLE[best_key]
    return "other", _INDUSTRY_TABLE["other"]


class IndustrySegmentRiskTool(BaseTool):
    name = "industry_segment_risk"
    description = (
        "Look up the AML/KYC risk weight for any industry segment string. "
        "Accepts free-text labels (e.g. 'Wood, Furniture & Paper Manufacturing'), "
        "the internal enum keys used by kyc_scorer (e.g. 'wood_furniture_paper'), "
        "or NACE codes (e.g. '16.10'). Returns a 5-25 score, FATF class "
        "(low/medium/high/very_high), one-line rationale, and source citation "
        "(FATF NRA, Basel AML Index, Wolfsberg DDQ). Used as KYC Indicator III "
        "and by any sector-risk-rating flow. Pure function — no network calls."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "industry_segment": {
                "type": "string",
                "description": "Free-text industry label, kyc_scorer enum key, or NACE code.",
            },
            "list_all": {
                "type": "boolean",
                "description": "If true, return the full catalogue (keys, labels, scores, fatf_class, source_url) instead of matching a single segment.",
            },
        },
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if arguments.get("list_all"):
            industries: list[dict[str, Any]] = []
            for k, row in _INDUSTRY_TABLE.items():
                rationale = (row.get("rationale") or "").strip()
                label = rationale.split(" — ")[0].strip() or k.replace("_", " ").title()
                industries.append(
                    {
                        "key": k,
                        "label": label,
                        "score": int(row.get("score", 0)),
                        "fatf_class": row.get("fatf_class"),
                        "source_url": row.get("source_url"),
                    }
                )
            return ToolResult(
                content=json.dumps({"industries": industries}, indent=2),
                metadata={"count": len(industries)},
            )

        label = (arguments.get("industry_segment") or "").strip()
        if not label:
            return ToolResult(
                content="Error: 'industry_segment' is required.", is_error=True
            )
        key, rec = _match_industry(label)
        out = {
            "input": label,
            "matched_key": key,
            "score": int(rec["score"]),
            "fatf_class": rec["fatf_class"],
            "rationale": rec["rationale"],
            "source_citation": rec["source_citation"],
            "source_url": rec.get("source_url"),
            "nace_codes": rec.get("nace_codes", []),
            "matched_via_fallback": key == "other"
            and _normalise(label) not in _INDUSTRY_TABLE,
        }
        return ToolResult(
            content=json.dumps(out, indent=2),
            metadata={"score": int(rec["score"]), "fatf_class": rec["fatf_class"]},
        )
