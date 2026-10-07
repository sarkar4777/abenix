"""Sample models users can register from the ML Models page to try the feature."""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

IRIS_FEATURES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
IRIS_CLASSES = ["setosa", "versicolor", "virginica"]

SAMPLES: dict[str, dict] = {
    "iris": {
        "name": "iris-sample",
        "filename": "iris_classifier.joblib",
        "description": (
            "Sample scikit-learn classifier. Give it a flower's sepal and petal "
            "measurements in cm and it names the iris species."
        ),
        "input_schema": {
            "features": IRIS_FEATURES,
            "types": ["number"] * 4,
            "units": "cm",
            "example": [5.1, 3.5, 1.4, 0.2],
        },
        "output_schema": {
            "type": "classification",
            "classes": IRIS_CLASSES,
            "returns": "predictions (species), probabilities per class",
        },
        "tags": ["sample", "iris", "classifier"],
    },
}


def build_iris(path: Path) -> Path:
    # string labels so predictions read as species names
    import joblib
    from sklearn.datasets import load_iris
    from sklearn.linear_model import LogisticRegression

    data = load_iris()
    labels = [IRIS_CLASSES[i] for i in data.target]
    clf = LogisticRegression(max_iter=500).fit(data.data, labels)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, path)
    return path


def sample_file(sample_id: str) -> Path:
    return HERE / SAMPLES[sample_id]["filename"]
