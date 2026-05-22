"""CVaR / Expected Shortfall — average loss conditional on being beyond VaR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class CVaRResult:
    method: str
    confidence: float
    horizon_days: int
    cvar_pct: float
    cvar_usd: float
    var_pct: float
    var_usd: float
    n_tail_observations: int


def cvar(
    returns: Sequence[float],
    *,
    notional_usd: float,
    confidence: float = 0.95,
    horizon_days: int = 1,
    method: str = "historical",
) -> CVaRResult:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return CVaRResult(method, confidence, horizon_days, 0.0, 0.0, 0.0, 0.0, 0)
    if horizon_days > 1 and arr.size > horizon_days:
        agg = np.array([arr[i:i + horizon_days].sum() for i in range(arr.size - horizon_days + 1)])
    else:
        agg = arr
    q = (1.0 - confidence) * 100.0
    var_pct = -float(np.percentile(agg, q))
    tail = agg[agg <= -var_pct]
    cvar_pct = max(0.0, -float(tail.mean()) if tail.size else var_pct)
    return CVaRResult(
        method,
        confidence,
        horizon_days,
        cvar_pct,
        cvar_pct * notional_usd,
        max(0.0, var_pct),
        max(0.0, var_pct) * notional_usd,
        int(tail.size),
    )
