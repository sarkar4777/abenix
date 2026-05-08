"""Train and pickle the Wingman scenario-prior model.

A Gaussian Naive Bayes classifier over five forward-curve scenarios for
LPG propane:

  - base                   : market roughly balanced
  - bull_geopolitical      : geopolitical de-escalation lifts spread
  - bear_supply_glut       : USGC export overcapacity + inventory build
  - bear_demand_shock      : Asian demand softening / China policy shift
  - tail_event             : freight stress + extreme weather window

Inputs (8 normalised market signals; mean ~0, std ~1):
    spot_momentum_4w        4-week % change in origin-hub spot
    futures_premium_3m      3-month future minus spot, normalised
    news_sentiment_supply   sentiment z-score of supply-side headlines
    news_sentiment_demand   sentiment z-score of demand-side headlines
    news_sentiment_geo      sentiment z-score of geopolitics headlines
    news_sentiment_reg      sentiment z-score of regulatory headlines
    weather_z               combined weather-disruption z-score over 7d
    freight_stress          bunker + congestion stress index, 0-2 typical

Output: predicted scenario class + per-class probability (Bayes posterior
under the GaussianNB likelihood). The Wingman scenario forecaster agent
uses these probabilities as the *prior* over scenarios, then refines
them with an LLM pass over current news headlines.

The training corpus below is synthetic but matches the linguistic shape
of how a desk economist would describe each regime — every sample is a
labeled feature draw from a regime-specific multivariate normal whose
mean reflects the headline trait of that regime (e.g. bull_geopolitical
has a high positive geo-sentiment mean and a slightly negative spot
momentum mean from buyers stepping back). Re-train on real desk-labelled
outcomes the moment you have them.

Output:
    wingman/ml-models/scenario_prior.pkl
    wingman/ml-models/scenario_prior.meta.json
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.naive_bayes import GaussianNB

OUT = Path(__file__).parent

FEATURE_NAMES = [
    "spot_momentum_4w",
    "futures_premium_3m",
    "news_sentiment_supply",
    "news_sentiment_demand",
    "news_sentiment_geo",
    "news_sentiment_reg",
    "weather_z",
    "freight_stress",
]

# Regime mean vectors. Each entry is the conditional mean of the 8
# features given that class. Tuned to match the shape an LPG analyst
# would describe for each scenario; these are deliberately not extreme
# so the GaussianNB posterior stays calibrated rather than degenerate.
REGIMES: dict[str, dict[str, float | int]] = {
    "base": {
        "n": 240,
        "spot_momentum_4w": 0.0,
        "futures_premium_3m": 0.05,
        "news_sentiment_supply": 0.0,
        "news_sentiment_demand": 0.0,
        "news_sentiment_geo": 0.0,
        "news_sentiment_reg": 0.0,
        "weather_z": 0.0,
        "freight_stress": 0.4,
    },
    "bull_geopolitical": {
        "n": 110,
        "spot_momentum_4w": -0.25,
        "futures_premium_3m": -0.45,
        "news_sentiment_supply": 0.10,
        "news_sentiment_demand": 0.30,
        "news_sentiment_geo": 1.55,
        "news_sentiment_reg": 0.10,
        "weather_z": -0.10,
        "freight_stress": 0.30,
    },
    "bear_supply_glut": {
        "n": 110,
        "spot_momentum_4w": -0.55,
        "futures_premium_3m": -0.55,
        "news_sentiment_supply": 1.40,
        "news_sentiment_demand": -0.10,
        "news_sentiment_geo": -0.05,
        "news_sentiment_reg": -0.05,
        "weather_z": -0.05,
        "freight_stress": 0.30,
    },
    "bear_demand_shock": {
        "n": 90,
        "spot_momentum_4w": -0.65,
        "futures_premium_3m": -0.30,
        "news_sentiment_supply": 0.05,
        "news_sentiment_demand": -1.45,
        "news_sentiment_geo": -0.10,
        "news_sentiment_reg": 0.05,
        "weather_z": -0.05,
        "freight_stress": 0.40,
    },
    "tail_event": {
        "n": 60,
        "spot_momentum_4w": 0.55,
        "futures_premium_3m": 0.65,
        "news_sentiment_supply": -0.40,
        "news_sentiment_demand": 0.20,
        "news_sentiment_geo": 0.50,
        "news_sentiment_reg": 0.10,
        "weather_z": 1.65,
        "freight_stress": 1.55,
    },
}

# Per-feature standard deviation. The dispersion is the same across
# regimes so the discriminating signal lives in the mean — that's the
# textbook GaussianNB setup.
STD_BY_FEATURE = {
    "spot_momentum_4w": 0.45,
    "futures_premium_3m": 0.50,
    "news_sentiment_supply": 0.55,
    "news_sentiment_demand": 0.55,
    "news_sentiment_geo": 0.55,
    "news_sentiment_reg": 0.55,
    "weather_z": 0.55,
    "freight_stress": 0.45,
}


def _generate(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    rows: list[np.ndarray] = []
    labels: list[str] = []
    for label, spec in REGIMES.items():
        n = int(spec["n"])  # type: ignore[arg-type]
        for _ in range(n):
            v = np.array(
                [rng.normal(spec[f], STD_BY_FEATURE[f]) for f in FEATURE_NAMES],  # type: ignore[arg-type]
                dtype=np.float64,
            )
            rows.append(v)
            labels.append(label)
    return np.vstack(rows), np.array(labels)


def train_and_save() -> None:
    rng = np.random.default_rng(20260508)
    X, y = _generate(rng)
    clf = GaussianNB()
    clf.fit(X, y)

    classes = list(clf.classes_)
    mean_priors = {c: float(p) for c, p in zip(classes, clf.class_prior_)}

    # Hold-out accuracy on a freshly drawn batch — real validation, not
    # train-on-train. Recorded in metadata so the platform UI can show
    # it as a training metric.
    rng_eval = np.random.default_rng(99)
    Xe, ye = _generate(rng_eval)
    score = float(clf.score(Xe, ye))

    out_pkl = OUT / "scenario_prior.pkl"
    out_meta = OUT / "scenario_prior.meta.json"
    with out_pkl.open("wb") as f:
        pickle.dump(clf, f)

    meta = {
        "name": "wingman-scenario-prior",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": (
            "Bayesian (Gaussian Naive Bayes) prior over LPG propane "
            "forward-curve scenarios. Given 8 normalised market signals "
            "(spot momentum, 3-month futures premium, four news-sentiment "
            "z-scores by category, weather z-score, freight stress), the "
            "model returns calibrated probabilities over five named "
            "scenario classes. The Wingman scenario forecaster uses these "
            "as priors and the LLM refines posteriors using current news. "
            "Trained on a synthetic but realistic regime-conditional "
            "distribution; production deployments should re-train on "
            "desk-labelled outcomes."
        ),
        "input_schema": {
            "features": FEATURE_NAMES,
            "types": ["float"] * len(FEATURE_NAMES),
            "example": [0.20, -0.10, 0.40, 0.30, 1.20, 0.00, 0.50, 0.70],
        },
        "output_schema": {
            "type": "classification",
            "classes": classes,
            "returns": "scenario class probabilities (Bayesian prior)",
        },
        "tags": ["wingman", "trading", "scenario", "bayesian", "prior"],
        "training": {
            "samples": int(X.shape[0]),
            "algorithm": "Gaussian Naive Bayes",
            "synthetic": True,
            "regimes": list(REGIMES.keys()),
            "holdout_accuracy": round(score, 4),
            "class_priors": mean_priors,
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2))
    print(f"Wrote {out_pkl} ({out_pkl.stat().st_size} bytes)")
    print(f"Wrote {out_meta}")
    print(f"Holdout accuracy: {score:.4f}  classes: {classes}")


if __name__ == "__main__":
    train_and_save()
