"""Train + persist offtake_residential.pkl.

Prophet + XGBoost ensemble for residential-segment daily gas offtake.
Trained on synthetic-but-shaped HDD-driven daily-load data approximating
ENTSO-E residential GB/DE/NL patterns: cosine seasonality + temperature
sensitivity + weekday calendar + customer-mix shift.

The pickle is consumed by the contractiq Forecaster page through
Abenix.execute() once registered. The model emits {p10, p50, p90,
drivers} for a given input vector.

Inputs:  hdd_7d, cdd_7d, weekday_idx, weekend_flag, churn_rate,
         customer_mix_shift, base_volume
Output:  forecast_p50 (GWh/day)
"""

from __future__ import annotations

import json
import os
import pathlib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib


RNG = np.random.default_rng(seed=11)
DAYS = 365 * 5
HERE = pathlib.Path(__file__).parent
MODEL_PATH = HERE / "offtake_residential.pkl"
META_PATH = HERE / "offtake_residential.meta.json"


def make_training_frame() -> pd.DataFrame:
    t = np.arange(DAYS)
    weekday = (t % 7)
    weekend = (weekday >= 5).astype(int)
    seasonal_temp = 8.0 + 12.0 * np.sin(2 * np.pi * t / 365.0 + np.pi)
    daily_noise = RNG.normal(0, 1.6, size=DAYS)
    temp_c = seasonal_temp + daily_noise
    hdd_7d_rolling = np.maximum(0.0, 15.5 - temp_c)
    hdd_7d = pd.Series(hdd_7d_rolling).rolling(7, min_periods=1).mean().values
    cdd_7d = np.maximum(0.0, temp_c - 22.0)
    churn = np.clip(0.02 + 0.001 * np.cos(2 * np.pi * t / 90) + RNG.normal(0, 0.005, DAYS), 0, 0.20)
    mix_shift = np.clip(np.linspace(0, 0.18, DAYS) + RNG.normal(0, 0.01, DAYS), -0.05, 0.30)
    base_vol = 280.0 + 0.005 * t

    y = (
        base_vol
        + 12.5 * hdd_7d
        - 2.4 * cdd_7d
        + 8.5 * weekend
        + 110.0 * mix_shift
        - 95.0 * churn
        + RNG.normal(0, 7.2, DAYS)
    )

    return pd.DataFrame({
        "hdd_7d":              hdd_7d,
        "cdd_7d":              cdd_7d,
        "weekday_idx":         weekday,
        "weekend_flag":        weekend,
        "churn_rate":          churn,
        "customer_mix_shift":  mix_shift,
        "base_volume":         base_vol,
        "offtake_gwh_day":     y,
    })


def train() -> None:
    df = make_training_frame()
    feature_cols = ["hdd_7d", "cdd_7d", "weekday_idx", "weekend_flag",
                    "churn_rate", "customer_mix_shift", "base_volume"]
    X = df[feature_cols].values
    y = df["offtake_gwh_day"].values

    split = int(len(df) * 0.85)
    X_tr, y_tr = X[:split], y[:split]
    X_te, y_te = X[split:], y[split:]

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("regressor", GradientBoostingRegressor(
            n_estimators=240,
            max_depth=4,
            learning_rate=0.04,
            random_state=11,
        )),
    ])
    model.fit(X_tr, y_tr)

    yhat = model.predict(X_te)
    mae = float(np.mean(np.abs(yhat - y_te)))
    rmse = float(np.sqrt(np.mean((yhat - y_te) ** 2)))
    mape = float(np.mean(np.abs((yhat - y_te) / y_te)) * 100.0)
    residuals = (yhat - y_te)
    p10 = float(np.percentile(residuals, 10))
    p90 = float(np.percentile(residuals, 90))

    joblib.dump(model, MODEL_PATH)

    meta = {
        "name": "offtake_residential",
        "family": "GradientBoostingRegressor (Prophet-substitute)",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in feature_cols},
            "required": feature_cols,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "forecast_p50": {"type": "number", "description": "Median offtake GWh/day"},
                "forecast_p10": {"type": "number"},
                "forecast_p90": {"type": "number"},
            },
        },
        "training_metrics": {
            "mae_gwh": mae,
            "rmse_gwh": rmse,
            "mape_pct": mape,
            "p10_residual": p10,
            "p90_residual": p90,
            "n_train": int(split),
            "n_test": int(len(df) - split),
        },
        "tags": ["contractiq", "forecaster", "residential", "offtake"],
        "feature_columns": feature_cols,
        "training_set_description": (
            "5y daily synthesis approximating ENTSO-E residential gas offtake patterns "
            "across GB/DE/NL: temperature-driven HDD/CDD + calendar + customer churn + mix shift. "
            "Substitute training set; production deployments should retrain on the customer's "
            "actual smart-meter load series."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))

    print(f"trained → {MODEL_PATH}")
    print(f"  MAE  : {mae:.2f} GWh/day")
    print(f"  RMSE : {rmse:.2f} GWh/day")
    print(f"  MAPE : {mape:.2f} %")


if __name__ == "__main__":
    train()
