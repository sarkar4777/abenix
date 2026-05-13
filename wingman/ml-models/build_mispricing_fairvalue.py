"""Train and pickle the Wingman corridor-spread fair-value model.

Bayesian Ridge regression that predicts the *fair-value spread*
(destination spot - origin spot - freight, in $/MT) for an LPG propane
corridor, given a 15-feature vector. Returns posterior mean + std, so
the mispricing engine can compute a residual z-score and credible-
interval band.

Version 1.2.0: extends the v1.1 12-feature model with three freight-
quality features that turn freight from a bunker-derived proxy into a
density-aware, route-aware signal. These come straight from the new
Phase-1-to-3 platform tools (vessel_specs, freight_worldscale,
freight_baltic_blpg):

    freight_baltic_z       z-score of Baltic BLPG mid ($/MT propane VLGC)
                            vs 12-week mean. Direct LPG assessment;
                            replaces noisy bunker proxy as the corridor's
                            primary freight signal where Baltic coverage
                            exists (BLPG1/2/3).
    freight_ws_per_mt_z    z-score of Worldscale-anchored freight in $/MT
                            after density correction
                            (ws_points / 100 * flat_rate). Carries
                            independent CPP-route signal; for LPG-only
                            corridors this is set to the model mean so
                            the column is benign rather than missing.
    route_vessel_size_norm typical liftable cargo in MT for the corridor's
                            standard vessel, normalised by /50_000.
                            Bigger ships → freight per-MT lower → wider
                            arb. Encodes the unit economics the desk
                            already knows.

Version 1.1.0 added four options-market features (kept):
    crude_iv_atm_z          z-score of ATM implied vol on Brent 1m options
    crude_risk_reversal     25-delta call IV minus 25-delta put IV
    nat_gas_iv_atm_z        z-score of ATM IV on HH natgas 1m options
    oil_put_call_ratio      put / call OI ratio on front-month crude

Why these three new ones: they were chosen to cover the trader checklist
gap that v1.1 still had — freight in v1.1 was bunker-derived only, with
no density correction and no vessel-class awareness. Baltic BLPG is the
industry-standard assessment for LPG; Worldscale is the standard for
CPP. Density-corrected $/MT is what every chartering desk actually
quotes. v1.2 makes the fair-value model speak that language.

Features (15 total):
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
    [12] freight_baltic_z      z-score of Baltic BLPG mid for the corridor
    [13] freight_ws_per_mt_z   z-score of Worldscale-anchored CPP freight
    [14] route_vessel_size_norm  liftable cargo MT / 50,000

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
    "freight_baltic_z",
    "freight_ws_per_mt_z",
    "route_vessel_size_norm",
]

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
            freight_baltic_z=0.0,
            freight_ws_per_mt_z=0.0,
            route_vessel_size_norm=0.88,
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
            freight_baltic_z=1.1,
            freight_ws_per_mt_z=0.3,
            route_vessel_size_norm=0.88,
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
            freight_baltic_z=-0.6,
            freight_ws_per_mt_z=-0.2,
            route_vessel_size_norm=0.88,
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
    for i, name in enumerate(FEATURE_NAMES[:7]):
        feats[i] = rng.normal(weights.get(name, 0.0), 1.0)
    feats[7] = float(rng.integers(1, 5))
    feats[8] = rng.normal(weights.get("crude_iv_atm_z", 0.0), 1.0)
    feats[9] = rng.normal(weights.get("crude_risk_reversal", 0.0), 0.04)
    feats[10] = rng.normal(weights.get("nat_gas_iv_atm_z", 0.0), 1.0)
    feats[11] = max(0.2, rng.normal(weights.get("oil_put_call_ratio", 0.9), 0.25))
    feats[12] = rng.normal(weights.get("freight_baltic_z", 0.0), 1.0)
    feats[13] = rng.normal(weights.get("freight_ws_per_mt_z", 0.0), 1.0)
    feats[14] = max(0.1, rng.normal(weights.get("route_vessel_size_norm", 0.88), 0.05))

    base = spread_mean
    contrib = (
        -3.5 * feats[0]
        + 4.0 * feats[1]
        - 2.0 * feats[2]
        - 1.0 * feats[3]
        + 1.8 * feats[4]
        + 0.6 * feats[5]
        + 0.4 * feats[6]
        + 1.4 * feats[8]
        - 24.0 * feats[9]
        + 0.9 * feats[10]
        + 4.5 * (feats[11] - 0.9)
        - 2.8 * feats[12]
        - 1.6 * feats[13]
        + 5.5 * (feats[14] - 0.88)
    )
    season_lift = {1: 2.5, 2: 0.0, 3: -2.0, 4: 2.0}[int(feats[7])]
    y = base + contrib + season_lift + rng.normal(0, spread_std)
    return feats, y


def train_and_save() -> None:
    rng = np.random.default_rng(20260512)
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

    rng_eval = np.random.default_rng(13)
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

    # 12-feature ablation (v1.1 footprint — no freight quality features)
    X12 = X[:, :12]
    Xe12 = Xe[:, :12]
    m12 = BayesianRidge(compute_score=True, max_iter=300)
    m12.fit(X12, y)
    r2_12 = float(m12.score(Xe12, ye))
    pred12, _ = m12.predict(Xe12, return_std=True)
    rmse_12 = float(np.sqrt(np.mean((pred12 - ye) ** 2)))

    # 8-feature ablation (v1.0 footprint — base market signals only)
    X8 = X[:, :8]
    Xe8 = Xe[:, :8]
    m8 = BayesianRidge(compute_score=True, max_iter=300)
    m8.fit(X8, y)
    r2_8 = float(m8.score(Xe8, ye))
    pred8, _ = m8.predict(Xe8, return_std=True)
    rmse_8 = float(np.sqrt(np.mean((pred8 - ye) ** 2)))

    out_pkl = OUT / "mispricing_fairvalue.pkl"
    out_meta = OUT / "mispricing_fairvalue.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(model, f)

    meta = {
        "name": "wingman-mispricing-fairvalue",
        "version": "1.2.0",
        "framework": "sklearn",
        "description": (
            "Bayesian Ridge regression of LPG/CPP corridor fair-value "
            "spread ($/MT) on a 15-feature vector. v1.2 adds three "
            "freight-quality features (Baltic BLPG z-score, Worldscale-"
            "anchored CPP freight z-score, normalised vessel size) on top "
            "of the v1.1 options-aware 12. Returns posterior mean + std "
            "so the mispricing engine can compute a residual z-score and "
            "credible interval. Trained synthetic regime-conditional; "
            "re-train on real desk-labelled history in production."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [
                0.20, 0.40, -0.10, -0.30, 0.12, 0.15, 0.20, 2,
                0.30, 0.02, 0.10, 0.85,
                0.10, 0.05, 0.88,
            ],
        },
        "output_schema": {
            "type": "regression",
            "returns": "posterior mean spread ($/MT) + posterior std",
        },
        "tags": [
            "wingman", "trading", "mispricing", "bayesian", "regression",
            "options-aware", "freight-quality",
        ],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "Bayesian Ridge Regression (15 features, "
                         "options + freight-quality aware)",
            "synthetic": True,
            "regimes": [r["name"] for r in REGIMES],
            "holdout_r2": round(r2, 4),
            "holdout_rmse_usd_mt": round(rmse, 4),
            "average_posterior_std": round(avg_std, 4),
            "coef_": [round(float(c), 4) for c in model.coef_],
            "intercept_": round(float(model.intercept_), 4),
            "ablation_12_feature_only_r2": round(r2_12, 4),
            "ablation_12_feature_only_rmse_usd_mt": round(rmse_12, 4),
            "ablation_8_feature_only_r2": round(r2_8, 4),
            "ablation_8_feature_only_rmse_usd_mt": round(rmse_8, 4),
            "freight_features_added": [
                "freight_baltic_z",
                "freight_ws_per_mt_z",
                "route_vessel_size_norm",
            ],
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(
        f"15-feat (options + freight-quality): "
        f"R^2 {r2:.4f}  RMSE {rmse:.2f} $/MT  std {avg_std:.2f}"
    )
    print(
        f"12-feat ablation (options-only, no freight quality): "
        f"R^2 {r2_12:.4f}  RMSE {rmse_12:.2f} $/MT"
    )
    print(
        f" 8-feat ablation (base signals only): "
        f"R^2 {r2_8:.4f}  RMSE {rmse_8:.2f} $/MT"
    )
    print(
        f" v1.2 vs v1.1 lift: R^2 {r2 - r2_12:+.4f}, "
        f"RMSE {rmse_12 - rmse:+.2f} $/MT lower"
    )


if __name__ == "__main__":
    train_and_save()
