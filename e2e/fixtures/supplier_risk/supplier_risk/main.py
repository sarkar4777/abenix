"""Supplier risk scorer.

Reads {"suppliers": [{"name", "current_ratio", "debt_to_equity",
"on_time_delivery_pct", "single_source", "country_risk"}]} on stdin and
writes {"scored": [...], "portfolio": {...}} on stdout. Standard library only.
"""

import json
import sys

WEIGHTS = {"liquidity": 0.30, "leverage": 0.25, "delivery": 0.25, "concentration": 0.10, "country": 0.10}
COUNTRY = {"low": 0.0, "medium": 0.5, "high": 1.0}


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score(s: dict) -> dict:
    cr = float(s.get("current_ratio", 1.0))
    de = float(s.get("debt_to_equity", 1.0))
    otd = float(s.get("on_time_delivery_pct", 95.0))
    parts = {
        "liquidity": clamp((1.5 - cr) / 1.0),
        "leverage": clamp((de - 0.5) / 2.0),
        "delivery": clamp((98.0 - otd) / 15.0),
        "concentration": 1.0 if s.get("single_source") else 0.0,
        "country": COUNTRY.get(str(s.get("country_risk", "low")).lower(), 0.5),
    }
    total = round(100 * sum(WEIGHTS[k] * v for k, v in parts.items()), 1)
    tier = "red" if total >= 60 else "amber" if total >= 35 else "green"
    drivers = sorted(parts, key=lambda k: WEIGHTS[k] * parts[k], reverse=True)[:2]
    return {"name": s.get("name", "unknown"), "risk_score": total, "tier": tier, "top_drivers": drivers}


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    payload = json.loads(raw)
    suppliers = payload.get("suppliers") or []
    scored = sorted((score(s) for s in suppliers), key=lambda r: r["risk_score"], reverse=True)
    tiers = {t: sum(1 for r in scored if r["tier"] == t) for t in ("red", "amber", "green")}
    out = {
        "scored": scored,
        "portfolio": {
            "count": len(scored),
            "tiers": tiers,
            "highest": scored[0]["name"] if scored else None,
            "marker": "SUPPLIER_RISK_ENGINE_V1",
        },
    }
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()
