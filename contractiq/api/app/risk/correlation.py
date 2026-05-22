"""EWMA correlation + covariance matrix. λ=0.94 default (RiskMetrics)."""

from __future__ import annotations

from typing import Sequence

import numpy as np


def correlation_matrix(
    series: dict[str, Sequence[float]],
    *,
    decay: float = 0.94,
    method: str = "ewma",
) -> dict[str, dict[str, float]]:
    """Return a {name: {name: corr}} matrix.

    Series can be of unequal length — they are trimmed to the shortest.
    EWMA-weighted correlation by default.
    """
    names = sorted(series.keys())
    if len(names) < 2:
        return {n: {n: 1.0} for n in names}
    arrs = [np.asarray(series[n], dtype=float) for n in names]
    n_min = min(a.size for a in arrs)
    if n_min < 2:
        return {n: {m: 1.0 if n == m else 0.0 for m in names} for n in names}
    arrs = [a[-n_min:] for a in arrs]
    mat = np.vstack(arrs)
    if method == "ewma":
        weights = np.array([(1.0 - decay) * decay ** (n_min - 1 - i) for i in range(n_min)])
        weights = weights / weights.sum()
        means = (mat * weights).sum(axis=1, keepdims=True)
        centered = mat - means
        cov = (weights * centered) @ centered.T
        std = np.sqrt(np.diag(cov))
        std[std == 0] = 1.0
        corr = cov / np.outer(std, std)
    else:
        corr = np.corrcoef(mat)
    out: dict[str, dict[str, float]] = {}
    for i, n in enumerate(names):
        out[n] = {m: round(float(corr[i, j]), 6) for j, m in enumerate(names)}
    return out
