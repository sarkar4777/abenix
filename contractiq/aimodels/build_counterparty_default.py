"""Counterparty probability-of-default model for ContractIQ.

Logistic regression that scores a counterparty's 12-month probability of
default given financial-ratio inputs plus a sector code. Used by the
credit_risk agent as a fast pre-screen before it runs the full sanctions
+ KYC + adverse-media sweep. Returns a calibrated probability between 0
and 1 with a four-level rating (investment / speculative / sub-IG / distressed).

Features:
    debt_to_equity            total debt / equity
    interest_coverage         EBITDA / interest expense
    current_ratio             current assets / current liabilities
    quick_ratio               (current assets - inventory) / current liabilities
    return_on_assets          net income / total assets
    revenue_growth_yoy        last-12m revenue growth %
    altman_z                  Altman Z-score
    sector_oilgas             1 if oil & gas, else 0
    sector_power              1 if power utility, else 0
    sector_metals             1 if metals refiner, else 0
    is_public                 1 if listed equity, else 0

Output: PD float [0,1] + rating bucket.

Output:
    contractiq/aimodels/counterparty_default.pkl
    contractiq/aimodels/counterparty_default.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "debt_to_equity",
    "interest_coverage",
    "current_ratio",
    "quick_ratio",
    "return_on_assets",
    "revenue_growth_yoy",
    "altman_z",
    "sector_oilgas",
    "sector_power",
    "sector_metals",
    "is_public",
]


def _label(f: dict[str, float]) -> int:
    """Synthetic ground truth based on Altman-style logic. 1 = default
    within 12m, 0 = no default. The classifier learns this without ever
    seeing the formula directly."""
    score = 0.0
    score -= f["altman_z"] * 0.55
    score += max(0.0, f["debt_to_equity"] - 2.5) * 0.45
    score -= min(8.0, f["interest_coverage"]) * 0.20
    score -= max(0.0, f["current_ratio"] - 0.5) * 0.25
    score -= f["return_on_assets"] * 1.4
    score -= f["revenue_growth_yoy"] * 0.05
    score -= 0.4 if f["is_public"] else 0.0
    # Sector adjustments
    score += 0.3 if f["sector_oilgas"] else 0.0
    score -= 0.1 if f["sector_power"] else 0.0
    # Logistic prob
    p = 1.0 / (1.0 + np.exp(-score))
    return 1 if np.random.random() < p else 0


def _sample(rng: np.random.Generator) -> dict[str, float]:
    sector = rng.choice(["oilgas", "power", "metals", "other"], p=[0.35, 0.25, 0.20, 0.20])
    return {
        "debt_to_equity": float(rng.gamma(2.5, 0.7)),
        "interest_coverage": float(rng.gamma(3.0, 1.5)),
        "current_ratio": float(rng.gamma(2.0, 0.6)),
        "quick_ratio": float(rng.gamma(2.0, 0.4)),
        "return_on_assets": float(rng.normal(0.03, 0.08)),
        "revenue_growth_yoy": float(rng.normal(0.05, 0.15)),
        "altman_z": float(rng.normal(2.2, 1.0)),
        "sector_oilgas": 1.0 if sector == "oilgas" else 0.0,
        "sector_power": 1.0 if sector == "power" else 0.0,
        "sector_metals": 1.0 if sector == "metals" else 0.0,
        "is_public": float(rng.choice([0.0, 1.0], p=[0.40, 0.60])),
    }


def _generate(rng: np.random.Generator, n: int):
    X = np.zeros((n, len(FEATURE_NAMES)))
    y = np.zeros(n, dtype=int)
    np.random.seed(int(rng.integers(0, 2**31)))
    for i in range(n):
        feats = _sample(rng)
        X[i] = [feats[f] for f in FEATURE_NAMES]
        y[i] = _label(feats)
    return X, y


def train_and_save() -> None:
    rng = np.random.default_rng(20260522)
    X, y = _generate(rng, n=4000)

    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, C=0.6)),
    ])
    pipe.fit(X, y)

    rng_eval = np.random.default_rng(909)
    Xe, ye = _generate(rng_eval, n=1500)
    score = float(pipe.score(Xe, ye))
    base_rate = float(y.mean())

    out_pkl = OUT / "counterparty_default.pkl"
    out_meta = OUT / "counterparty_default.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(pipe, f)

    meta = {
        "name": "contractiq-counterparty-default",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Logistic-regression PD model. Given 7 financial ratios + 3 "
            "sector flags + a public/private flag, returns a calibrated "
            "12-month probability of default and a four-level rating bucket "
            "(investment / speculative / sub-IG / distressed). The "
            "credit_risk agent calls this BEFORE running sanctions / PEP / "
            "adverse-media so cheap counterparties get screened fast and "
            "expensive deep-checks only run on suspect names."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [1.5, 4.0, 1.2, 0.8, 0.06, 0.08, 3.5, 1, 0, 0, 1],
        },
        "output_schema": {
            "type": "binary_classification",
            "classes": [0, 1],
            "returns": "P(default within 12m); rating bucket derived from probability bands",
        },
        "tags": ["contractiq", "credit-risk", "counterparty", "pd"],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "StandardScaler -> Logistic Regression",
            "synthetic": True,
            "holdout_accuracy": round(score, 4),
            "base_default_rate": round(base_rate, 4),
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Holdout accuracy: {score:.4f}  base_rate: {base_rate:.4f}")


if __name__ == "__main__":
    train_and_save()
