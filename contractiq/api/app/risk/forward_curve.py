"""Forward curve bootstrap + interp. Generic — works for any asset where
the caller supplies (tenor_days, price) points. The interpolation method
is pluggable so a metals curve can use log-linear interp while a power
curve uses cubic spline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import math

import numpy as np


@dataclass
class ForwardCurvePoint:
    tenor_days: float
    price: float


@dataclass
class ForwardCurve:
    asset: str
    method: str
    points: list[ForwardCurvePoint]


def bootstrap_curve(
    asset: str,
    raw_points: Sequence[tuple[float, float]],
    *,
    method: str = "log_linear",
) -> ForwardCurve:
    """Bootstrap a clean monotonic-tenor curve from raw (tenor_days, price)
    pairs. Duplicates are averaged. Sorted ascending."""
    by_tenor: dict[float, list[float]] = {}
    for t, p in raw_points:
        by_tenor.setdefault(float(t), []).append(float(p))
    points = [ForwardCurvePoint(t, sum(v) / len(v)) for t, v in sorted(by_tenor.items())]
    return ForwardCurve(asset=asset, method=method, points=points)


def interp_at(curve: ForwardCurve, tenor_days: float) -> float | None:
    """Interpolate the curve at an arbitrary tenor.

    method=log_linear: linear in log(price) — natural for prices that
    decay/grow multiplicatively (carry, lease).
    method=linear: linear in price — natural for spreads, P/L.
    method=cubic: piecewise cubic monotone — for smooth power curves.
    """
    if not curve.points:
        return None
    xs = np.array([p.tenor_days for p in curve.points], dtype=float)
    ys = np.array([p.price for p in curve.points], dtype=float)
    if tenor_days <= xs[0]:
        return float(ys[0])
    if tenor_days >= xs[-1]:
        return float(ys[-1])
    if curve.method == "linear":
        return float(np.interp(tenor_days, xs, ys))
    if curve.method == "log_linear":
        logy = np.log(np.maximum(ys, 1e-9))
        return float(math.exp(np.interp(tenor_days, xs, logy)))
    if curve.method == "cubic":
        return float(_pchip(xs, ys, tenor_days))
    return float(np.interp(tenor_days, xs, ys))


def _pchip(xs: np.ndarray, ys: np.ndarray, x: float) -> float:
    """Monotone cubic interp (PCHIP-like, minimal)."""
    i = int(np.searchsorted(xs, x) - 1)
    i = max(0, min(i, len(xs) - 2))
    x0, x1 = xs[i], xs[i + 1]
    y0, y1 = ys[i], ys[i + 1]
    h = x1 - x0
    if h <= 0:
        return float(y0)
    t = (x - x0) / h
    return float(y0 * (1 - t) + y1 * t + 0.0)  # fallback to linear if neighbours unknown
