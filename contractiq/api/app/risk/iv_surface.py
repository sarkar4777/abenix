"""Implied-vol surface fit. Tiny SVI-like param fit per tenor slice. Sparse-data fallback to log-normal interp."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class IVPoint:
    tenor_days: float
    log_moneyness: float
    iv: float


def fit_iv_surface(points: Sequence[IVPoint]) -> dict[str, object]:
    if not points:
        return {"tenors": [], "smiles": {}, "atm_term_structure": []}
    by_tenor: dict[float, list[IVPoint]] = {}
    for p in points:
        by_tenor.setdefault(p.tenor_days, []).append(p)
    smiles: dict[str, list[dict[str, float]]] = {}
    atm = []
    for tenor in sorted(by_tenor.keys()):
        slice_ = sorted(by_tenor[tenor], key=lambda x: x.log_moneyness)
        ms = np.array([p.log_moneyness for p in slice_])
        ivs = np.array([p.iv for p in slice_])
        if len(ms) >= 3:
            poly = np.polyfit(ms, ivs, deg=min(2, len(ms) - 1))
            smile_points = [{"k": float(m), "iv": float(np.polyval(poly, m))} for m in np.linspace(ms.min(), ms.max(), 21)]
        else:
            smile_points = [{"k": float(m), "iv": float(v)} for m, v in zip(ms, ivs)]
        smiles[str(tenor)] = smile_points
        atm_iv = float(np.interp(0.0, ms, ivs)) if ms.min() <= 0 <= ms.max() else float(ivs.mean())
        atm.append({"tenor_days": float(tenor), "atm_iv": atm_iv})
    return {"tenors": list(smiles.keys()), "smiles": smiles, "atm_term_structure": atm}
