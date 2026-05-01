"""Remaining-useful-life estimator — pure stdlib.

Reads a chronological history of health readings from stdin and
returns the estimated hours remaining before the asset crosses a
failure threshold. Uses an exponential fit first, falls back to
linear if exponential is worse or numerically unstable.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime


def parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Returns (slope, intercept, r_squared)."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    if den == 0:
        return 0.0, my, 0.0
    slope = num / den
    intercept = my - slope * mx
    ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(n))
    ss_tot = sum((ys[i] - my) ** 2 for i in range(n))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return slope, intercept, r2


def exponential_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Fit ys = a * exp(-k * xs) by regressing log(ys) on xs.

    Returns (k, a, r_squared_on_original_scale). Values of y ≤ 0 are
    guarded so tiny positive floor is used.
    """
    log_ys = [math.log(max(y, 1e-6)) for y in ys]
    slope, intercept, _ = linear_regression(xs, log_ys)
    k = -slope  # we model y = a * exp(-k*t), so slope of log(y) is -k
    a = math.exp(intercept)
    # Compute R² on the ORIGINAL scale, not log scale — otherwise
    # we'd compare the wrong thing against the linear fallback.
    preds = [a * math.exp(-k * x) for x in xs]
    my = sum(ys) / len(ys)
    ss_res = sum((ys[i] - preds[i]) ** 2 for i in range(len(ys)))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
    return k, a, r2


def main() -> int:
    raw = sys.stdin.read() or "{}"
    data = json.loads(raw)
    readings = data.get("readings") or []
    threshold = float(data.get("failure_threshold", 0.35))

    if len(readings) < 4:
        print(json.dumps({"error": "need at least 4 readings"}))
        return 1

    # Convert to (hours_since_first, health_score).
    t0 = parse_iso(readings[0]["timestamp"])
    xs: list[float] = []
    ys: list[float] = []
    for r in readings:
        t = parse_iso(r["timestamp"])
        dt_hours = (t - t0).total_seconds() / 3600.0
        xs.append(dt_hours)
        ys.append(float(r["health_score"]))

    last_x = xs[-1]
    last_y = ys[-1]

    # Already below threshold? RUL is 0.
    if last_y <= threshold:
        print(json.dumps({
            "rul_hours": 0.0,
            "confidence": 1.0,
            "model": "observed",
            "trend_slope": 0.0,
            "last_health": last_y,
            "horizon_samples": len(readings),
        }))
        return 0

    slope_lin, intercept_lin, r2_lin = linear_regression(xs, ys)
    k_exp, a_exp, r2_exp = exponential_fit(xs, ys)

    # Pick the better fit. Exponential is usually the right physics for
    # degradation, but linear wins for near-constant or plateaued series.
    if r2_exp >= r2_lin and k_exp > 0 and math.isfinite(k_exp):
        # y(t_fail) = a * exp(-k * t_fail) = threshold
        # t_fail = -ln(threshold / a) / k
        t_fail = -math.log(max(threshold, 1e-9) / max(a_exp, 1e-9)) / k_exp
        rul = max(0.0, t_fail - last_x)
        trend_at_now = -k_exp * a_exp * math.exp(-k_exp * last_x)
        print(json.dumps({
            "rul_hours": round(rul, 2),
            "confidence": round(max(0.0, min(1.0, r2_exp)), 3),
            "model": "exponential",
            "trend_slope": round(trend_at_now, 6),
            "last_health": last_y,
            "horizon_samples": len(readings),
        }))
        return 0

    # Linear fallback: y = slope*x + intercept; solve for x_fail
    if slope_lin >= 0:
        # Not degrading on linear trend — RUL is effectively infinite.
        print(json.dumps({
            "rul_hours": 1e6,
            "confidence": round(max(0.0, min(1.0, r2_lin)), 3),
            "model": "linear",
            "trend_slope": round(slope_lin, 6),
            "last_health": last_y,
            "horizon_samples": len(readings),
            "note": "health not degrading — RUL unbounded",
        }))
        return 0

    x_fail = (threshold - intercept_lin) / slope_lin
    rul = max(0.0, x_fail - last_x)
    print(json.dumps({
        "rul_hours": round(rul, 2),
        "confidence": round(max(0.0, min(1.0, r2_lin)), 3),
        "model": "linear",
        "trend_slope": round(slope_lin, 6),
        "last_health": last_y,
        "horizon_samples": len(readings),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
