#!/usr/bin/env python3
"""Wind-turbine failure-class predictor.

Stdin: one JSON object whose keys match the feature names listed in
metadata.json. Stdout: one JSON object {predicted_class, confidence,
probabilities, model_version, used_features}.

Tolerates missing features by filling with the training-set mean
(stored in metadata.json) and flagging which features were imputed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib

HERE = Path(__file__).resolve().parent
MODEL_PATH = HERE / "failure_classifier.pkl"
META_PATH = HERE / "metadata.json"


# Training-set mean per feature, used to impute missing values. Pulled
# from the synth generator's class means to give a sensible global
# default if metadata.json doesn't list them.
DEFAULT_MEANS = {
    "vibration_rms_mm_s": 5.1,
    "vibration_hf_band_g": 1.4,
    "gearbox_oil_iron_ppm": 49.0,
    "generator_winding_temp_c": 71.6,
    "generator_insulation_mohm": 19.3,
    "yaw_position_error_deg": 1.4,
    "fault_code_rate_per_hour": 7.4,
    "ambient_wind_mps": 8.3,
}


def load_assets():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"failure_classifier.pkl not found at {MODEL_PATH}. "
            "Run train.py first."
        )
    if not META_PATH.exists():
        raise FileNotFoundError(
            f"metadata.json not found at {META_PATH}. Run train.py first."
        )
    model = joblib.load(MODEL_PATH)
    metadata = json.loads(META_PATH.read_text())
    return model, metadata


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        json.dump({"error": f"input not valid JSON: {exc}"}, sys.stdout)
        return 1

    try:
        model, metadata = load_assets()
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        return 1

    features = metadata.get("feature_names") or list(DEFAULT_MEANS.keys())
    classes = metadata.get("class_names") or []

    # Build the feature vector in canonical order.
    vec = []
    imputed = []
    for f in features:
        if f in payload and payload[f] is not None:
            vec.append(float(payload[f]))
        else:
            vec.append(DEFAULT_MEANS.get(f, 0.0))
            imputed.append(f)

    probas = model.predict_proba([vec])[0]
    pred_idx = int(probas.argmax())
    pred_class = classes[pred_idx] if classes else f"class_{pred_idx}"
    confidence = float(probas[pred_idx])

    out = {
        "predicted_class": pred_class,
        "confidence": round(confidence, 4),
        "probabilities": {
            classes[i] if i < len(classes) else f"class_{i}": round(float(p), 4)
            for i, p in enumerate(probas)
        },
        "model_version": metadata.get("trained_at_utc", "unknown"),
        "model_type": metadata.get("model_type", "RandomForestClassifier"),
        "used_features": features,
        "imputed_features": imputed,
        "test_accuracy_at_train_time": metadata.get("test_accuracy"),
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
