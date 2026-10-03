"""Notional volume score — KYC Indicator II, returns a 5-25 score."""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult


def _score_band(usd: float, commodity_factor: float) -> tuple[int, str]:
    """5-25 band mapping for annual contracted volume / notional in USD."""
    v = usd * commodity_factor
    if v < 1_000_000:
        return 5, f"Notional ${usd:,.0f} — immaterial (<$1M)"
    if v < 10_000_000:
        return 10, f"Notional ${usd:,.0f} — small ($1M-$10M)"
    if v < 50_000_000:
        return 15, f"Notional ${usd:,.0f} — medium ($10M-$50M)"
    if v < 250_000_000:
        return 20, f"Notional ${usd:,.0f} — large ($50M-$250M)"
    return 25, f"Notional ${usd:,.0f} — material (>$250M)"


# Multiplier on USD notional for higher-risk commodities. Trade-finance sectors
# with structural sanctions / dual-use exposure are weighted up so a smaller
# absolute notional still maps to a higher KYC band.
_COMMODITY_FACTORS: dict[str, float] = {
    "arms": 2.5,
    "weapons": 2.5,
    "dual_use": 2.0,
    "crypto": 1.6,
    "precious_metals": 1.6,
    "oil": 1.3,
    "gas": 1.3,
    "lng": 1.3,
    "energy": 1.0,
    "power": 1.0,
    "wood": 1.0,
    "furniture": 1.0,
    "paper": 1.0,
    "metals": 1.1,
    "agri": 1.0,
    "services": 0.9,
    "saas": 0.8,
    "": 1.0,
}


def _commodity_factor(label: str) -> tuple[float, str]:
    if not label:
        return 1.0, ""
    s = label.lower()
    for k, f in _COMMODITY_FACTORS.items():
        if k and k in s:
            return f, k
    return 1.0, ""


class NotionalVolumeScoreTool(BaseTool):
    name = "notional_volume_score"
    risk_tier = "low"
    description = (
        "Pure-function KYC Indicator II tool. Takes annual contracted volume "
        "or notional in USD plus an optional commodity label and returns an "
        "integer 5-25 score, a rationale, and the band cut-off used. Bands: "
        "<$1M=5, $1-10M=10, $10-50M=15, $50-250M=20, >$250M=25. A small set of "
        "higher-risk commodities (arms, dual-use, crypto, precious metals, "
        "oil & gas) get a multiplier so a smaller absolute notional still maps "
        "to a higher KYC band. No external calls; deterministic and explainable."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "annual_notional_usd": {
                "type": "number",
                "description": "Expected annual contracted volume or notional, in USD.",
            },
            "commodity": {
                "type": "string",
                "description": "Optional free-text commodity / product (e.g. 'LNG', 'wood', 'arms').",
            },
        },
        "required": ["annual_notional_usd"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            usd = float(arguments.get("annual_notional_usd") or 0)
        except (TypeError, ValueError):
            return ToolResult(
                content="Error: 'annual_notional_usd' must be a number.", is_error=True
            )
        if usd < 0:
            return ToolResult(
                content="Error: 'annual_notional_usd' must be non-negative.",
                is_error=True,
            )
        commodity = (arguments.get("commodity") or "").strip()
        factor, factor_key = _commodity_factor(commodity)
        score, rationale = _score_band(usd, factor)
        out = {
            "annual_notional_usd": usd,
            "commodity": commodity,
            "commodity_factor": factor,
            "commodity_factor_match": factor_key,
            "score": score,
            "rationale": rationale,
            "band_cutoffs_usd": {
                "5": "<$1M",
                "10": "$1M-$10M",
                "15": "$10M-$50M",
                "20": "$50M-$250M",
                "25": ">$250M",
            },
            "source_citation": "MET KYC Indicator II ladder (5-25)",
        }
        return ToolResult(content=json.dumps(out, indent=2), metadata={"score": score})
