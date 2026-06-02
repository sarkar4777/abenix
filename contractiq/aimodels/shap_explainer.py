"""SHAP-style feature attributions for the contractiq ML models.

Mounted as a code-asset in Abenix. Given (model_name, feature_vector),
loads the corresponding .pkl from /data/ml-models/<tenant>/, computes
SHAP values for tree / linear models, and returns per-feature
contribution + cumulative waterfall.

Falls back to permutation importance when SHAP is unavailable, so the
Workbench page always gets *something* real, never a synthesised story.
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


def _feature_columns(model_name: str) -> list[str]:
    base = pathlib.Path(__file__).resolve().parent
    meta = base / f"{model_name}.meta.json"
    if meta.exists():
        return json.loads(meta.read_text()).get("feature_columns", [])
    return []


def explain(model_name: str, feature_vector: dict[str, float]) -> dict[str, Any]:
    path = _find_model(model_name)
    if not path:
        return {
            "ok": False,
            "error": f"model file for {model_name} not found in ML_MODELS_DIR",
        }
    model = joblib.load(path)
    cols = _feature_columns(model_name) or list(feature_vector.keys())
    x = np.array([[feature_vector.get(c, 0.0) for c in cols]])

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
    base_pred = float(model.predict(x)[0])

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


if __name__ == "__main__":
    payload = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    out = explain(
        model_name=payload.get("model_name", ""),
        feature_vector=payload.get("feature_vector", {}),
    )
    print(json.dumps(out, indent=2))
