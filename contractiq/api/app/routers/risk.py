"""Risk REST surface — VaR / CVaR / forward curve / correlations."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.market_data import adapters  # noqa: F401
from app.market_data.registry import fetch as md_fetch
from app.models.contractiq_models import (
    ContractIQContract,
    ContractIQRiskRun,
    ContractIQUser,
)
from app.risk import (
    bootstrap_curve,
    correlation_matrix,
    cvar as cvar_fn,
    interp_at,
    var_filtered_historical,
    var_historical,
    var_parametric,
)
from app.routers.auth import get_contractiq_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/risk", tags=["contractiq-risk"])


def _calc_signature(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _returns_from_series(series: list[dict[str, Any]] | None) -> list[float]:
    if not series:
        return []
    closes = [float(p["close"]) for p in series if p.get("close") is not None]
    if len(closes) < 2:
        return []
    return [float(np.log(closes[i] / closes[i - 1])) for i in range(1, len(closes))]


@router.post("/var")
async def compute_var(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    source = body.get("source") or "lbma_gold_fix"
    notional_usd = float(body.get("notional_usd") or 0)
    confidence = float(body.get("confidence") or 0.95)
    horizon = int(body.get("horizon_days") or 1)
    method = body.get("method") or "filtered_historical"
    history_days = int(body.get("history_days") or 250)

    md = await md_fetch(source, db, {"history_days": history_days})
    returns = body.get("returns") or _returns_from_series(md.series)
    if not returns:
        return error("no returns available — pass `returns: [..]` or use a source with history", 400)

    if method == "parametric":
        v = var_parametric(returns, notional_usd=notional_usd, confidence=confidence, horizon_days=horizon)
    elif method == "historical":
        v = var_historical(returns, notional_usd=notional_usd, confidence=confidence, horizon_days=horizon)
    else:
        v = var_filtered_historical(returns, notional_usd=notional_usd, confidence=confidence, horizon_days=horizon)
    c = cvar_fn(returns, notional_usd=notional_usd, confidence=confidence, horizon_days=horizon, method=method)

    sig_input = {
        "source": source,
        "notional_usd": notional_usd,
        "confidence": confidence,
        "horizon_days": horizon,
        "method": method,
        "n_obs": v.n_observations,
        "first_ts": (md.series or [{}])[0].get("ts") if md.series else None,
        "last_ts": (md.series or [{}])[-1].get("ts") if md.series else None,
    }
    sig = _calc_signature(sig_input)

    row = ContractIQRiskRun(
        user_id=user.id,
        kind="var",
        scope="single",
        contract_id=(uuid.UUID(body["contract_id"]) if body.get("contract_id") else None),
        confidence=confidence,
        horizon_days=horizon,
        method=method,
        var_usd=v.var_usd,
        cvar_usd=c.cvar_usd,
        base_notional_usd=notional_usd,
        drivers=[{"source": source}],
        tail_paths=v.tail_paths,
        config=sig_input,
        calc_signature=sig,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return success({
        "id": str(row.id),
        "method": method,
        "confidence": confidence,
        "horizon_days": horizon,
        "var_pct": v.var_pct,
        "var_usd": v.var_usd,
        "cvar_pct": c.cvar_pct,
        "cvar_usd": c.cvar_usd,
        "n_observations": v.n_observations,
        "n_tail_observations": c.n_tail_observations,
        "tail_paths_sample": v.tail_paths[:20],
        "source": source,
        "calc_signature": sig,
    })


@router.post("/portfolio/var")
async def portfolio_var(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    positions = body.get("positions") or []
    if not positions:
        return error("`positions` is required", 400)
    confidence = float(body.get("confidence") or 0.95)
    horizon = int(body.get("horizon_days") or 1)

    per_pos = []
    portfolio_returns_by_day: dict[int, float] = {}
    for p in positions:
        source = p.get("source") or "lbma_gold_fix"
        notional = float(p.get("notional_usd") or 0)
        md = await md_fetch(source, db, {"history_days": int(body.get("history_days") or 250)})
        rets = _returns_from_series(md.series)
        if not rets:
            continue
        v = var_filtered_historical(rets, notional_usd=notional, confidence=confidence, horizon_days=horizon)
        c = cvar_fn(rets, notional_usd=notional, confidence=confidence, horizon_days=horizon)
        per_pos.append({
            "position": p,
            "var_usd": v.var_usd,
            "cvar_usd": c.cvar_usd,
        })
        for i, ret in enumerate(rets[-min(len(rets), 250):]):
            portfolio_returns_by_day[i] = portfolio_returns_by_day.get(i, 0.0) + ret * notional

    if not portfolio_returns_by_day:
        return error("no positions had usable history", 400)
    port_rets = list(portfolio_returns_by_day.values())
    total_notional = sum(float(p.get("notional_usd") or 0) for p in positions)
    norm = [r / total_notional for r in port_rets] if total_notional else port_rets
    portfolio_var = var_filtered_historical(norm, notional_usd=total_notional, confidence=confidence, horizon_days=horizon)
    portfolio_cvar = cvar_fn(norm, notional_usd=total_notional, confidence=confidence, horizon_days=horizon)

    sum_individual = sum(p["var_usd"] for p in per_pos)
    diversification = max(0.0, sum_individual - portfolio_var.var_usd)

    return success({
        "portfolio_var_usd": portfolio_var.var_usd,
        "portfolio_cvar_usd": portfolio_cvar.cvar_usd,
        "confidence": confidence,
        "horizon_days": horizon,
        "total_notional_usd": total_notional,
        "diversification_benefit_usd": diversification,
        "per_position": per_pos,
    })


@router.post("/marginal-var")
async def marginal_var(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    base = body.get("base_positions") or []
    proposal = body.get("proposed_position") or {}
    base_call = await portfolio_var({"positions": base, "confidence": body.get("confidence", 0.95), "horizon_days": body.get("horizon_days", 1), "history_days": body.get("history_days", 250)}, user, db)
    new_call = await portfolio_var({"positions": base + [proposal], "confidence": body.get("confidence", 0.95), "horizon_days": body.get("horizon_days", 1), "history_days": body.get("history_days", 250)}, user, db)
    base_data = (await base_call.body_iterator.__anext__()) if hasattr(base_call, 'body_iterator') else None  # not used
    # Cleaner: re-derive from JSON
    import json as _json
    base_json = _json.loads(base_call.body.decode())
    new_json = _json.loads(new_call.body.decode())
    base_var = float((base_json.get("data") or {}).get("portfolio_var_usd") or 0)
    new_var = float((new_json.get("data") or {}).get("portfolio_var_usd") or 0)
    return success({
        "base_var_usd": base_var,
        "new_var_usd": new_var,
        "marginal_var_usd": new_var - base_var,
        "marginal_var_pct_of_base": ((new_var - base_var) / base_var * 100.0) if base_var else None,
    })


@router.get("/correlations")
async def correlations(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    sources: str = Query("lbma_gold_fix,lbma_silver_price,lppm_platinum_fix,lppm_palladium_fix"),
    history_days: int = Query(120, ge=10, le=365),
) -> JSONResponse:
    slugs = [s.strip() for s in sources.split(",") if s.strip()]
    series = {}
    for slug in slugs:
        md = await md_fetch(slug, db, {"history_days": history_days})
        series[slug] = _returns_from_series(md.series)
    return success({
        "matrix": correlation_matrix(series, decay=0.94, method="ewma"),
        "sources": slugs,
        "history_days": history_days,
    })


@router.post("/forward-curve")
async def forward_curve(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    asset = body.get("asset") or "gold"
    pts = body.get("points") or []
    method = body.get("method") or "log_linear"
    if not pts:
        return error("`points` (list of [tenor_days, price]) is required", 400)
    curve = bootstrap_curve(asset, [(float(t), float(p)) for t, p in pts], method=method)
    sample_tenors = body.get("sample_tenors") or [30, 90, 180, 365]
    sampled = [{"tenor_days": t, "price": interp_at(curve, t)} for t in sample_tenors]
    return success({
        "asset": asset,
        "method": method,
        "points": [{"tenor_days": p.tenor_days, "price": p.price} for p in curve.points],
        "sampled": sampled,
    })


@router.get("/runs")
async def list_runs(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQRiskRun)
            .where(ContractIQRiskRun.user_id == user.id)
            .order_by(desc(ContractIQRiskRun.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([
        {
            "id": str(r.id),
            "kind": r.kind,
            "scope": r.scope,
            "contract_id": str(r.contract_id) if r.contract_id else None,
            "method": r.method,
            "confidence": r.confidence,
            "horizon_days": r.horizon_days,
            "var_usd": r.var_usd,
            "cvar_usd": r.cvar_usd,
            "base_notional_usd": r.base_notional_usd,
            "calc_signature": r.calc_signature,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])
