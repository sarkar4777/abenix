"""Lightweight ML model serving server — deployed as a k8s pod."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("model-server")

app = FastAPI(title="Abenix Model Server")

# ─── Config from environment ──────────────────────────────────────────────
MODEL_URI = os.environ.get("MODEL_URI", "")
MODEL_FRAMEWORK = os.environ.get("MODEL_FRAMEWORK", "sklearn")

_model: Any = None


class PredictRequest(BaseModel):
    input_data: Any  # dict with "features" key or list of values


class PredictResponse(BaseModel):
    predictions: Any
    model_uri: str
    framework: str
    latency_ms: int


def _resolve_model_path() -> str:
    """Resolve MODEL_URI to a local file path. Downloads if it's an HTTP URL."""
    uri = MODEL_URI
    if not uri:
        raise RuntimeError("MODEL_URI environment variable is not set")

    if uri.startswith(("http://", "https://")):
        import urllib.request
        local_path = "/tmp/model_file"
        logger.info("Downloading model from %s...", uri)
        req = urllib.request.Request(uri)
        auth = os.environ.get("MODEL_AUTH_HEADER", "").strip()
        if auth:
            req.add_header("Authorization", auth)
        with urllib.request.urlopen(req, timeout=60) as resp, open(local_path, "wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
        logger.info("Downloaded to %s", local_path)
        return local_path

    return uri


def _load_model() -> Any:
    """Load model based on framework."""
    model_path = _resolve_model_path()

    logger.info("Loading model from %s (framework=%s)", model_path, MODEL_FRAMEWORK)
    start = time.monotonic()

    if MODEL_FRAMEWORK in ("sklearn", "xgboost"):
        import joblib
        model = joblib.load(model_path)
    elif MODEL_FRAMEWORK == "onnx":
        import onnxruntime as ort
        model = ort.InferenceSession(model_path)
    elif MODEL_FRAMEWORK == "pytorch":
        import torch
        model = torch.load(model_path, map_location="cpu", weights_only=False)
        model.eval()
    else:
        raise ValueError(f"Unsupported framework: {MODEL_FRAMEWORK}")

    elapsed = (time.monotonic() - start) * 1000
    logger.info("Model loaded in %.0fms", elapsed)
    return model


@app.on_event("startup")
async def startup():
    global _model
    _model = _load_model()


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None, "framework": MODEL_FRAMEWORK}


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    start = time.monotonic()

    # Parse input
    input_data = req.input_data
    if isinstance(input_data, dict):
        features = input_data.get("features") or list(input_data.values())
    elif isinstance(input_data, list):
        features = input_data
    else:
        features = [input_data]

    X = np.array([features]) if not isinstance(features[0], (list, np.ndarray)) else np.array(features)

    # Predict
    if MODEL_FRAMEWORK in ("sklearn", "xgboost"):
        preds = _model.predict(X)
        result: dict[str, Any] = {"predictions": preds.tolist()}
        if hasattr(_model, "predict_proba"):
            result["probabilities"] = _model.predict_proba(X).tolist()
        if hasattr(_model, "classes_"):
            result["classes"] = [str(c) for c in _model.classes_]
            result["predicted_class"] = str(_model.classes_[preds[0]])
        predictions = result

    elif MODEL_FRAMEWORK == "onnx":
        input_name = _model.get_inputs()[0].name
        preds = _model.run(None, {input_name: X.astype(np.float32)})
        predictions = {"predictions": [p.tolist() if hasattr(p, 'tolist') else p for p in preds]}

    elif MODEL_FRAMEWORK == "pytorch":
        import torch
        with torch.no_grad():
            output = _model(torch.FloatTensor(X))
            predictions = {"predictions": output.numpy().tolist()}

    else:
        predictions = {"error": f"Unsupported framework: {MODEL_FRAMEWORK}"}

    latency_ms = int((time.monotonic() - start) * 1000)
    return PredictResponse(
        predictions=predictions,
        model_uri=MODEL_URI,
        framework=MODEL_FRAMEWORK,
        latency_ms=latency_ms,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
