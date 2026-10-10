"""Per-feature attributions for one prediction of a registered model."""

from __future__ import annotations

from math import factorial
from typing import Any, Callable

import numpy as np

EXACT_MAX_FEATURES = 10
MAX_FEATURES = 500
PERMUTATIONS = 64

Score = Callable[[np.ndarray], np.ndarray]


class ExplainInputError(ValueError):
    """Explain input the model cannot take. Reported to the caller as 422."""


def _floats(value: Any, names: list[str], n: int) -> list[float] | None:
    if isinstance(value, dict) and names and all(k in value for k in names):
        vals = [value[k] for k in names]
    elif isinstance(value, list) and len(value) == n:
        vals = value
    else:
        return None
    try:
        out = [float(v) for v in vals]
    except (TypeError, ValueError):
        return None
    return out if all(np.isfinite(out)) else None


def stored_means(
    input_schema: Any, training_metrics: Any, names: list[str], n: int
) -> list[float] | None:
    """Training means saved in the model's metadata, if it has them."""
    schema = input_schema if isinstance(input_schema, dict) else {}
    props = schema.get("properties")
    prop = props.get("input_data") if isinstance(props, dict) else None
    tm = training_metrics if isinstance(training_metrics, dict) else {}
    for candidate in (
        schema.get("x-feature-means"),
        prop.get("x-feature-means") if isinstance(prop, dict) else None,
        tm.get("feature_means"),
    ):
        means = _floats(candidate, names, n)
        if means is not None:
            return means
    return None


def scaler_means(model: Any, n: int) -> list[float] | None:
    """Training means a pipeline's leading StandardScaler learned while fitting."""
    steps = getattr(model, "steps", None)
    if not steps:
        return None
    first = steps[0][1]
    mean = getattr(first, "mean_", None)
    if type(first).__name__ != "StandardScaler" or mean is None:
        return None
    mean = np.asarray(mean, dtype=float).reshape(-1)
    return mean.tolist() if mean.size == n else None


def _number(v: Any, label: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ExplainInputError(f"baseline value for {label} must be a number.")
    if not np.isfinite(f):
        raise ExplainInputError(f"baseline value for {label} must be a finite number.")
    return f


def resolve_baseline(
    requested: Any,
    names: list[str],
    n: int,
    defaults: list[tuple[str, list[float] | None]],
) -> tuple[np.ndarray, str]:
    """The baseline row and where it came from. defaults are tried in order, zeros last."""
    base, source = np.zeros(n), "zeros"
    for src, vals in defaults:
        if vals is not None:
            base, source = np.asarray(vals, dtype=float), src
            break
    if requested is None:
        return base, source
    if isinstance(requested, dict):
        if not names:
            raise ExplainInputError(
                f"This model has no feature names, send baseline as a list of {n} numbers."
            )
        unknown = [str(k) for k in requested if k not in names]
        if unknown:
            raise ExplainInputError(
                f"baseline names unknown features: {', '.join(unknown)}. "
                f"This model's features are {', '.join(names)}."
            )
        out = base.copy()
        for k, v in requested.items():
            out[names.index(k)] = _number(v, k)
        if len(requested) == n:
            return out, "request"
        return out, f"request, rest from {source}"
    if isinstance(requested, list):
        if len(requested) != n:
            raise ExplainInputError(
                f"baseline has {len(requested)} values, this model expects {n}."
            )
        label = names if len(names) == n else list(range(n))
        return np.array([_number(v, label[i]) for i, v in enumerate(requested)]), (
            "request"
        )
    raise ExplainInputError(
        "baseline must be an object of feature values or a list of numbers."
    )


def linear_coefs(model: Any, n: int) -> np.ndarray | None:
    """Coefficients in input units for a linear regressor, optionally behind StandardScalers."""
    steps = getattr(model, "steps", None)
    est = steps[-1][1] if steps else model
    scale = np.ones(n)
    for _, step in (steps or [])[:-1]:
        if step is None or step == "passthrough":
            continue
        if type(step).__name__ != "StandardScaler":
            return None
        s = getattr(step, "scale_", None)
        if s is not None:
            scale = scale * np.asarray(s, dtype=float).reshape(-1)
    if hasattr(est, "predict_proba") or hasattr(est, "classes_"):
        return None
    coef = getattr(est, "coef_", None)
    if coef is None or getattr(est, "intercept_", None) is None:
        return None
    coef = np.asarray(coef, dtype=float)
    if coef.size != n:
        return None
    return coef.reshape(n) / scale


def _is_tree(model: Any) -> bool:
    name = type(model).__name__
    return any(s in name for s in ("Tree", "Forest", "Boost", "XGB", "LGBM"))


def shap_values(
    model: Any, x: np.ndarray, b: np.ndarray, linear: bool
) -> tuple[np.ndarray, str] | None:
    """SHAP values against the one baseline row, when the shap package is installed."""
    try:
        import shap
    except Exception:
        return None
    if getattr(model, "steps", None) is not None:
        return None
    try:
        background = b.reshape(1, -1)
        if linear:
            ex, method = shap.LinearExplainer(model, background), "linear-shap"
        elif _is_tree(model):
            ex = shap.TreeExplainer(
                model, data=background, feature_perturbation="interventional"
            )
            method = "tree-shap"
        else:
            return None
        vals = np.asarray(ex.shap_values(x.reshape(1, -1)), dtype=float).reshape(-1)
    except Exception:
        return None
    return (vals, method) if vals.size == x.size else None


def exact_shapley(f: Score, x: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shapley values over every mix of input and baseline values."""
    n = x.size
    masks = np.arange(1 << n)
    bits = ((masks[:, None] >> np.arange(n)) & 1).astype(bool)
    v = f(np.where(bits, x, b))
    sizes = bits.sum(axis=1)
    w = np.array([factorial(s) * factorial(n - s - 1) / factorial(n) for s in range(n)])
    phi = np.empty(n)
    for i in range(n):
        without = masks[~bits[:, i]]
        phi[i] = np.sum(w[sizes[without]] * (v[without | (1 << i)] - v[without]))
    return phi


def sampled_shapley(
    f: Score, x: np.ndarray, b: np.ndarray, permutations: int = PERMUTATIONS
) -> np.ndarray:
    """Shapley values averaged over walks from baseline to input, each walk sums exactly."""
    n = x.size
    count = max(4, min(permutations, 40000 // (n + 1)))
    rng = np.random.default_rng(0)
    half = [rng.permutation(n) for _ in range(count // 2)]
    perms = half + [p[::-1] for p in half]
    rows = np.empty((len(perms), n + 1, n))
    for k, p in enumerate(perms):
        z = b.copy()
        rows[k, 0] = z
        for t, j in enumerate(p):
            z[j] = x[j]
            rows[k, t + 1] = z
    v = f(rows.reshape(-1, n)).reshape(len(perms), n + 1)
    phi = np.zeros(n)
    for k, p in enumerate(perms):
        phi[p] += np.diff(v[k])
    return phi / len(perms)


def attribute(
    f: Score,
    x: np.ndarray,
    b: np.ndarray,
    *,
    model: Any = None,
    coefs: np.ndarray | None = None,
    allow_shap: bool = False,
) -> tuple[np.ndarray, float, float, str]:
    """Contributions, f(x), f(baseline) and the method used."""
    n = x.size
    if n > MAX_FEATURES:
        raise ExplainInputError(
            f"Explain handles up to {MAX_FEATURES} features, this row has {n}."
        )
    fx, fb = (float(v) for v in f(np.vstack([x, b])))
    tol = 1e-6 * max(1.0, abs(fx), abs(fb))

    def adds_up(phi: np.ndarray) -> bool:
        return bool(np.all(np.isfinite(phi))) and abs(phi.sum() - (fx - fb)) <= tol

    if allow_shap:
        got = shap_values(model, x, b, coefs is not None)
        if got is not None and adds_up(got[0]):
            return got[0], fx, fb, got[1]
    if coefs is not None:
        phi = coefs * (x - b)
        if adds_up(phi):
            return phi, fx, fb, "linear"
    if n <= EXACT_MAX_FEATURES:
        return exact_shapley(f, x, b), fx, fb, "exact-shapley"
    return sampled_shapley(f, x, b), fx, fb, "sampled-shapley"


def report(
    names: list[str],
    x: np.ndarray,
    b: np.ndarray,
    phi: np.ndarray,
    fx: float,
    fb: float,
    method: str,
    baseline_source: str,
    target: str,
) -> dict[str, Any]:
    """Contributions largest first and the waterfall from baseline to prediction."""
    order = sorted(range(x.size), key=lambda i: -abs(phi[i]))
    contributions = []
    waterfall = []
    running = fb
    for i in order:
        c = float(phi[i])
        contributions.append(
            {
                "feature": names[i],
                "value": float(x[i]),
                "baseline": float(b[i]),
                "contribution": c,
            }
        )
        waterfall.append(
            {
                "feature": names[i],
                "contribution": c,
                "start": running,
                "end": running + c,
            }
        )
        running += c
    return {
        "method": method,
        "target": target,
        "prediction": fx,
        "base_value": fb,
        "baseline": {names[i]: float(b[i]) for i in range(x.size)},
        "baseline_source": baseline_source,
        "feature_names": list(names),
        "contributions": contributions,
        "waterfall": waterfall,
        "additivity_gap": fx - fb - float(np.sum(phi)),
    }
