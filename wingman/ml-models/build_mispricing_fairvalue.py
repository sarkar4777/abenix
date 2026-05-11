"""Train and pickle the Wingman corridor-spread fair-value model.

Bayesian Ridge regression that predicts the *fair-value spread*
(destination spot - origin spot - freight, in $/MT) for an LPG propane
corridor, given a 12-feature vector. Returns posterior mean + std, so
the mispricing engine can compute a residual z-score and credible-
interval band.

Version 1.1.0: extends the v1.0 8-feature model with four options-
market-derived features that carry independent signal about the spread:

    crude_iv_atm_z          z-score of ATM implied vol on Brent 1m options
                            (market-wide nervousness; widens fair-value)
    crude_risk_reversal     25-delta call IV minus 25-delta put IV on
                            Brent 1m options (positive = upside skew /
                            supply fear → narrower forward spread)
    nat_gas_iv_atm_z        z-score of ATM IV on Henry Hub natural-gas
                            1m options (propane is an NGL by-product)
    oil_put_call_ratio      put / call open-interest ratio on front-month
                            crude options. Extreme values (>1.3 or <0.6)
                            predict mean reversion.

Why those four: they were chosen on (1) liquidity — Brent and HH option
chains are deep and free to read; (2) economic linkage — crude drives
propane price level, HH drives NGL availability and winter demand,
EUR/USD vol drives the NWE-leg arb; (3) independence from the existing
8 features — options data is forward-looking, the rest is realised.

Features (12 total):
    [ 0] origin_spot_z         z-score of origin hub spot vs 12-week mean
    [ 1] dest_spot_z           z-score of destination hub spot vs 12-week mean
    [ 2] freight_per_mt_z      z-score of bunker-derived freight vs 12-week mean
    [ 3] inventory_z           z-score of EIA US propane stocks vs 5-yr seasonal
    [ 4] exports_4w_pct        4-week change in USGC propane export volume (pct)
    [ 5] fx_eur_usd_z          z-score of EUR/USD vs 12-week mean
    [ 6] weather_dest_gust_z   z-score of destination-hub 7-day max gust
    [ 7] season_q              quarter-of-year (1..4)
    [ 8] crude_iv_atm_z        z-score of Brent 1m ATM IV vs 60-day mean
    [ 9] crude_risk_reversal   25-delta call IV minus 25-delta put IV
    [10] nat_gas_iv_atm_z      z-score of HH 1m ATM IV vs 60-day mean
    [11] oil_put_call_ratio    front-month crude put/call OI ratio

Target:
    spread_usd_mt              destination_spot - origin_spot - freight_per_mt

Output:
    wingman/ml-models/mispricing_fairvalue.pkl
    wingman/ml-models/mispricing_fairvalue.meta.json
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
    "crude_iv_atm_z",
    "crude_risk_reversal",
    "nat_gas_iv_atm_z",
    "oil_put_call_ratio",
]

# Three regimes the desk would recognise. Each carries the mean feature
# vector AND a baseline spread mean. The options features are correlated
# with the regime: when the desk is in a supply-shock regime, crude IV
# rises and skew goes positive (upside risk).
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
            crude_iv_atm_z=0.0,
            crude_risk_reversal=0.0,
            nat_gas_iv_atm_z=0.0,
            oil_put_call_ratio=0.9,
        ),
        "spread_mean": 22.0,
        "spread_std": 3.5,
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
            crude_iv_atm_z=0.7,
            crude_risk_reversal=0.06,
            nat_gas_iv_atm_z=0.3,
            oil_put_call_ratio=0.7,
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
            crude_iv_atm_z=0.4,
            crude_risk_reversal=-0.05,
            nat_gas_iv_atm_z=0.2,
            oil_put_call_ratio=1.3,
        ),
        "spread_mean": 11.0,
        "spread_std": 4.0,
    },
]


def _make_row(
    rng: np.random.Generator,
    weights: dict,
    spread_mean: float,
    spread_std: float,
) -> tuple[np.ndarray, float]:
    feats = np.zeros(len(FEATURE_NAMES))
    # Indexes 0..6 are continuous z-scores (or pct change)
    for i, name in enumerate(FEATURE_NAMES[:7]):
        feats[i] = rng.normal(weights.get(name, 0.0), 1.0)
    feats[7] = float(rng.integers(1, 5))  # season_q
    # Options features: index 8..11
    feats[8] = rng.normal(weights.get("crude_iv_atm_z", 0.0), 1.0)
    feats[9] = rng.normal(weights.get("crude_risk_reversal", 0.0), 0.04)
    feats[10] = rng.normal(weights.get("nat_gas_iv_atm_z", 0.0), 1.0)
    feats[11] = max(0.2, rng.normal(weights.get("oil_put_call_ratio", 0.9), 0.25))

    base = spread_mean
    contrib = (
        -3.5 * feats[0]   # origin_spot_z
        + 4.0 * feats[1]   # dest_spot_z
        - 2.0 * feats[2]   # freight_per_mt_z
        - 1.0 * feats[3]   # inventory_z
        + 1.8 * feats[4]   # exports_4w_pct
        + 0.6 * feats[5]   # fx_eur_usd_z
        + 0.4 * feats[6]   # weather_dest_gust_z
        # Options contributions: each carries signal the realised
        # features can't capture. Together they account for a couple of
        # R-squared points on the held-out validation slice.
        + 1.4 * feats[8]                  # crude_iv_atm_z
        - 24.0 * feats[9]                 # risk reversal (upside-skewed → narrower forward spread)
        + 0.9 * feats[10]                 # HH IV
        + 4.5 * (feats[11] - 0.9)         # OI ratio centred at 0.9
    )
    season_lift = {1: 2.5, 2: 0.0, 3: -2.0, 4: 2.0}[int(feats[7])]
    y = base + contrib + season_lift + rng.normal(0, spread_std)
    return feats, y


def train_and_save() -> None:
    rng = np.random.default_rng(20260511)
    X, y = [], []
    for r in REGIMES:
        for _ in range(int(r["n"])):
            row, target = _make_row(
                rng, r["weights"], r["spread_mean"], r["spread_std"]
            )
            X.append(row)
            y.append(target)
    X = np.asarray(X)
    y = np.asarray(y)

    model = BayesianRidge(compute_score=True, max_iter=300)
    model.fit(X, y)

    rng_eval = np.random.default_rng(11)
    Xe, ye = [], []
    for r in REGIMES:
        for _ in range(int(r["n"] * 0.2)):
            row, target = _make_row(
                rng_eval, r["weights"], r["spread_mean"], r["spread_std"]
            )
            Xe.append(row)
            ye.append(target)
    Xe = np.asarray(Xe)
    ye = np.asarray(ye)
    r2 = float(model.score(Xe, ye))
    pred_mean, pred_std = model.predict(Xe, return_std=True)
    rmse = float(np.sqrt(np.mean((pred_mean - ye) ** 2)))
    avg_std = float(np.mean(pred_std))

    # Apples-to-apples ablation: train the same algorithm on the
    # 8 base features only, evaluate on the same holdout, so the lift
    # from the 4 options columns is honest.
    X_base = X[:, :8]
    Xe_base = Xe[:, :8]
    base_model = BayesianRidge(compute_score=True, max_iter=300)
    base_model.fit(X_base, y)
    base_r2 = float(base_model.score(Xe_base, ye))
    base_pred, _ = base_model.predict(Xe_base, return_std=True)
    base_rmse = float(np.sqrt(np.mean((base_pred - ye) ** 2)))

    out_pkl = OUT / "mispricing_fairvalue.pkl"
    out_meta = OUT / "mispricing_fairvalue.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(model, f)

    meta = {
        "name": "wingman-mispricing-fairvalue",
        "version": "1.1.0",
        "framework": "sklearn",
        "description": (
            "Bayesian Ridge regression of LPG propane corridor fair-value "
            "spread ($/MT) on a 12-feature vector (8 base market signals "
            "plus 4 options-market signals: Brent ATM IV, Brent 25-delta "
            "risk reversal, HH natgas ATM IV, crude put/call OI ratio). "
            "Returns posterior mean + std so the mispricing engine can "
            "compute a residual z-score and credible interval. Options "
            "features added in v1.1 to capture forward-looking market "
            "nervousness and skew. Trained synthetic regime-conditional; "
            "re-train on real desk-labelled history in production."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [
                0.20, 0.40, -0.10, -0.30, 0.12, 0.15, 0.20, 2,
                0.30, 0.02, 0.10, 0.85,
            ],
        },
        "output_schema": {
            "type": "regression",
            "returns": "posterior mean spread ($/MT) + posterior std",
        },
        "tags": [
            "wingman", "trading", "mispricing", "bayesian", "regression",
            "options-aware",
        ],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "Bayesian Ridge Regression (12 features, "
                         "options-aware)",
            "synthetic": True,
            "regimes": [r["name"] for r in REGIMES],
            "holdout_r2": round(r2, 4),
            "holdout_rmse_usd_mt": round(rmse, 4),
            "average_posterior_std": round(avg_std, 4),
            "coef_": [round(float(c), 4) for c in model.coef_],
            "intercept_": round(float(model.intercept_), 4),
            "ablation_8_feature_only_r2": round(base_r2, 4),
            "ablation_8_feature_only_rmse_usd_mt": round(base_rmse, 4),
            "options_features_added": [
                "crude_iv_atm_z",
                "crude_risk_reversal",
                "nat_gas_iv_atm_z",
                "oil_put_call_ratio",
            ],
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(
        f"12-feat (options-aware): R^2 {r2:.4f}  RMSE {rmse:.2f} $/MT  "
        f"avg posterior std {avg_std:.2f}"
    )
    print(
        f" 8-feat ablation (same data, no options): "
        f"R^2 {base_r2:.4f}  RMSE {base_rmse:.2f} $/MT"
    )
    print(
        f" lift: R^2 {r2 - base_r2:+.4f}, "
        f"RMSE {base_rmse - rmse:+.2f} $/MT lower"
    )


if __name__ == "__main__":
    train_and_save()
