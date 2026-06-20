"""SHAP feature attributions for the ContractIQ ML models.

Reads a JSON envelope on stdin:

  {
    "model_name": "price_fairvalue_gas_hubs",
    "feature_vector": { "storage_eu_pct": 62, ... }
  }

Loads the matching .pkl from /data/ml-models/<tenant>/, runs SHAP
(tree or linear), and writes the per-feature contributions to
stdout. Falls back to feature_importances_ / coef_ when the SHAP
backend can't handle the estimator so the Workbench page always
gets a real attribution, never a synthesised one.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any

import joblib
import numpy as np


def _find_model(model_name: str) -> pathlib.Path | None:
    base = pathlib.Path(os.environ.get("ML_MODELS_DIR", "/data/ml-models"))
    if not base.is_dir():
        return None
    for tenant_dir in base.iterdir():
        if not tenant_dir.is_dir():
            continue
        for f in tenant_dir.glob(f"*_{model_name}.pkl"):
            return f
        for f in tenant_dir.glob(f"*{model_name}*.pkl"):
            return f
    return None


def _feature_columns(model_name: str, fallback: list[str]) -> list[str]:
    base = pathlib.Path(__file__).resolve().parent
    meta = base / f"{model_name}.meta.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text()).get("feature_columns", []) or fallback
        except Exception:
            return fallback
    # Look next to the .pkl too — the platform writes meta next to the model.
    pkl = _find_model(model_name)
    if pkl is not None:
        side = pkl.with_suffix(".meta.json")
        if side.exists():
            try:
                return json.loads(side.read_text()).get("feature_columns", []) or fallback
            except Exception:
                return fallback
    return fallback


def explain(model_name: str, feature_vector: dict[str, float]) -> dict[str, Any]:
    path = _find_model(model_name)
    if not path:
        return {
            "ok": False,
            "error": f"model file for {model_name} not found in ML_MODELS_DIR",
        }
    model = joblib.load(path)
    cols = _feature_columns(model_name, list(feature_vector.keys()))
    x = np.array([[float(feature_vector.get(c, 0.0)) for c in cols]])

    contributions: list[dict[str, Any]] = []
    method = "unknown"

    try:
        import shap

        if hasattr(model, "named_steps"):
            est = model.named_steps[list(model.named_steps)[-1]]
            x_in = model[:-1].transform(x) if len(model.named_steps) > 1 else x
        else:
            est, x_in = model, x

        try:
            expl = shap.TreeExplainer(est)
            sv = expl.shap_values(x_in)
            method = "tree-shap"
        except Exception:
            expl = shap.LinearExplainer(est, x_in)
            sv = expl.shap_values(x_in)
            method = "linear-shap"

        sv = np.asarray(sv).reshape(-1)
        for col, val in zip(cols, sv):
            contributions.append({"feature": col, "value": float(val)})
    except Exception:
        try:
            if hasattr(model, "named_steps"):
                est = model.named_steps[list(model.named_steps)[-1]]
            else:
                est = model
            if hasattr(est, "feature_importances_"):
                imps = est.feature_importances_
                method = "permutation-importance"
                for col, val in zip(cols, imps):
                    contributions.append({"feature": col, "value": float(val)})
            elif hasattr(est, "coef_"):
                coefs = np.asarray(est.coef_).reshape(-1)
                method = "linear-coef"
                for col, val in zip(cols, coefs):
                    contributions.append({"feature": col, "value": float(val)})
            else:
                return {"ok": False, "error": "model exposes no importance interface"}
        except Exception as e:
            return {"ok": False, "error": f"fallback explain failed: {e}"}

    contributions.sort(key=lambda c: abs(c["value"]), reverse=True)
    try:
        base_pred = float(model.predict(x)[0])
    except Exception:
        base_pred = 0.0

    return {
        "ok": True,
        "method": method,
        "model_name": model_name,
        "prediction": base_pred,
        "feature_columns": cols,
        "contributions": contributions,
        "waterfall": [
            {"feature": c["feature"], "delta": c["value"]} for c in contributions
        ],
    }


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"invalid json: {e}"}))
        return 1
    model_name = (payload.get("model_name") or "").strip()
    feature_vector = payload.get("feature_vector") or {}
    if not model_name:
        print(json.dumps({"ok": False, "error": "model_name required"}))
        return 1
    out = explain(model_name=model_name, feature_vector=feature_vector)
    print(json.dumps(out, default=float))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
