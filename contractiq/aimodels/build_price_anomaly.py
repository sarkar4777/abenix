"""Contract price-anomaly detector for ContractIQ.

IsolationForest over the residual between a contract's strike price and
the market-implied fair value. Flags deals that look mispriced versus
their cohort. Used by the valuator agent and surfaced on the market
board as a side rail next to the analytical VaR + PV figures.

Features:
    log_notional               ln(notional_usd)
    tenor_years                contract length
    price_residual_pct         (strike - implied_fair) / implied_fair
    forward_curve_slope        12m forward minus spot, normalised
    vol_z                      realised vol z-score
    counterparty_rating_num    1=AAA .. 10=NR
    indexation_strength        0..1
    has_take_or_pay            0 / 1

The synthetic training set is 90% in-distribution + 10% deliberately
mispriced rows so IsolationForest learns the manifold. Score returns
between -0.5 (very anomalous) and +0.5 (typical).

Output:
    contractiq/aimodels/price_anomaly.pkl
    contractiq/aimodels/price_anomaly.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "log_notional",
    "tenor_years",
    "price_residual_pct",
    "forward_curve_slope",
    "vol_z",
    "counterparty_rating_num",
    "indexation_strength",
    "has_take_or_pay",
]


def _sample_in(rng: np.random.Generator) -> np.ndarray:
    """Typical row. Price residual is small and centred on zero."""
    return np.array([
        rng.normal(16.5, 1.2),
        rng.uniform(0.5, 20.0),
        rng.normal(0.0, 0.03),
        rng.normal(0.02, 0.04),
        rng.normal(0.0, 1.0),
        rng.choice([1, 2, 3, 4, 5, 6], p=[.10,.20,.25,.20,.15,.10]),
        rng.beta(2, 5),
        rng.choice([0.0, 1.0], p=[0.65, 0.35]),
    ], dtype=np.float64)


def _sample_out(rng: np.random.Generator) -> np.ndarray:
    """Mispriced or anomalous row."""
    return np.array([
        rng.normal(16.5, 2.5),
        rng.uniform(0.1, 25.0),
        rng.normal(0.0, 0.18),                 # MUCH wider residual
        rng.normal(0.0, 0.15),
        rng.normal(0.0, 2.5),
        rng.choice([7, 8, 9, 10], p=[.30,.30,.25,.15]),
        rng.beta(1, 1),
        rng.choice([0.0, 1.0], p=[0.50, 0.50]),
    ], dtype=np.float64)


def _generate(rng: np.random.Generator, n: int):
    X = np.zeros((n, len(FEATURE_NAMES)))
    for i in range(n):
        X[i] = _sample_out(rng) if rng.random() < 0.10 else _sample_in(rng)
    return X


def train_and_save() -> None:
    rng = np.random.default_rng(20260522)
    X = _generate(rng, n=3000)

    iforest = IsolationForest(
        n_estimators=200,
        contamination=0.10,
        random_state=42,
        n_jobs=-1,
    )
    iforest.fit(X)

    # Eval split. Use score_samples as a proxy for separating in vs out.
    rng_eval = np.random.default_rng(123)
    Xin = np.array([_sample_in(rng_eval) for _ in range(500)])
    Xout = np.array([_sample_out(rng_eval) for _ in range(200)])
    sc_in = iforest.score_samples(Xin)
    sc_out = iforest.score_samples(Xout)
    # AUC-style separation: fraction of out-of-distribution rows scored lower than the in-dist median
    threshold = float(np.median(sc_in))
    detected_out = float((sc_out < threshold).mean())

    out_pkl = OUT / "price_anomaly.pkl"
    out_meta = OUT / "price_anomaly.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(iforest, f)

    meta = {
        "name": "contractiq-price-anomaly",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "IsolationForest anomaly detector for contract prices. Trains on "
            "the joint distribution of 8 features (log notional, tenor, "
            "price residual vs implied fair value, curve slope, realised "
            "vol z-score, counterparty rating, indexation strength, take-or-"
            "pay flag) with 10% planted outliers. The valuator agent calls "
            "this after computing the analytical fair value: if the score "
            "is anomalous AND the residual sign is unfavourable, the result "
            "card lights up red and a hedge_advisor follow-up is queued."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [16.5, 5.0, 0.02, 0.03, 0.5, 3, 0.4, 1.0],
        },
        "output_schema": {
            "type": "anomaly",
            "returns": "score (higher = more typical), is_anomaly bool (score < threshold)",
        },
        "tags": ["contractiq", "valuation", "anomaly", "price-deviation"],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "IsolationForest (200 trees, contamination=0.10)",
            "synthetic": True,
            "planted_outlier_recall": round(detected_out, 4),
            "threshold_at_median": round(threshold, 4),
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Planted-outlier recall: {detected_out:.4f}")


if __name__ == "__main__":
    train_and_save()
