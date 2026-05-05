#!/usr/bin/env python3
"""Train a 5-class wind-turbine failure classifier on synthetic sensor data.

The synthetic generator embeds plausible signatures for each class:

  bearing    -> high-frequency vibration energy + slight temperature rise
  blade      -> rotor imbalance, AEP loss, audible "whoosh" amplitude
  gearbox    -> oil iron ppm spike, broadband mid-frequency vibration
  generator  -> winding temperature rise, low insulation resistance
  control    -> erratic yaw position error, fault-code rate spike

Five real engineering features per class make the problem learnable with
a small Random Forest while still feeling realistic. We keep the training
intentionally cheap (~5 seconds, 1500 samples) because the artefact ships
checked-in.

Outputs (next to this script):
  - failure_classifier.pkl
  - metadata.json   (feature names, class names, accuracy, train timestamp)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split


HERE = Path(__file__).resolve().parent

# Feature order is locked — predict.py reads this exact order from JSON input.
FEATURE_NAMES = [
    "vibration_rms_mm_s",        # 0..15  -- ISO 10816 RMS velocity
    "vibration_hf_band_g",       # 0..5   -- 1-3 kHz band peak
    "gearbox_oil_iron_ppm",      # 0..200
    "generator_winding_temp_c",  # 30..150
    "generator_insulation_mohm", # 0..50  (lower is bad)
    "yaw_position_error_deg",    # 0..10
    "fault_code_rate_per_hour",  # 0..50
    "ambient_wind_mps",          # 2..18  (context, weak signal)
]
CLASS_NAMES = ["bearing", "blade", "gearbox", "generator", "control"]
N_PER_CLASS = 300
RANDOM_STATE = 42


@dataclass
class _ClassParams:
    """Mean / std for each feature at each class. Designed so a Random Forest
    can pick discriminative thresholds without the synthetic problem being
    trivially separable."""
    mean: np.ndarray
    std: np.ndarray


# Means roughly match real-engineering ranges. Std controls overlap so the
# model has to actually learn the joint distribution.
_PARAMS: dict[str, _ClassParams] = {
    "bearing": _ClassParams(
        mean=np.array([8.5, 3.2, 35.0, 60.0, 22.0, 0.8, 4.0, 8.0]),
        std =np.array([1.6, 0.9, 12.0, 6.0,  4.0,  0.4, 2.5, 2.5]),
    ),
    "blade": _ClassParams(
        mean=np.array([6.5, 1.0, 25.0, 55.0, 25.0, 0.5, 2.0, 9.0]),
        std =np.array([1.4, 0.5, 8.0,  6.0,  4.0,  0.3, 1.5, 2.5]),
    ),
    "gearbox": _ClassParams(
        mean=np.array([5.0, 1.6, 130.0, 65.0, 21.0, 0.6, 3.0, 7.5]),
        std =np.array([1.3, 0.6, 25.0,  6.0,  4.0,  0.3, 1.8, 2.5]),
    ),
    "generator": _ClassParams(
        mean=np.array([3.0, 0.8, 28.0, 120.0, 4.5, 0.5, 6.0, 8.5]),
        std =np.array([1.0, 0.4, 9.0,  10.0,  2.0, 0.3, 2.5, 2.5]),
    ),
    "control": _ClassParams(
        mean=np.array([2.5, 0.7, 26.0, 58.0,  24.0, 4.5, 22.0, 8.5]),
        std =np.array([1.0, 0.3, 8.0,  6.0,   4.0,  1.4, 6.0,  2.5]),
    ),
}


def synth_dataset() -> tuple[np.ndarray, np.ndarray]:
    """Generate the labelled synthetic dataset."""
    rng = np.random.default_rng(RANDOM_STATE)
    Xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    for class_idx, class_name in enumerate(CLASS_NAMES):
        params = _PARAMS[class_name]
        # Gaussian per-feature noise around the class mean.
        samples = rng.normal(
            loc=params.mean, scale=params.std,
            size=(N_PER_CLASS, len(FEATURE_NAMES)),
        )
        # Clip to physically sensible ranges — negative ppm or insulation
        # would just confuse the classifier.
        samples = np.clip(
            samples,
            a_min=np.array([0, 0, 0, 20, 0, 0, 0, 0]),
            a_max=np.array([20, 8, 250, 180, 60, 12, 80, 25]),
        )
        Xs.append(samples)
        ys.append(np.full(N_PER_CLASS, class_idx, dtype=int))
    X = np.vstack(Xs)
    y = np.concatenate(ys)
    return X, y


def main() -> None:
    print("Generating synthetic dataset...")
    X, y = synth_dataset()
    print(f"  shape={X.shape}, classes={CLASS_NAMES}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y,
    )

    print("Training Random Forest (200 estimators, max_depth=10)...")
    t0 = time.time()
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_leaf=4,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    train_time = time.time() - t0
    print(f"  trained in {train_time:.2f}s")

    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"\nTest accuracy: {accuracy:.4f}")
    print("\nPer-class report:")
    print(classification_report(y_test, y_pred, target_names=CLASS_NAMES))

    pkl_path = HERE / "failure_classifier.pkl"
    meta_path = HERE / "metadata.json"

    joblib.dump(model, pkl_path)
    print(f"Saved model -> {pkl_path}")

    metadata = {
        "model_type": "RandomForestClassifier",
        "feature_names": FEATURE_NAMES,
        "class_names": CLASS_NAMES,
        "n_train_samples": int(X_train.shape[0]),
        "n_test_samples": int(X_test.shape[0]),
        "test_accuracy": round(float(accuracy), 4),
        "train_time_seconds": round(train_time, 3),
        "trained_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "feature_importances": dict(
            zip(FEATURE_NAMES, [round(float(v), 4) for v in model.feature_importances_])
        ),
        "synthetic": True,
        "random_state": RANDOM_STATE,
    }
    meta_path.write_text(json.dumps(metadata, indent=2))
    print(f"Saved metadata -> {meta_path}")


if __name__ == "__main__":
    main()
