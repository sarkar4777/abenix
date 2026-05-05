#!/usr/bin/env python3
"""ValueEdge offshore-wind cost calculator.

Reads ONE JSON scenario object on stdin, prints ONE JSON cost block
on stdout. Coefficients track the inline rule-of-thumb path in
iot_valueedge_pipeline.yaml so the UI numbers stay consistent
whether the cost asset is deployed or not.

Input shape (any extra fields are ignored):
    {
      "id": "S1",
      "turbine_count": 13,
      "turbine_rating_mw": 15,
      "foundation_type": "monopile" | "jacket" | "floating-semisub" | "floating-spar",
      "water_depth_m": 28,
      "distance_to_shore_km": 130,
      "array_voltage_kv": 66,
      "export_topology": "HVAC-via-OSS" | "HVDC-monopolar" | ...,
      "offshore_substations": 1
    }

Output shape:
    {
      "id": "S1",
      "capacity_mw": 195.0,
      "capex_musd": 612.4,
      "co2_kt": 290.1,
      "om_annual_musd": 27.1,
      "irr_pct": 9.12,
      "lcoe_usd_mwh": 71.4,
      "breakdown_musd": {"turbines": ..., "foundation": ..., ...}
    }
"""
from __future__ import annotations

import json
import math
import sys

# Per-MW base coefficients (USD-millions per MW unless noted).
# Aligned to the 2026 BNEF/IRENA ranges in the KB ve-knw-006 doc.
_FOUNDATION_BASE = {
    "monopile":         {"capex": 2.85, "co2": 1.55, "om_pct": 0.045},
    "jacket":           {"capex": 3.40, "co2": 1.85, "om_pct": 0.052},
    "floating-semisub": {"capex": 4.20, "co2": 2.30, "om_pct": 0.063},
    "floating-spar":    {"capex": 4.55, "co2": 2.45, "om_pct": 0.066},
}

# CapEx breakdown shares — turbine, foundation, BoS (electrical),
# install, project dev. These shift with foundation choice.
_BREAKDOWN_SHARE = {
    "monopile":         {"turbines": 0.36, "foundation": 0.18, "bos": 0.20, "install": 0.16, "dev": 0.10},
    "jacket":           {"turbines": 0.32, "foundation": 0.24, "bos": 0.19, "install": 0.16, "dev": 0.09},
    "floating-semisub": {"turbines": 0.28, "foundation": 0.30, "bos": 0.18, "install": 0.15, "dev": 0.09},
    "floating-spar":    {"turbines": 0.27, "foundation": 0.32, "bos": 0.17, "install": 0.15, "dev": 0.09},
}

# HVDC export adder — applied to BoS share when distance-to-shore
# justifies it. Ranges from KB ve-knw-006: +0.45–0.70 USD M / MW.
_HVDC_ADDER_PER_MW = 0.55


def _compute(scenario: dict) -> dict:
    n = float(scenario.get("turbine_count") or 0)
    rating = float(scenario.get("turbine_rating_mw") or 0)
    cap_mw = n * rating
    if cap_mw <= 0:
        raise ValueError("turbine_count * turbine_rating_mw must be > 0")

    foundation = scenario.get("foundation_type") or "jacket"
    base = _FOUNDATION_BASE.get(foundation, _FOUNDATION_BASE["jacket"])
    share = _BREAKDOWN_SHARE.get(foundation, _BREAKDOWN_SHARE["jacket"])

    depth = float(scenario.get("water_depth_m") or 30)
    dist = float(scenario.get("distance_to_shore_km") or 60)
    # depth penalty: quadratic-ish above 25 m, ~0 below
    depth_mult = 1.0 + max(0.0, (depth - 25) / 100.0) ** 1.5
    # distance penalty: linear above 50 km
    dist_mult = 1.0 + max(0.0, (dist - 50) / 150.0)

    raw_capex = cap_mw * base["capex"] * depth_mult * dist_mult

    # apply HVDC adder if scenario chose HVDC export
    topology = (scenario.get("export_topology") or "").upper()
    if "HVDC" in topology:
        raw_capex += cap_mw * _HVDC_ADDER_PER_MW

    capex = round(raw_capex, 2)

    # lifecycle CO2 (manufacture + install + decom; excludes operation)
    co2_kt = round(cap_mw * base["co2"] * (1.0 + (depth - 25) / 200.0), 1)

    om_annual = round(capex * base["om_pct"], 2)

    # 4500 full-load-hours typical offshore; price floor 75 USD/MWh
    annual_revenue = cap_mw * 4500 * 75 / 1e6
    net_annual = annual_revenue - om_annual

    rate = _solve_irr(capex, net_annual, years=25)
    lcoe = (capex / 25 + om_annual) / (cap_mw * 4500 / 1000) * 1000

    breakdown = {k: round(capex * v, 2) for k, v in share.items()}

    return {
        "id": scenario.get("id"),
        "capacity_mw": round(cap_mw, 2),
        "capex_musd": capex,
        "co2_kt": co2_kt,
        "om_annual_musd": om_annual,
        "irr_pct": round(rate * 100, 2),
        "lcoe_usd_mwh": round(lcoe, 1),
        "depth_multiplier": round(depth_mult, 3),
        "distance_multiplier": round(dist_mult, 3),
        "breakdown_musd": breakdown,
    }


def _solve_irr(capex: float, net_annual: float, years: int = 25) -> float:
    """Newton-iterate the project IRR for the given annuity profile."""
    r = 0.08
    for _ in range(60):
        npv = -capex + sum(net_annual / (1 + r) ** t for t in range(1, years + 1))
        dnpv = sum(-t * net_annual / (1 + r) ** (t + 1) for t in range(1, years + 1))
        if abs(dnpv) < 1e-9:
            break
        r -= npv / dnpv
        if r < -0.5 or r > 0.6:
            return 0.08
    return r


def main() -> int:
    raw = sys.stdin.read().strip() or "{}"
    try:
        scenario = json.loads(raw)
    except json.JSONDecodeError as exc:
        json.dump({"error": "bad_json", "detail": str(exc)}, sys.stdout)
        return 1
    try:
        result = _compute(scenario)
    except Exception as exc:
        json.dump({"error": "compute_failed", "detail": str(exc)}, sys.stdout)
        return 1
    json.dump({"result": result}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
