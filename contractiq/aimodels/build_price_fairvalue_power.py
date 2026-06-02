"""Train + persist price_fairvalue_power_hubs.pkl.

BayesianRidge fair-value for EU power hubs (DE, FR, NL, BE, AT) with
renewables-residual and clean-spark spread inputs.

Features:
  ttf_eur_mwh, eua_eur_t, residual_load_gw, wind_capf, solar_capf,
  hydro_reservoir_pct, hour_of_day_idx
Output:
  fair_value_eur_mwh + sigma
"""

from __future__ import annotations

import json
import pathlib
import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import joblib


RNG = np.random.default_rng(seed=71)
HOURS = 24 * 365 * 3
HERE = pathlib.Path(__file__).parent
MODEL_PATH = HERE / "price_fairvalue_power_hubs.pkl"
ANOM_PATH = HERE / "price_fairvalue_power_hubs.anomaly.pkl"
META_PATH = HERE / "price_fairvalue_power_hubs.meta.json"


def make_frame() -> pd.DataFrame:
    t = np.arange(HOURS)
    hour = (t % 24).astype(int)
    seasonal = 32 + 16 * np.sin(2 * np.pi * t / (24 * 365))
    daily = 10 * np.sin(2 * np.pi * hour / 24)
    ttf = 38 + 10 * np.sin(2 * np.pi * t / (24 * 365)) + RNG.normal(0, 3.5, HOURS)
    eua = 70 + 15 * np.sin(2 * np.pi * t / (24 * 220)) + RNG.normal(0, 4.5, HOURS)
    wind = np.clip(0.28 + 0.18 * np.sin(2 * np.pi * t / (24 * 7)) + RNG.normal(0, 0.12, HOURS), 0, 1)
    solar = np.clip(np.maximum(0, np.sin(np.pi * hour / 12)) * (0.32 + 0.08 * np.sin(2 * np.pi * t / (24 * 365))) + RNG.normal(0, 0.04, HOURS), 0, 1)
    hydro = np.clip(55 + 22 * np.sin(2 * np.pi * t / (24 * 365)) + RNG.normal(0, 4, HOURS), 5, 100)
    residual = np.clip(65 - 38 * wind - 22 * solar + RNG.normal(0, 4, HOURS), 5, 90)

    fair = (
        seasonal + daily
        + 1.4 * (ttf - 38) + 0.6 * (eua - 70)
        + 0.85 * (residual - 50)
        - 0.06 * (hydro - 55)
        + RNG.normal(0, 3.8, HOURS)
    )

    return pd.DataFrame({
        "ttf_eur_mwh":          ttf,
        "eua_eur_t":            eua,
        "residual_load_gw":     residual,
        "wind_capf":            wind,
        "solar_capf":           solar,
        "hydro_reservoir_pct":  hydro,
        "hour_of_day_idx":      hour,
        "spot_eur_mwh":         fair,
    })


def train() -> None:
    df = make_frame()
    feature_cols = ["ttf_eur_mwh", "eua_eur_t", "residual_load_gw",
                    "wind_capf", "solar_capf", "hydro_reservoir_pct", "hour_of_day_idx"]
    X = df[feature_cols].values
    y = df["spot_eur_mwh"].values

    split = int(len(df) * 0.85)
    pipe = Pipeline([("scaler", StandardScaler()), ("br", BayesianRidge(max_iter=400))])
    pipe.fit(X[:split], y[:split])
    yhat, sigma = pipe.named_steps["br"].predict(
        pipe.named_steps["scaler"].transform(X[split:]), return_std=True
    )
    y_te = y[split:]
    mae = float(np.mean(np.abs(yhat - y_te)))
    rmse = float(np.sqrt(np.mean((yhat - y_te) ** 2)))

    residuals = y[:split] - pipe.predict(X[:split])
    anom = IsolationForest(n_estimators=200, contamination=0.05, random_state=71)
    anom.fit(residuals.reshape(-1, 1))

    joblib.dump(pipe, MODEL_PATH)
    joblib.dump(anom, ANOM_PATH)

    meta = {
        "name": "price_fairvalue_power_hubs",
        "family": "BayesianRidge + IsolationForest residual",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {c: {"type": "number"} for c in feature_cols},
            "required": feature_cols,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "fair_value_eur_mwh": {"type": "number"},
                "sigma":              {"type": "number"},
                "z_score":            {"type": "number"},
                "anomaly_flag":       {"type": "boolean"},
            },
        },
        "training_metrics": {
            "mae_eur_mwh": mae,
            "rmse_eur_mwh": rmse,
            "avg_sigma": float(sigma.mean()),
            "n_train": int(split),
            "n_test": int(len(df) - split),
        },
        "tags": ["contractiq", "price-engine", "power", "fair-value"],
        "feature_columns": feature_cols,
        "applies_to_hubs": ["DE", "FR", "NL", "BE", "AT"],
        "training_set_description": (
            "3y hourly synthesis of EU power formation: gas+EUA marginal-cost stack + wind/solar capf + residual load + hydro. "
            "Substitute training set; production retrains on ENTSO-E + EEX settlements + day-ahead prints."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"trained power fair-value: MAE {mae:.2f}  RMSE {rmse:.2f}  avg_sigma {sigma.mean():.2f}")


if __name__ == "__main__":
    train()
