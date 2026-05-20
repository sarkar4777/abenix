"""Train the Wingman freight-forecast model.

Gradient-boosted regressor that predicts next-week Baltic BLPG mid
($/MT propane VLGC) from origin/destination inventory, AIS density, and
season. Picked specifically because:

  1. Tree-based feature_importances_ exposes the `explain` operation of
     the ml_model tool — the other Wingman models are linear (Bayesian
     Ridge, scenario prior) or isolation-forest (no importances).
  2. Real desk question: every chartering call needs a forward freight
     view, and trailing Baltic settlement is a lagging indicator.
  3. Small enough (50 trees, depth 3) that local inference stays under
     5ms even on the CPU pod, so health_check stays green.

Features (8):
    [0] origin_inventory_z       USGC propane stocks z vs 5y seasonal
    [1] dest_inventory_z         FE / NWE / LATAM landed stocks z
    [2] vlgc_orderbook_pct       new VLGC tonnage / fleet (%)
    [3] vlgc_utilisation_pct     14-day moving utilisation (%)
    [4] panama_wait_days         booked-slot lag at PCC + Mira (days)
    [5] season_q                 quarter-of-year
    [6] hormuz_disruption        0/1 flag
    [7] ais_density_z            destination-port AIS arrivals z

Target:
    blpg_next_week_usd_mt        Baltic BLPG mid 7 days forward

Output:
    wingman/ml-models/freight_forecast.pkl
    wingman/ml-models/freight_forecast.meta.json
"""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "origin_inventory_z",
    "dest_inventory_z",
    "vlgc_orderbook_pct",
    "vlgc_utilisation_pct",
    "panama_wait_days",
    "season_q",
    "hormuz_disruption",
    "ais_density_z",
]


def _synthesize_training_set(n: int = 4000, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = np.column_stack([
        rng.normal(0, 1, n),                          # origin_inventory_z
        rng.normal(0, 1, n),                          # dest_inventory_z
        rng.uniform(2.0, 10.0, n),                    # vlgc_orderbook_pct
        rng.uniform(70.0, 98.0, n),                   # vlgc_utilisation_pct
        rng.gamma(1.5, 2.0, n),                       # panama_wait_days
        rng.integers(1, 5, n).astype(float),          # season_q
        rng.binomial(1, 0.35, n).astype(float),       # hormuz_disruption
        rng.normal(0, 1, n),                          # ais_density_z
    ])
    # Real signal: utilisation, orderbook (inverse), hormuz, panama, dest
    # stocks (inverse) drive freight up. Base around BLPG1 historical mid.
    base = 95.0
    blpg = (
        base
        + 4.0 * (X[:, 3] - 85) / 10            # utilisation
        - 8.0 * (X[:, 2] - 6) / 4              # more orderbook -> cheaper freight
        + 65.0 * X[:, 6]                        # hormuz on
        + 6.0 * X[:, 4]                         # panama wait
        - 3.5 * X[:, 1]                         # dest stocks suppress
        + 1.8 * X[:, 7]                         # AIS density
        + rng.normal(0, 8.0, n)
    )
    return X, blpg


def main() -> None:
    X, y = _synthesize_training_set()
    split = int(len(X) * 0.85)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    model = GradientBoostingRegressor(
        n_estimators=120,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.85,
        random_state=42,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_val)
    mae = float(mean_absolute_error(y_val, preds))
    r2 = float(r2_score(y_val, preds))

    model_path = OUT / "freight_forecast.pkl"
    joblib.dump(model, model_path, compress=3)

    meta = {
        "name": "wingman-freight-forecast",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Gradient-boosted regressor predicting next-week Baltic BLPG mid in "
            "$/MT propane VLGC from inventory, orderbook, utilisation, Hormuz "
            "flag, Panama wait, season, and destination-port AIS density."
        ),
        "input_schema": {
            "type": "object",
            "properties": {n: {"type": "number"} for n in FEATURE_NAMES},
            "feature_names": FEATURE_NAMES,
            "required": FEATURE_NAMES,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "predictions": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Next-week BLPG mid forecast, $/MT",
                }
            },
        },
        "training_metrics": {
            "samples": int(len(X_train)),
            "validation_samples": int(len(X_val)),
            "mae_usd_mt": round(mae, 3),
            "r2": round(r2, 4),
        },
        "tags": ["wingman", "freight", "blpg", "regression", "gradient_boosting"],
        "feature_importances": {
            name: float(imp)
            for name, imp in zip(FEATURE_NAMES, model.feature_importances_)
        },
    }
    (OUT / "freight_forecast.meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Wrote {model_path.name} (R² {r2:.4f}, MAE ${mae:.2f}/MT)")


if __name__ == "__main__":
    main()
