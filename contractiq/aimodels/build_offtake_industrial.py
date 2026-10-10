"""Train + persist offtake_industrial.pkl.

Gradient-boosting regressor approximating the LSTM baseload behaviour
for industrial counterparties: sector-PMI + plant-utilisation + cluster
profile drive daily offtake.

Inputs:  sector_pmi, plant_utilisation, cluster_id, last_quarter_avg,
         power_price_eur_mwh, maintenance_flag
Output:  baseload_gwh_day
"""

from __future__ import annotations

import json
import pathlib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
import joblib


RNG = np.random.default_rng(seed=23)
DAYS = 365 * 5
HERE = pathlib.Path(__file__).parent
MODEL_PATH = HERE / "offtake_industrial.pkl"
META_PATH = HERE / "offtake_industrial.meta.json"


def make_training_frame() -> pd.DataFrame:
    t = np.arange(DAYS)
    cluster_id = (t % 6).astype(int)
    pmi_base = 50.0 + 6.0 * np.sin(2 * np.pi * t / 250) + RNG.normal(0, 1.5, DAYS)
    plant_util = np.clip(0.78 + 0.04 * np.sin(2 * np.pi * t / 90) + RNG.normal(0, 0.03, DAYS), 0.4, 1.0)
    last_quarter_avg = 410.0 + 12.0 * cluster_id + RNG.normal(0, 6.0, DAYS)
    power_price = np.clip(95.0 + 14.0 * np.sin(2 * np.pi * t / 365) + RNG.normal(0, 8.0, DAYS), 30, 200)
    maintenance_flag = (RNG.random(DAYS) < 0.04).astype(int)

    y = (
        last_quarter_avg
        + 4.0 * (pmi_base - 50)
        + 220.0 * (plant_util - 0.75)
        - 0.5 * (power_price - 95)
        - 60.0 * maintenance_flag
        + RNG.normal(0, 8.5, DAYS)
    )

    return pd.DataFrame({
        "sector_pmi":         pmi_base,
        "plant_utilisation":  plant_util,
        "cluster_id":         cluster_id,
        "last_quarter_avg":   last_quarter_avg,
        "power_price_eur_mwh":power_price,
        "maintenance_flag":   maintenance_flag,
        "baseload_gwh_day":   y,
    })


def train() -> None:
    df = make_training_frame()
    feature_cols = ["sector_pmi", "plant_utilisation", "cluster_id",
                    "last_quarter_avg", "power_price_eur_mwh", "maintenance_flag"]
    X = df[feature_cols].values
    y = df["baseload_gwh_day"].values

    split = int(len(df) * 0.85)
    model = Pipeline([
        ("regressor", HistGradientBoostingRegressor(
            max_iter=350,
            max_depth=6,
            learning_rate=0.05,
            random_state=23,
        )),
    ])
    model.fit(X[:split], y[:split])
    yhat = model.predict(X[split:])
    y_te = y[split:]
    mae = float(np.mean(np.abs(yhat - y_te)))
    rmse = float(np.sqrt(np.mean((yhat - y_te) ** 2)))
    mape = float(np.mean(np.abs((yhat - y_te) / y_te)) * 100.0)

    joblib.dump(model, MODEL_PATH)

    meta = {
        "name": "offtake_industrial",
        "family": "HistGradientBoostingRegressor (LSTM-substitute)",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in feature_cols},
            "required": feature_cols,
        },
        "output_schema": {
            "type": "object",
            "properties": {"baseload_gwh_day": {"type": "number"}},
        },
        "training_metrics": {"mae_gwh": mae, "rmse_gwh": rmse, "mape_pct": mape,
                              "n_train": int(split), "n_test": int(len(df) - split),
                              "feature_means": {c: float(df[c].values[:split].mean()) for c in feature_cols}},
        "tags": ["contractiq", "forecaster", "industrial", "baseload"],
        "feature_columns": feature_cols,
        "training_set_description": (
            "5y daily synthesis approximating industrial baseload patterns across 6 cluster "
            "profiles, driven by sector PMI + plant utilisation + power-price elasticity. "
            "Substitute training set; production should retrain on real customer baseload curves."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"trained → {MODEL_PATH}  MAE {mae:.2f}  RMSE {rmse:.2f}  MAPE {mape:.2f}%")


if __name__ == "__main__":
    train()
