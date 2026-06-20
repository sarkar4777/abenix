"""Deterministic VaR / CVaR / correlation / marginal-VaR engine.

Reads a JSON envelope on stdin:

  {
    "op": "var" | "portfolio_var" | "marginal_var" | "correlations",
    ...op-specific fields...
  }

Writes a JSON envelope on stdout. Pure numpy/pandas math — no I/O, no
LLM. Called by contractiq_risk_calculator / contractiq_correlations /
contractiq_marginal_var_analyzer agents via the `code_asset` tool.

The agent supplies the returns + notionals (or full portfolio); this
binary does the deterministic compute the router used to call inline.
Keeps the routers thin and lets the runtime audit-log the exact math.
"""

from __future__ import annotations

import json
import math
import sys
from typing import Any, Sequence

import numpy as np


# ───── core stats helpers ─────────────────────────────────────────────

_Z = {0.90: 1.282, 0.95: 1.645, 0.975: 1.960, 0.99: 2.326, 0.995: 2.576, 0.999: 3.090}


def _z_score(confidence: float) -> float:
    if confidence in _Z:
        return _Z[confidence]
    nearest = min(_Z, key=lambda k: abs(k - confidence))
    return _Z[nearest]


def _returns_from_series(series: list[dict[str, Any]] | None) -> list[float]:
    if not series:
        return []
    closes = [float(p["close"]) for p in series if p.get("close") is not None]
    if len(closes) < 2:
        return []
    return [float(math.log(closes[i] / closes[i - 1])) for i in range(1, len(closes))]


def _resolve_returns(payload: dict[str, Any]) -> list[float]:
    """Accept either `returns: [..]` or `series: [{close: ..}, ..]`."""
    rets = payload.get("returns")
    if isinstance(rets, list) and rets:
        return [float(r) for r in rets]
    return _returns_from_series(payload.get("series"))


# ───── VaR / CVaR ─────────────────────────────────────────────────────


def var_parametric(returns: Sequence[float], notional_usd: float, confidence: float, horizon_days: int) -> dict:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return {"method": "parametric", "var_pct": 0.0, "var_usd": 0.0, "n_observations": 0, "tail_paths": []}
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1)) if arr.size > 1 else 0.0
    z = _z_score(confidence)
    var_pct = max(0.0, z * sigma * math.sqrt(horizon_days) - mu * horizon_days)
    return {
        "method": "parametric",
        "var_pct": var_pct,
        "var_usd": var_pct * notional_usd,
        "n_observations": int(arr.size),
        "tail_paths": [],
    }


def var_historical(returns: Sequence[float], notional_usd: float, confidence: float, horizon_days: int) -> dict:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return {"method": "historical", "var_pct": 0.0, "var_usd": 0.0, "n_observations": 0, "tail_paths": []}
    if horizon_days > 1 and arr.size > horizon_days:
        agg = np.array([arr[i:i + horizon_days].sum() for i in range(arr.size - horizon_days + 1)])
    else:
        agg = arr
    q = (1.0 - confidence) * 100.0
    var_pct = -float(np.percentile(agg, q))
    var_pct = max(0.0, var_pct)
    tail = sorted([float(x) for x in agg if x <= -var_pct])[:50]
    return {
        "method": "historical",
        "var_pct": var_pct,
        "var_usd": var_pct * notional_usd,
        "n_observations": int(arr.size),
        "tail_paths": tail,
    }


def var_filtered_historical(returns: Sequence[float], notional_usd: float, confidence: float, horizon_days: int, decay: float = 0.94) -> dict:
    arr = np.asarray(returns, dtype=float)
    n = arr.size
    if n == 0:
        return {"method": "filtered_historical", "var_pct": 0.0, "var_usd": 0.0, "n_observations": 0, "tail_paths": []}
    var_ewma = np.zeros(n)
    var_ewma[0] = arr[0] ** 2
    for i in range(1, n):
        var_ewma[i] = decay * var_ewma[i - 1] + (1.0 - decay) * arr[i - 1] ** 2
    sigma_t = np.sqrt(var_ewma + 1e-12)
    sigma_today = sigma_t[-1]
    rescaled = (arr * (sigma_today / sigma_t)).tolist()
    out = var_historical(rescaled, notional_usd, confidence, horizon_days)
    out["method"] = "filtered_historical"
    return out


def cvar(returns: Sequence[float], notional_usd: float, confidence: float, horizon_days: int, method: str = "historical") -> dict:
    arr = np.asarray(returns, dtype=float)
    if arr.size == 0:
        return {"method": method, "cvar_pct": 0.0, "cvar_usd": 0.0, "var_pct": 0.0, "var_usd": 0.0, "n_tail_observations": 0}
    if horizon_days > 1 and arr.size > horizon_days:
        agg = np.array([arr[i:i + horizon_days].sum() for i in range(arr.size - horizon_days + 1)])
    else:
        agg = arr
    q = (1.0 - confidence) * 100.0
    var_pct = max(0.0, -float(np.percentile(agg, q)))
    tail = agg[agg <= -var_pct]
    cvar_pct = max(0.0, -float(tail.mean()) if tail.size else var_pct)
    return {
        "method": method,
        "cvar_pct": cvar_pct,
        "cvar_usd": cvar_pct * notional_usd,
        "var_pct": var_pct,
        "var_usd": var_pct * notional_usd,
        "n_tail_observations": int(tail.size),
    }


def _compute_var(returns: Sequence[float], notional_usd: float, confidence: float, horizon_days: int, method: str) -> dict:
    if method == "parametric":
        return var_parametric(returns, notional_usd, confidence, horizon_days)
    if method == "historical":
        return var_historical(returns, notional_usd, confidence, horizon_days)
    return var_filtered_historical(returns, notional_usd, confidence, horizon_days)


# ───── correlation matrix ─────────────────────────────────────────────


def correlation_matrix(series_map: dict[str, Sequence[float]], decay: float = 0.94, method: str = "ewma") -> dict:
    names = sorted(series_map.keys())
    if len(names) < 2:
        return {n: {n: 1.0} for n in names}
    arrs = [np.asarray(series_map[n], dtype=float) for n in names]
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
    return {n: {m: round(float(corr[i, j]), 6) for j, m in enumerate(names)} for i, n in enumerate(names)}


# ───── portfolio + marginal VaR ───────────────────────────────────────


def _portfolio_var(positions: list[dict], confidence: float, horizon_days: int) -> dict:
    per_pos = []
    portfolio_returns_by_day: dict[int, float] = {}
    for p in positions:
        notional = float(p.get("notional_usd") or 0)
        rets = _resolve_returns(p)
        if not rets:
            continue
        v = var_filtered_historical(rets, notional, confidence, horizon_days)
        c = cvar(rets, notional, confidence, horizon_days)
        per_pos.append({
            "position": {k: v_ for k, v_ in p.items() if k != "series"},
            "var_usd": v["var_usd"],
            "cvar_usd": c["cvar_usd"],
        })
        # Cap at 250d for shape parity with the original router.
        tail = rets[-min(len(rets), 250):]
        for i, ret in enumerate(tail):
            portfolio_returns_by_day[i] = portfolio_returns_by_day.get(i, 0.0) + ret * notional

    if not portfolio_returns_by_day:
        return {"error": "no positions had usable history"}
    port_rets = list(portfolio_returns_by_day.values())
    total_notional = sum(float(p.get("notional_usd") or 0) for p in positions)
    norm = [r / total_notional for r in port_rets] if total_notional else port_rets
    p_var = var_filtered_historical(norm, total_notional, confidence, horizon_days)
    p_cvar = cvar(norm, total_notional, confidence, horizon_days)
    sum_individual = sum(p["var_usd"] for p in per_pos)
    diversification = max(0.0, sum_individual - p_var["var_usd"])
    return {
        "portfolio_var_usd": p_var["var_usd"],
        "portfolio_cvar_usd": p_cvar["cvar_usd"],
        "confidence": confidence,
        "horizon_days": horizon_days,
        "total_notional_usd": total_notional,
        "diversification_benefit_usd": diversification,
        "per_position": per_pos,
    }


# ───── operation dispatch ─────────────────────────────────────────────


def _op_var(payload: dict) -> dict:
    confidence = float(payload.get("confidence") or 0.95)
    horizon = int(payload.get("horizon_days") or 1)
    method = payload.get("method") or "filtered_historical"
    notional = float(payload.get("notional_usd") or 0)
    returns = _resolve_returns(payload)
    if not returns:
        return {"error": "no returns available"}
    v = _compute_var(returns, notional, confidence, horizon, method)
    c = cvar(returns, notional, confidence, horizon, method)
    return {
        "method": method,
        "confidence": confidence,
        "horizon_days": horizon,
        "var_pct": v["var_pct"],
        "var_usd": v["var_usd"],
        "cvar_pct": c["cvar_pct"],
        "cvar_usd": c["cvar_usd"],
        "n_observations": v["n_observations"],
        "n_tail_observations": c["n_tail_observations"],
        "tail_paths": v["tail_paths"],
    }


def _op_portfolio_var(payload: dict) -> dict:
    positions = payload.get("positions") or []
    confidence = float(payload.get("confidence") or 0.95)
    horizon = int(payload.get("horizon_days") or 1)
    if not positions:
        return {"error": "`positions` is required"}
    return _portfolio_var(positions, confidence, horizon)


def _op_marginal_var(payload: dict) -> dict:
    base = payload.get("base_positions") or []
    proposal = payload.get("proposed_position") or {}
    confidence = float(payload.get("confidence") or 0.95)
    horizon = int(payload.get("horizon_days") or 1)
    base_res = _portfolio_var(base, confidence, horizon) if base else {"portfolio_var_usd": 0.0}
    new_res = _portfolio_var(base + [proposal], confidence, horizon)
    base_var = float(base_res.get("portfolio_var_usd") or 0.0)
    new_var = float(new_res.get("portfolio_var_usd") or 0.0)
    marginal = new_var - base_var
    pct = (marginal / base_var * 100.0) if base_var else None
    return {
        "base_var_usd": base_var,
        "new_var_usd": new_var,
        "marginal_var_usd": marginal,
        "marginal_var_pct_of_base": pct,
        "confidence": confidence,
        "horizon_days": horizon,
    }


def _op_correlations(payload: dict) -> dict:
    series_input = payload.get("series") or {}
    series_map: dict[str, list[float]] = {}
    for slug, body in series_input.items():
        if isinstance(body, list) and body and isinstance(body[0], (int, float)):
            series_map[slug] = [float(x) for x in body]
        elif isinstance(body, dict):
            series_map[slug] = _resolve_returns(body)
        elif isinstance(body, list):
            series_map[slug] = _returns_from_series(body)
    decay = float(payload.get("decay") or 0.94)
    method = payload.get("method") or "ewma"
    matrix = correlation_matrix(series_map, decay=decay, method=method)
    return {
        "matrix": matrix,
        "sources": sorted(series_map.keys()),
        "history_days": payload.get("history_days"),
    }


_OPS = {
    "var": _op_var,
    "portfolio_var": _op_portfolio_var,
    "marginal_var": _op_marginal_var,
    "correlations": _op_correlations,
}


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid json: {e}"}))
        return 1
    op = (payload.get("op") or "").strip()
    handler = _OPS.get(op)
    if handler is None:
        print(json.dumps({"error": f"unknown op '{op}' — expected one of {sorted(_OPS)}"}))
        return 1
    try:
        result = handler(payload)
    except Exception as e:
        print(json.dumps({"error": f"{op} failed: {e}"}))
        return 1
    print(json.dumps(result, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
