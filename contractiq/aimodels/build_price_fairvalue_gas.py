"""Train + persist price_fairvalue_gas_hubs.pkl.

BayesianRidge fair-value model for European gas hubs (TTF, NBP, THE, PEG,
PSV, CEGH). Takes a 6-dim hub feature vector and emits expected mid +
1-sigma confidence band. Pairs with an IsolationForest residual detector
(also trained here, second pickle) for mispricing signals.

Features:
  storage_eu_pct, ttf_basis_eur, hh_eur_equiv, brent_eur,
  weather_anomaly_c, lng_send_out_gwh
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


RNG = np.random.default_rng(seed=53)
DAYS = 365 * 5
HERE = pathlib.Path(__file__).parent
MODEL_PATH = HERE / "price_fairvalue_gas_hubs.pkl"
ANOM_PATH = HERE / "price_fairvalue_gas_hubs.anomaly.pkl"
META_PATH = HERE / "price_fairvalue_gas_hubs.meta.json"


def make_frame() -> pd.DataFrame:
    t = np.arange(DAYS)
    storage_pct = np.clip(50 + 35 * np.sin(2 * np.pi * t / 365 + 0.5) + RNG.normal(0, 4, DAYS), 5, 100)
    ttf_basis = RNG.normal(0.0, 1.2, DAYS)
    hh_eur = 12.0 + 4.0 * np.sin(2 * np.pi * t / 365) + RNG.normal(0, 1.5, DAYS)
    brent_eur = 75.0 + 12.0 * np.sin(2 * np.pi * t / 220) + RNG.normal(0, 4.0, DAYS)
    weather_anom = RNG.normal(0, 2.5, DAYS)
    lng_send = np.clip(2800 + 600 * np.sin(2 * np.pi * t / 365 + 1.0) + RNG.normal(0, 120, DAYS), 1000, 4500)

    fair = (
        35.0
        - 0.18 * storage_pct
        + 3.8 * (hh_eur - 12.0)
        + 0.42 * (brent_eur - 75.0)
        - 1.6 * weather_anom
        - 0.005 * (lng_send - 2800)
        + ttf_basis * 1.4
        + RNG.normal(0, 2.4, DAYS)
    )

    return pd.DataFrame({
        "storage_eu_pct":     storage_pct,
        "ttf_basis_eur":      ttf_basis,
        "hh_eur_equiv":       hh_eur,
        "brent_eur":          brent_eur,
        "weather_anomaly_c":  weather_anom,
        "lng_send_out_gwh":   lng_send,
        "spot_eur_mwh":       fair,
    })


def train() -> None:
    df = make_frame()
    feature_cols = ["storage_eu_pct", "ttf_basis_eur", "hh_eur_equiv",
                    "brent_eur", "weather_anomaly_c", "lng_send_out_gwh"]
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
    anom = IsolationForest(n_estimators=200, contamination=0.05, random_state=53)
    anom.fit(residuals.reshape(-1, 1))

    joblib.dump(pipe, MODEL_PATH)
    joblib.dump(anom, ANOM_PATH)

    meta = {
        "name": "price_fairvalue_gas_hubs",
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
        "tags": ["contractiq", "price-engine", "gas", "fair-value"],
        "feature_columns": feature_cols,
        "applies_to_hubs": ["TTF", "NBP", "THE", "PEG", "PSV", "CEGH"],
        "training_set_description": (
            "5y daily synthesis of EU hub fundamentals: storage, TTF basis, HH equiv, Brent, weather, LNG send-out. "
            "Substitute training set; production retrains on ICE settlements + GIE storage + EIA HH + ENTSOG."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"trained gas fair-value: MAE {mae:.2f}  RMSE {rmse:.2f}  avg_sigma {sigma.mean():.2f}")


if __name__ == "__main__":
    train()
