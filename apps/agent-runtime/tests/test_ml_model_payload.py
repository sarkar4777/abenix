"""Predictions come back as JSON with the single value on top."""

from __future__ import annotations

import json

from engine import autonomy
from engine.tools.ml_model_tool import prediction_payload


def test_single_regression_value_is_on_top():
    out = prediction_payload("price", "1", "local", {"predictions": [125.8]})
    assert out["prediction"] == 125.8
    assert out["predictions"] == [125.8]
    assert out["model"] == "price" and out["operation"] == "predict"


def test_classifier_keeps_classes_and_label():
    out = prediction_payload(
        "iris",
        2,
        "k8s",
        {"predictions": ["setosa"], "classes": ["setosa"], "probabilities": [[1.0]]},
    )
    assert out["prediction"] == "setosa"
    assert out["version"] == "2"


def test_batch_has_no_single_value():
    out = prediction_payload("p", "1", "local", [[1.0], [2.0]], batch=True)
    assert "prediction" not in out
    assert out["predictions"] == [[1.0], [2.0]]


def test_world_model_reads_the_payload():
    content = json.dumps(prediction_payload("p", "1", "local", {"predictions": [80]}))
    pred = autonomy._prediction_from(
        content, {"metric": "price", "band": 10}, "ml_model"
    )
    assert pred["value"] == 80 and pred["low"] == 70 and pred["high"] == 90
