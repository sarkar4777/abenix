"""Risk REST surface — VaR / CVaR / forward curve / correlations.

Every financial calculation runs in an Abenix agent now. The router
validates input, fetches market-data series via the registered
adapters, delegates the math to the contractiq-risk-* agents through
the SDK, and persists the result. Keeps the router thin so audit and
governance live with the agent runtime, not inline in FastAPI.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.market_data import adapters  # noqa: F401
from app.market_data.registry import fetch as md_fetch
from app.models.contractiq_models import (
    ContractIQContract,  # noqa: F401 — kept for downstream import compatibility
    ContractIQRiskRun,
    ContractIQUser,
)
from app.risk import (
    bootstrap_curve,
    interp_at,
)
from app.routers.auth import get_contractiq_user

# Same SDK-path bootstrap used by commodities.py. Idempotent.
_SDK_PATH = str(Path(__file__).resolve().parents[2] / "sdk")
if _SDK_PATH not in sys.path:
    sys.path.insert(0, _SDK_PATH)

from abenix_sdk import Abenix, ActingSubject  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/risk", tags=["contractiq-risk"])


# ───── helpers ─────────────────────────────────────────────────────────


def _calc_signature(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


def _parse_json_blob(text: str) -> dict | None:
    """Lenient extractor for agent output — strips fences, tolerates prose."""
    if not text:
        return None
    cleaned = text.strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        pass
    fence = re.search(r"```(?:json)?\s*\n([\s\S]*?)```", cleaned)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


async def _call_agent(
    user: ContractIQUser,
    agent_slug: str,
    payload: dict[str, Any],
    timeout: float = 300.0,
) -> tuple[dict | None, dict]:
    """Run an Abenix agent with `actAs` delegation and return (parsed_json, meta)."""
    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://localhost:8000")
    if not api_key:
        raise RuntimeError("CONTRACTIQ_ABENIX_API_KEY not configured")

    subject = ActingSubject(
        subject_type="contractiq",
        subject_id=str(user.id),
        email=user.email,
        display_name=user.full_name,
    )
    async with Abenix(
        api_key=api_key, base_url=api_base, act_as=subject, timeout=timeout
    ) as forge:
        result = await forge.execute(agent_slug, json.dumps(payload, default=str))
        parsed = _parse_json_blob(result.output or "")
        meta = {
            "execution_id": str(getattr(result, "execution_id", "") or ""),
            "duration_ms": result.duration_ms or 0,
            "cost_usd": float(result.cost or 0.0),
            "model": getattr(result, "model", None),
            "tool_calls": len(result.tool_calls or []),
            "input_tokens": result.input_tokens or 0,
            "output_tokens": result.output_tokens or 0,
        }
        return parsed, meta


# ───── endpoints ───────────────────────────────────────────────────────


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

    # Market data fetch stays in the router — adapters + DB caching are
    # router-tier concerns. The agent only sees the resolved series.
    md = await md_fetch(source, db, {"history_days": history_days})
    series = md.series or []
    returns = body.get("returns") or None

    if not returns and not series:
        return error("no returns available — pass `returns: [..]` or use a source with history", 400)

    agent_payload: dict[str, Any] = {
        "op": "var",
        "notional_usd": notional_usd,
        "confidence": confidence,
        "horizon_days": horizon,
        "method": method,
    }
    if returns:
        agent_payload["returns"] = returns
    else:
        agent_payload["series"] = series

    try:
        result, _meta = await _call_agent(user, "contractiq-risk-calculator", agent_payload)
    except Exception as e:
        logger.exception("VaR agent invocation failed")
        return error(f"Risk calculator agent failed: {e}", 503)
    if not result or result.get("error"):
        return error(f"Risk calculator returned no usable result: {(result or {}).get('error', 'empty')}", 502)

    sig_input = {
        "source": source,
        "notional_usd": notional_usd,
        "confidence": confidence,
        "horizon_days": horizon,
        "method": method,
        "n_obs": result.get("n_observations"),
        "first_ts": (series[0].get("ts") if series else None),
        "last_ts": (series[-1].get("ts") if series else None),
    }
    sig = _calc_signature(sig_input)

    tail_paths = list(result.get("tail_paths") or [])
    row = ContractIQRiskRun(
        user_id=user.id,
        kind="var",
        scope="single",
        contract_id=(uuid.UUID(body["contract_id"]) if body.get("contract_id") else None),
        confidence=confidence,
        horizon_days=horizon,
        method=method,
        var_usd=float(result.get("var_usd") or 0.0),
        # cvar_usd: field name from contractiq-risk-calculator agent output (pass-through)
        cvar_usd=float(result.get("cvar_usd") or 0.0),
        base_notional_usd=notional_usd,
        drivers=[{"source": source}],
        tail_paths=tail_paths,
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
        "var_pct": float(result.get("var_pct") or 0.0),
        "var_usd": float(result.get("var_usd") or 0.0),
        # cvar_pct / cvar_usd: field names from contractiq-risk-calculator agent (pass-through)
        "cvar_pct": float(result.get("cvar_pct") or 0.0),
        "cvar_usd": float(result.get("cvar_usd") or 0.0),
        "n_observations": int(result.get("n_observations") or 0),
        "n_tail_observations": int(result.get("n_tail_observations") or 0),
        "tail_paths_sample": tail_paths[:20],
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
    history_days = int(body.get("history_days") or 250)

    # Resolve each position's series via the router-side adapters so the
    # agent never has to talk to market-data infra directly.
    resolved: list[dict[str, Any]] = []
    for p in positions:
        source = p.get("source") or "lbma_gold_fix"
        notional = float(p.get("notional_usd") or 0)
        md = await md_fetch(source, db, {"history_days": history_days})
        entry: dict[str, Any] = {"source": source, "notional_usd": notional}
        if p.get("returns"):
            entry["returns"] = p["returns"]
        else:
            entry["series"] = md.series or []
        resolved.append(entry)

    agent_payload = {
        "op": "portfolio_var",
        "positions": resolved,
        "confidence": confidence,
        "horizon_days": horizon,
    }
    try:
        result, _meta = await _call_agent(user, "contractiq-risk-calculator", agent_payload)
    except Exception as e:
        logger.exception("Portfolio VaR agent invocation failed")
        return error(f"Risk calculator agent failed: {e}", 503)
    if not result or result.get("error"):
        return error(f"Risk calculator returned no usable result: {(result or {}).get('error', 'empty')}", 502)

    return success({
        "portfolio_var_usd": float(result.get("portfolio_var_usd") or 0.0),
        # portfolio_cvar_usd: field name from contractiq-risk-calculator agent (pass-through)
        "portfolio_cvar_usd": float(result.get("portfolio_cvar_usd") or 0.0),
        "confidence": confidence,
        "horizon_days": horizon,
        "total_notional_usd": float(result.get("total_notional_usd") or 0.0),
        "diversification_benefit_usd": float(result.get("diversification_benefit_usd") or 0.0),
        "per_position": result.get("per_position") or [],
    })


@router.post("/marginal-var")
async def marginal_var(
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    base = body.get("base_positions") or []
    proposal = body.get("proposed_position") or {}
    if not proposal:
        return error("`proposed_position` is required", 400)
    confidence = float(body.get("confidence") or 0.95)
    horizon = int(body.get("horizon_days") or 1)
    history_days = int(body.get("history_days") or 250)

    async def _resolve(pos: dict) -> dict:
        source = pos.get("source") or "lbma_gold_fix"
        notional = float(pos.get("notional_usd") or 0)
        entry: dict[str, Any] = {"source": source, "notional_usd": notional}
        if pos.get("returns"):
            entry["returns"] = pos["returns"]
        else:
            md = await md_fetch(source, db, {"history_days": history_days})
            entry["series"] = md.series or []
        return entry

    base_resolved = [await _resolve(p) for p in base]
    proposal_resolved = await _resolve(proposal)

    agent_payload = {
        "op": "marginal_var",
        "base_positions": base_resolved,
        "proposed_position": proposal_resolved,
        "confidence": confidence,
        "horizon_days": horizon,
    }
    try:
        result, _meta = await _call_agent(user, "contractiq-marginal-var-analyzer", agent_payload)
    except Exception as e:
        logger.exception("Marginal VaR agent invocation failed")
        return error(f"Marginal VaR agent failed: {e}", 503)
    if not result or result.get("error"):
        return error(f"Marginal VaR agent returned no usable result: {(result or {}).get('error', 'empty')}", 502)

    return success({
        "base_var_usd": float(result.get("base_var_usd") or 0.0),
        "new_var_usd": float(result.get("new_var_usd") or 0.0),
        "marginal_var_usd": float(result.get("marginal_var_usd") or 0.0),
        "marginal_var_pct_of_base": result.get("marginal_var_pct_of_base"),
    })


@router.get("/correlations")
async def correlations(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    sources: str = Query("lbma_gold_fix,lbma_silver_price,lppm_platinum_fix,lppm_palladium_fix"),
    history_days: int = Query(120, ge=10, le=365),
) -> JSONResponse:
    slugs = [s.strip() for s in sources.split(",") if s.strip()]
    series_map: dict[str, list[dict[str, Any]]] = {}
    for slug in slugs:
        md = await md_fetch(slug, db, {"history_days": history_days})
        series_map[slug] = md.series or []

    agent_payload = {
        "op": "correlations",
        "series": series_map,
        "decay": 0.94,
        "method": "ewma",
        "history_days": history_days,
    }
    try:
        result, _meta = await _call_agent(user, "contractiq-correlations", agent_payload)
    except Exception as e:
        logger.exception("Correlations agent invocation failed")
        return error(f"Correlations agent failed: {e}", 503)
    if not result or result.get("error"):
        return error(f"Correlations agent returned no usable result: {(result or {}).get('error', 'empty')}", 502)

    return success({
        "matrix": result.get("matrix") or {},
        "sources": result.get("sources") or slugs,
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
            # cvar_usd: ContractIQRiskRun DB column populated from agent output
            "cvar_usd": r.cvar_usd,
            "base_notional_usd": r.base_notional_usd,
            "calc_signature": r.calc_signature,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])
