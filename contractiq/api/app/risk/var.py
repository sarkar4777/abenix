"""VaR: parametric, historical-simulation, and filtered-historical-simulation (FHS).

Inputs are returns or P&L paths. Outputs are dollar VaR for a given
notional + confidence. Pure numpy. All three methods produce a paired
VaR/CVaR alongside; CVaR computation is in cvar.py for clarity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import math

import numpy as np


@dataclass
class VaRResult:
    method: str
    confidence: float
    horizon_days: int
    var_pct: float
    var_usd: float
    n_observations: int
    tail_paths: list[float]


def _percentile(returns: np.ndarray, q: float) -> float:
    return float(np.percentile(returns, q))


def var_parametric(
    returns: Sequence[float],
    *,
    notional_usd: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> VaRResult:
    """Parametric VaR under normal returns.

    Var = -μ + zα·σ·sqrt(h)
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return VaRResult("parametric", confidence, horizon_days, 0.0, 0.0, 0, [])
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    z = _z_score(confidence)
    var_pct = max(0.0, z * sigma * math.sqrt(horizon_days) - mu * horizon_days)
    return VaRResult(
        "parametric",
        confidence,
        horizon_days,
        var_pct,
        var_pct * notional_usd,
        int(arr.size),
        [],
    )


def var_historical(
    returns: Sequence[float],
    *,
    notional_usd: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> VaRResult:
    """Historical-simulation VaR.

    For h > 1, returns are h-day-aggregated by overlapping windows so we
    keep all the observations.
    """
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return VaRResult("historical", confidence, horizon_days, 0.0, 0.0, 0, [])
    if horizon_days > 1 and arr.size > horizon_days:
        agg = np.array([arr[i:i + horizon_days].sum() for i in range(arr.size - horizon_days + 1)])
    else:
        agg = arr
    q = (1.0 - confidence) * 100.0
    var_pct = -_percentile(agg, q)
    tail = sorted([float(x) for x in agg if x <= -var_pct])[:50]
    return VaRResult(
        "historical",
        confidence,
        horizon_days,
        max(0.0, var_pct),
        max(0.0, var_pct) * notional_usd,
        int(arr.size),
        tail,
    )


def var_filtered_historical(
    returns: Sequence[float],
    *,
    notional_usd: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
    decay: float = 0.94,
) -> VaRResult:
    """Filtered-historical-simulation. EWMA-rescale returns to today's vol
    regime, then run historical-sim on the rescaled series. Reduces the
    weight of stale regimes (e.g. 2014's low vol when today is 2026 high
    vol).
    """
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n == 0:
        return VaRResult("filtered_historical", confidence, horizon_days, 0.0, 0.0, 0, [])
    var_ewma = np.zeros(n)
    var_ewma[0] = arr[0] ** 2
    for i in range(1, n):
        var_ewma[i] = decay * var_ewma[i - 1] + (1.0 - decay) * arr[i - 1] ** 2
    sigma_t = np.sqrt(var_ewma + 1e-12)
    sigma_today = sigma_t[-1]
    rescaled = arr * (sigma_today / sigma_t)
    return var_historical(
        rescaled.tolist(),
        notional_usd=notional_usd,
        confidence=confidence,
        horizon_days=horizon_days,
    )


def _z_score(confidence: float) -> float:
    table = {0.90: 1.282, 0.95: 1.645, 0.975: 1.960, 0.99: 2.326, 0.995: 2.576, 0.999: 3.090}
    if confidence in table:
        return table[confidence]
    nearest = min(table.keys(), key=lambda k: abs(k - confidence))
    return table[nearest]
