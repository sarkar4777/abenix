"""Train + persist offtake_storage_cycling.pkl.

Gradient-boosting regressor that maps (front-winter spread,
days-to-withdrawal, injection-capacity-left, linepack, basis) to
optimal daily storage cycling profile in GWh/day. Pairs with an LP
optimiser at inference time for the actual cycle plan.
"""

from __future__ import annotations

import json
import pathlib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
import joblib


RNG = np.random.default_rng(seed=37)
DAYS = 365 * 5
HERE = pathlib.Path(__file__).parent
MODEL_PATH = HERE / "offtake_storage_cycling.pkl"
META_PATH = HERE / "offtake_storage_cycling.meta.json"


def make_training_frame() -> pd.DataFrame:
    t = np.arange(DAYS)
    winter_pos = np.minimum(t % 365, 365 - (t % 365))
    front_winter_spread = np.clip(6.0 + 5.0 * np.sin(2 * np.pi * t / 365) + RNG.normal(0, 1.5, DAYS), -2, 18)
    days_to_withdrawal = 180 - winter_pos / 2 + RNG.normal(0, 4, DAYS)
    inj_capacity_left = np.clip(0.6 - 0.3 * np.sin(2 * np.pi * t / 365) + RNG.normal(0, 0.08, DAYS), 0, 1.0)
    linepack = np.clip(0.85 + RNG.normal(0, 0.05, DAYS), 0.4, 1.0)
    ttf_the_basis = RNG.normal(0.2, 0.35, DAYS)

    optimal_cycle = (
        1.2 * front_winter_spread
        + 0.08 * (180 - days_to_withdrawal)
        + 6.0 * inj_capacity_left
        - 4.0 * (1.0 - linepack)
        + 1.5 * ttf_the_basis
        + RNG.normal(0, 1.0, DAYS)
    )

    return pd.DataFrame({
        "front_winter_spread":  front_winter_spread,
        "days_to_withdrawal":   days_to_withdrawal,
        "inj_capacity_left":    inj_capacity_left,
        "linepack":             linepack,
        "ttf_the_basis":        ttf_the_basis,
        "optimal_cycle_gwh":    optimal_cycle,
    })


def train() -> None:
    df = make_training_frame()
    feature_cols = ["front_winter_spread", "days_to_withdrawal",
                    "inj_capacity_left", "linepack", "ttf_the_basis"]
    X = df[feature_cols].values
    y = df["optimal_cycle_gwh"].values

    split = int(len(df) * 0.85)
    model = GradientBoostingRegressor(n_estimators=300, max_depth=4, learning_rate=0.05, random_state=37)
    model.fit(X[:split], y[:split])
    yhat = model.predict(X[split:])
    y_te = y[split:]
    mae = float(np.mean(np.abs(yhat - y_te)))
    rmse = float(np.sqrt(np.mean((yhat - y_te) ** 2)))

    joblib.dump(model, MODEL_PATH)

    meta = {
        "name": "offtake_storage_cycling",
        "family": "GradientBoostingRegressor (paired with downstream LP optimiser)",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in feature_cols},
            "required": feature_cols,
        },
        "output_schema": {"type": "object", "properties": {"optimal_cycle_gwh": {"type": "number"}}},
        "training_metrics": {"mae_gwh": mae, "rmse_gwh": rmse,
                              "n_train": int(split), "n_test": int(len(df) - split)},
        "tags": ["contractiq", "forecaster", "storage", "cycling"],
        "feature_columns": feature_cols,
        "training_set_description": (
            "5y daily synthesis of storage-cycling decisions vs front-winter spread + days-to-"
            "withdrawal + injection capacity left. Substitute training set; production retrains "
            "on the customer's actual storage book + hub spreads."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"trained → {MODEL_PATH}  MAE {mae:.2f}  RMSE {rmse:.2f}")


if __name__ == "__main__":
    train()
