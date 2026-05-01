"""
Build the sample ML models shipped with Abenix.

Run from the repo root:
    python3 aimodels/build_samples.py

Produces (gitignored — regenerate locally):
- aimodels/iris_species_classifier.pkl
- aimodels/housing_price_predictor.pkl
- aimodels/churn_predictor.pkl

Each .pkl has a matching .meta.json (tracked in git) describing the
schema so the UI/API can populate the upload form automatically.
"""
import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.datasets import fetch_california_housing, load_iris
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import GradientBoostingRegressor

OUT = Path(__file__).parent


def build_iris() -> None:
    data = load_iris()
    clf = DecisionTreeClassifier(max_depth=4, random_state=42)
    clf.fit(data.data, data.target)
    with (OUT / "iris_species_classifier.pkl").open("wb") as f:
        pickle.dump(clf, f)
    meta = {
        "name": "iris-species-classifier",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": "Classifies iris flowers into setosa, versicolor, or virginica from sepal/petal measurements. Trained on 150 samples, 4 features.",
        "input_schema": {
            "features": ["sepal_length_cm", "sepal_width_cm", "petal_length_cm", "petal_width_cm"],
            "types": ["float", "float", "float", "float"],
            "example": [5.1, 3.5, 1.4, 0.2],
        },
        "output_schema": {
            "type": "classification",
            "classes": ["setosa", "versicolor", "virginica"],
            "output_fields": ["predicted_class", "probabilities"],
        },
        "training_metrics": {
            "accuracy": float(clf.score(data.data, data.target)),
            "samples": len(data.target),
            "features": 4,
            "classes": 3,
        },
        "tags": ["classification", "iris", "demo", "sklearn"],
    }
    (OUT / "iris_species_classifier.meta.json").write_text(json.dumps(meta, indent=2))


def build_housing() -> None:
    ds = fetch_california_housing()
    X, y = ds.data, ds.target  # y is in units of $100k
    # Train/test split by index to keep the script deterministic
    split = int(0.8 * len(y))
    model = GradientBoostingRegressor(n_estimators=100, max_depth=4, random_state=42)
    model.fit(X[:split], y[:split])
    score = model.score(X[split:], y[split:])
    with (OUT / "housing_price_predictor.pkl").open("wb") as f:
        pickle.dump(model, f)
    meta = {
        "name": "housing-price-predictor",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": "Predicts California housing prices (in $100k units) from 8 block-level features. Gradient boosted regression.",
        "input_schema": {
            "features": list(ds.feature_names),
            "types": ["float"] * len(ds.feature_names),
            "example": X[0].tolist(),
        },
        "output_schema": {
            "type": "regression",
            "unit": "100000 USD",
            "output_fields": ["predicted_price"],
        },
        "training_metrics": {
            "r2_test": float(score),
            "samples_train": split,
            "samples_test": len(y) - split,
            "features": X.shape[1],
        },
        "tags": ["regression", "housing", "demo", "sklearn"],
    }
    (OUT / "housing_price_predictor.meta.json").write_text(json.dumps(meta, indent=2))


def build_churn() -> None:
    """
    Synthesize a telco-style churn dataset and train a logistic regression
    in an sklearn Pipeline (scaler + model). Binary output with probability.

    Features (8):
      tenure_months        int  — how long the customer has been with us
      monthly_charges      float — USD
      total_charges        float — USD lifetime value
      contract_months      int  — 1 (M2M), 12, or 24
      is_senior            int  — 0/1
      has_partner          int  — 0/1
      support_tickets_30d  int  — number of support interactions last 30 days
      payment_auto         int  — 0/1 (is the customer on autopay)
    """
    rng = np.random.default_rng(42)
    n = 4000

    tenure = rng.integers(1, 72, size=n)
    monthly = rng.normal(70, 30, size=n).clip(20, 200)
    contract = rng.choice([1, 12, 24], size=n, p=[0.55, 0.25, 0.20])
    is_senior = rng.binomial(1, 0.16, size=n)
    has_partner = rng.binomial(1, 0.48, size=n)
    tickets = rng.poisson(1.2, size=n)
    auto_pay = rng.binomial(1, 0.55, size=n)
    total = monthly * tenure * rng.uniform(0.9, 1.1, size=n)

    # Latent churn probability — shorter tenure, M2M, many tickets, no autopay = higher churn
    logit = (
        -2.0
        - 0.04 * tenure
        + 0.012 * monthly
        - 0.06 * contract
        + 0.25 * is_senior
        - 0.35 * has_partner
        + 0.45 * tickets
        - 0.70 * auto_pay
    )
    prob = 1 / (1 + np.exp(-logit))
    y = rng.binomial(1, prob)

    X = np.column_stack([tenure, monthly, total, contract, is_senior, has_partner, tickets, auto_pay])
    split = int(0.8 * n)

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    pipe.fit(X[:split], y[:split])
    acc = float(pipe.score(X[split:], y[split:]))
    base_churn = float(y[split:].mean())

    with (OUT / "churn_predictor.pkl").open("wb") as f:
        pickle.dump(pipe, f)
    meta = {
        "name": "churn-predictor",
        "version": "1.0.0",
        "framework": "sklearn",
        "description": "Predicts customer churn probability for a telco-style subscription business. Input: 8 customer features. Output: binary churn label + probability.",
        "input_schema": {
            "features": [
                "tenure_months",
                "monthly_charges",
                "total_charges",
                "contract_months",
                "is_senior",
                "has_partner",
                "support_tickets_30d",
                "payment_auto",
            ],
            "types": ["int", "float", "float", "int", "int", "int", "int", "int"],
            "example": [12, 74.35, 892.20, 1, 0, 1, 3, 0],
            "feature_notes": {
                "contract_months": "1 for month-to-month, 12 for 1-year, 24 for 2-year",
                "is_senior": "0 or 1",
                "has_partner": "0 or 1",
                "payment_auto": "0 or 1 — whether the customer is enrolled in autopay",
            },
        },
        "output_schema": {
            "type": "binary_classification",
            "classes": ["retained", "churned"],
            "output_fields": ["predicted_class", "probabilities"],
        },
        "training_metrics": {
            "accuracy_test": acc,
            "base_churn_rate_test": base_churn,
            "samples_train": split,
            "samples_test": n - split,
            "features": X.shape[1],
        },
        "tags": ["classification", "churn", "telco", "demo", "sklearn", "business"],
    }
    (OUT / "churn_predictor.meta.json").write_text(json.dumps(meta, indent=2))


if __name__ == "__main__":
    print("Building iris_species_classifier...")
    build_iris()
    print("Building housing_price_predictor...")
    build_housing()
    print("Building churn_predictor...")
    build_churn()
    print("Done. .pkl + .meta.json files written to aimodels/")
