"""Risk-tier predictor for ContractIQ.

Maps a contract's structural features to a four-level deal risk tier:
low / medium / high / critical. Used by the hedge_advisor + market-risk
agents as a coarse upfront screen before they decide whether to run a
full VaR + scenario sweep. Cheap to call, easy to override.

Features (all numeric; pulled from the contract's extracted JSON):
    notional_usd               face value of the deal in USD
    tenor_years                contract length in years
    tolerance_pct              ±band on scheduled quantity
    indexation_strength        0..1, fraction of price linked to an index
    counterparty_rating_num    1=AAA .. 10=NR
    credit_support_ratio       LC value / 90-day MTM (0 if unsecured)
    force_majeure_clarity      0..1, how clear the FM trigger language is
    governing_law_friction     0..1, hostile-jurisdiction penalty
    has_take_or_pay            0 / 1
    market_volatility_z        12m realised vol of the underlying

Output: tier label + calibrated probabilities. The agent treats the
return as a soft prior and asks the trader (or the rules engine) to
confirm before acting.

Output:
    contractiq/aimodels/risk_tier_predictor.pkl
    contractiq/aimodels/risk_tier_predictor.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "notional_usd",
    "tenor_years",
    "tolerance_pct",
    "indexation_strength",
    "counterparty_rating_num",
    "credit_support_ratio",
    "force_majeure_clarity",
    "governing_law_friction",
    "has_take_or_pay",
    "market_volatility_z",
]


def _label(features: dict[str, float]) -> str:
    """Heuristic scoring used to label the synthetic corpus. Real
    deployments retrain from approved hedge_advisor outputs once enough
    labelled history accumulates."""
    score = 0.0
    score += np.log1p(features["notional_usd"]) / 30.0          # bigger = riskier
    score += features["tenor_years"] / 25.0                       # longer = riskier
    score += features["counterparty_rating_num"] / 12.0           # weaker = riskier
    score += features["governing_law_friction"] * 0.6
    score += (1.0 - features["credit_support_ratio"]) * 0.4
    score += (1.0 - features["force_majeure_clarity"]) * 0.3
    score += features["market_volatility_z"] / 5.0
    score += features["indexation_strength"] * 0.2
    score -= features["tolerance_pct"] / 50.0                     # bigger tolerance reduces fragility
    if features["has_take_or_pay"] > 0.5:
        score += 0.15
    # Bin
    if score < 0.55: return "low"
    if score < 0.85: return "medium"
    if score < 1.15: return "high"
    return "critical"


def _sample(rng: np.random.Generator) -> dict[str, float]:
    return {
        "notional_usd": float(rng.lognormal(mean=14.5, sigma=1.3)),
        "tenor_years": float(rng.uniform(0.5, 25.0)),
        "tolerance_pct": float(rng.uniform(0.0, 25.0)),
        "indexation_strength": float(rng.beta(2, 5)),
        "counterparty_rating_num": float(rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], p=[.05,.10,.20,.20,.18,.10,.07,.05,.03,.02])),
        "credit_support_ratio": float(rng.beta(3, 4)),
        "force_majeure_clarity": float(rng.beta(5, 2)),
        "governing_law_friction": float(rng.beta(2, 5)),
        "has_take_or_pay": float(rng.choice([0.0, 1.0], p=[0.65, 0.35])),
        "market_volatility_z": float(rng.normal(0.0, 1.0)),
    }


def _generate(rng: np.random.Generator, n: int):
    X = np.zeros((n, len(FEATURE_NAMES)))
    y = np.empty(n, dtype=object)
    for i in range(n):
        feats = _sample(rng)
        X[i] = [feats[f] for f in FEATURE_NAMES]
        y[i] = _label(feats)
    return X, y


def train_and_save() -> None:
    rng = np.random.default_rng(20260522)
    X, y = _generate(rng, n=1500)

    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("clf", CalibratedClassifierCV(GradientBoostingClassifier(n_estimators=200, max_depth=3, random_state=42), cv=3)),
    ])
    pipe.fit(X, y)

    rng_eval = np.random.default_rng(424242)
    Xe, ye = _generate(rng_eval, n=600)
    score = float(pipe.score(Xe, ye))

    out_pkl = OUT / "risk_tier_predictor.pkl"
    out_meta = OUT / "risk_tier_predictor.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(pipe, f)

    classes = sorted(set(y.tolist()))
    meta = {
        "name": "contractiq-risk-tier-predictor",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Calibrated Gradient Boosting classifier that maps a contract's "
            "10 structural features (notional, tenor, tolerance, indexation, "
            "counterparty rating, credit support, force-majeure clarity, "
            "governing-law friction, take-or-pay flag, market volatility) "
            "into a four-level deal risk tier. The hedge_advisor agent calls "
            "this as a fast prior before deciding whether to run a full VaR "
            "+ scenario sweep, and the market-risk dashboard shows it next "
            "to the analytical VaR number so the operator can see when the "
            "ML prior disagrees with the parametric model."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [50_000_000, 5.0, 10.0, 0.4, 4, 0.5, 0.8, 0.2, 1, 0.5],
        },
        "output_schema": {
            "type": "classification",
            "classes": classes,
            "returns": "tier label + calibrated probabilities",
        },
        "tags": ["contractiq", "risk", "tier", "hedge-advisor"],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "StandardScaler -> CalibratedClassifierCV(GradientBoostingClassifier)",
            "synthetic": True,
            "holdout_accuracy": round(score, 4),
            "classes": classes,
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Holdout accuracy: {score:.4f}  classes: {classes}")


if __name__ == "__main__":
    train_and_save()
