"""Train and pickle the Wingman corridor-spread fair-value model.

A Bayesian Ridge regression that predicts the *fair-value spread*
(destination spot − origin spot − freight, in $/MT) for an LPG propane
corridor, given an 8-feature vector. The model returns a posterior
mean PLUS a posterior standard deviation, which is what makes the
residual-z-score test in the Wingman Mispricing Lens work.

Features (8):
    origin_spot_z        z-score of origin hub spot vs 12-week mean
    dest_spot_z          z-score of destination hub spot vs 12-week mean
    freight_per_mt_z     z-score of bunker-derived freight vs 12-week mean
    inventory_z          z-score of EIA US propane stocks vs 5-yr seasonal
    exports_4w_pct       4-week change in USGC propane export volume (pct)
    fx_eur_usd_z         z-score of EUR/USD vs 12-week mean
    weather_dest_gust_z  z-score of destination-hub 7-day max gust
    season_q             quarter-of-year (1..4), used as a dummy proxy

Target:
    spread_usd_mt        destination_spot - origin_spot - freight_per_mt

Output:
    wingman/ml-models/mispricing_fairvalue.pkl
    wingman/ml-models/mispricing_fairvalue.meta.json

Note: training data is synthetic but built around three "regimes" the
desk would recognise — calm balance, USGC export surge (wider spread),
NWE demand softening (compressed spread) — with a sinusoidal seasonality
overlay. Production engagements should re-train on customer history
(point this script at a real CSV and re-run).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.linear_model import BayesianRidge

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "origin_spot_z",
    "dest_spot_z",
    "freight_per_mt_z",
    "inventory_z",
    "exports_4w_pct",
    "fx_eur_usd_z",
    "weather_dest_gust_z",
    "season_q",
]

# Three regimes the desk would recognise. Mean vectors over the 8 features
# (z-scores ~ N(0,1), season is uniform 1..4). Each regime has a different
# spread mean so the model learns a meaningful coefficient structure.
REGIMES = [
    {
        "name": "calm_balance",
        "n": 380,
        "weights": dict(
            origin_spot_z=0.0,
            dest_spot_z=0.0,
            freight_per_mt_z=0.0,
            inventory_z=0.0,
            exports_4w_pct=0.0,
            fx_eur_usd_z=0.0,
            weather_dest_gust_z=0.0,
        ),
        "spread_mean": 22.0,
        "spread_std": 4.5,
    },
    {
        "name": "usgc_export_surge",
        "n": 140,
        "weights": dict(
            origin_spot_z=-0.6,
            dest_spot_z=0.4,
            freight_per_mt_z=0.3,
            inventory_z=-1.1,
            exports_4w_pct=1.4,
            fx_eur_usd_z=0.0,
            weather_dest_gust_z=0.0,
        ),
        "spread_mean": 42.0,
        "spread_std": 6.0,
    },
    {
        "name": "nwe_demand_soft",
        "n": 100,
        "weights": dict(
            origin_spot_z=0.1,
            dest_spot_z=-0.9,
            freight_per_mt_z=-0.2,
            inventory_z=0.2,
            exports_4w_pct=-0.3,
            fx_eur_usd_z=-0.4,
            weather_dest_gust_z=-0.6,
        ),
        "spread_mean": 11.0,
        "spread_std": 4.0,
    },
]


def _make_row(
    rng: np.random.Generator, weights: dict, spread_mean: float, spread_std: float
) -> tuple[np.ndarray, float]:
    feats = np.zeros(len(FEATURE_NAMES))
    # First 7 features are continuous z-scores (or pct change), draw around
    # the regime mean.
    for i, name in enumerate(FEATURE_NAMES[:7]):
        feats[i] = rng.normal(weights.get(name, 0.0), 1.0)
    # season_q — integer 1..4
    feats[7] = float(rng.integers(1, 5))

    # Target: linear combination + regime baseline + noise. Coefficients
    # picked to be physical: higher dest_spot → wider spread, higher
    # freight → narrower spread, exports surge → wider spread.
    base = spread_mean
    contrib = (
        -3.5 * feats[0]      # origin_spot_z (higher origin → narrower)
        + 4.0 * feats[1]      # dest_spot_z   (higher destination → wider)
        - 2.0 * feats[2]      # freight_per_mt_z (more freight cost → narrower net)
        - 1.0 * feats[3]      # inventory_z   (high inv → narrower)
        + 1.8 * feats[4]      # exports_4w_pct (more exports → wider)
        + 0.6 * feats[5]      # fx_eur_usd_z  (stronger EUR → wider NWE-USD)
        + 0.4 * feats[6]      # weather_dest_gust_z (storm → wider via freight risk)
    )
    # Seasonality — Q1 + Q4 (winter) widen US→NWE; Q3 narrows
    season_lift = {1: 2.5, 2: 0.0, 3: -2.0, 4: 2.0}[int(feats[7])]
    y = base + contrib + season_lift + rng.normal(0, spread_std)
    return feats, y


def train_and_save() -> None:
    rng = np.random.default_rng(20260511)
    X, y = [], []
    for r in REGIMES:
        for _ in range(int(r["n"])):
            row, target = _make_row(rng, r["weights"], r["spread_mean"], r["spread_std"])
            X.append(row)
            y.append(target)
    X = np.asarray(X)
    y = np.asarray(y)

    model = BayesianRidge(compute_score=True, max_iter=300)
    model.fit(X, y)

    # Holdout score on a freshly drawn batch — real validation
    rng_eval = np.random.default_rng(11)
    Xe, ye = [], []
    for r in REGIMES:
        for _ in range(int(r["n"] * 0.2)):
            row, target = _make_row(rng_eval, r["weights"], r["spread_mean"], r["spread_std"])
            Xe.append(row)
            ye.append(target)
    Xe = np.asarray(Xe)
    ye = np.asarray(ye)
    r2 = float(model.score(Xe, ye))
    pred_mean, pred_std = model.predict(Xe, return_std=True)
    rmse = float(np.sqrt(np.mean((pred_mean - ye) ** 2)))
    avg_std = float(np.mean(pred_std))

    out_pkl = OUT / "mispricing_fairvalue.pkl"
    out_meta = OUT / "mispricing_fairvalue.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(model, f)

    meta = {
        "name": "wingman-mispricing-fairvalue",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Bayesian Ridge regression of LPG propane corridor fair-value "
            "spread ($/MT) on an 8-feature market vector (z-scored spots, "
            "freight, inventory, exports, FX, weather, seasonality). Returns "
            "posterior mean + std, so the mispricing engine can compute a "
            "residual z-score and a credible interval band. Trained on a "
            "synthetic regime-conditional sample; replace with desk-labelled "
            "history in production."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [0.20, 0.40, -0.10, -0.30, 0.12, 0.15, 0.20, 2],
        },
        "output_schema": {
            "type": "regression",
            "returns": "posterior mean spread ($/MT) + posterior std",
        },
        "tags": ["wingman", "trading", "mispricing", "bayesian", "regression"],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "Bayesian Ridge Regression",
            "synthetic": True,
            "regimes": [r["name"] for r in REGIMES],
            "holdout_r2": round(r2, 4),
            "holdout_rmse_usd_mt": round(rmse, 4),
            "average_posterior_std": round(avg_std, 4),
            "coef_": [round(float(c), 4) for c in model.coef_],
            "intercept_": round(float(model.intercept_), 4),
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(f"Holdout R^2: {r2:.4f}  RMSE: {rmse:.2f} $/MT  avg posterior std: {avg_std:.2f}")


if __name__ == "__main__":
    train_and_save()
