"""What-if analysis — type-aware. PPA / Gas / Metals each have their own
scenario library + agent prompt."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.models.contractiq_models import (
    ContractIQContract,
    ContractIQUser,
    ContractIQWhatIfRun,
)
from app.routers.auth import get_contractiq_user
from app.routers.insights import _call_abenix

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/whatif", tags=["contractiq-whatif"])


# Type-aware scenario library. Each entry is a template — the UI fills the values.
SCENARIO_LIBRARY: dict[str, list[dict[str, Any]]] = {
    "ppa": [
        {"id": "power_minus_20", "name": "Power price -20%", "perturbations": {"power_price_pct": -20}},
        {"id": "power_plus_15", "name": "Power price +15%", "perturbations": {"power_price_pct": 15}},
        {"id": "capacity_factor_minus_10", "name": "Capacity factor -10pp", "perturbations": {"capacity_factor_delta_pp": -10}},
        {"id": "fx_eurusd_minus_5", "name": "EUR weakens 5%", "perturbations": {"fx_eurusd_pct": -5}},
        {"id": "curtailment_event", "name": "10-day curtailment event", "perturbations": {"curtailment_days": 10}},
        {"id": "carbon_plus_30", "name": "EUA carbon +30%", "perturbations": {"eua_pct": 30}},
    ],
    "vppa": [
        {"id": "settlement_minus_15", "name": "Settlement price -15%", "perturbations": {"settlement_price_pct": -15}},
        {"id": "basis_minus_10", "name": "Basis widens 10%", "perturbations": {"basis_pct": -10}},
        {"id": "shape_factor_minus_5", "name": "Shape factor drops 5%", "perturbations": {"shape_pct": -5}},
    ],
    "gas": [
        {"id": "hh_minus_30", "name": "Henry Hub -30%", "perturbations": {"hh_pct": -30}},
        {"id": "ttf_plus_50", "name": "TTF +50% (cold snap)", "perturbations": {"ttf_pct": 50}},
        {"id": "demand_minus_20", "name": "Demand -20% (warm winter)", "perturbations": {"demand_pct": -20}},
        {"id": "tnp_outage_30d", "name": "30-day transport outage", "perturbations": {"transport_outage_days": 30}},
        {"id": "tor_miss", "name": "Take-or-pay miss this quarter", "perturbations": {"top_miss_pct": 100}},
        {"id": "jkm_arb_open", "name": "JKM-TTF arb opens $4/MMBtu", "perturbations": {"jkm_ttf_spread_usd": 4}},
    ],
    "tolling": [
        {"id": "feed_minus_20", "name": "Feedgas -20%", "perturbations": {"feedgas_pct": -20}},
        {"id": "lng_freight_double", "name": "LNG freight doubles", "perturbations": {"lng_freight_pct": 100}},
        {"id": "send_out_minus_15", "name": "Send-out -15%", "perturbations": {"send_out_pct": -15}},
    ],
    "metals": [
        {"id": "gold_minus_10", "name": "Gold -10%", "perturbations": {"gold_pct": -10}},
        {"id": "gold_plus_20", "name": "Gold +20%", "perturbations": {"gold_pct": 20}},
        {"id": "silver_minus_15", "name": "Silver -15%", "perturbations": {"silver_pct": -15}},
        {"id": "platinum_minus_25", "name": "Platinum -25%", "perturbations": {"platinum_pct": -25}},
        {"id": "lease_rate_plus_300bp", "name": "Gold lease rate +3pp", "perturbations": {"lease_rate_bp": 300}},
        {"id": "usdchf_plus_5", "name": "USDCHF +5% (CHF weakens)", "perturbations": {"usdchf_pct": 5}},
        {"id": "assay_variance_plus", "name": "Assay variance breach (-0.1%)", "perturbations": {"assay_fineness_delta": -0.001}},
        {"id": "refiner_delisted", "name": "Counterparty refiner delisted", "perturbations": {"refiner_delisted": True}},
        {"id": "russia_sanctions_tighten", "name": "Russia sanctions tighten", "perturbations": {"sanctions_severity_pp": 25}},
    ],
}


@router.get("/scenarios")
async def list_scenarios(
    user: ContractIQUser = Depends(get_contractiq_user),
    contract_type: str | None = Query(None),
) -> JSONResponse:
    if contract_type:
        return success({contract_type: SCENARIO_LIBRARY.get(contract_type, [])})
    return success(SCENARIO_LIBRARY)


@router.post("/contracts/{contract_id}/run")
async def run_whatif(
    contract_id: uuid.UUID,
    body: dict,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (
        await db.execute(
            select(ContractIQContract).where(
                ContractIQContract.id == contract_id,
                ContractIQContract.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    scenario_name = body.get("scenario_name") or "Custom what-if"
    perturbations = body.get("perturbations") or {}
    contract_type = body.get("contract_type") or contract.contract_type.value if hasattr(contract.contract_type, "value") else str(contract.contract_type)
    asset_class = body.get("asset_class") or contract.asset_class

    ctx_parts = [
        f"contract_id: {contract_id}",
        f"contract_type: {contract_type}",
        f"asset_class: {asset_class}",
        f"title: {contract.title}",
        f"counterparty_a: {contract.counterparty_a}",
        f"counterparty_b: {contract.counterparty_b}",
        f"contract_value_usd: {contract.contract_value}",
        f"effective_date: {contract.effective_date}",
        f"expiry_date: {contract.expiry_date}",
        f"raw_text_excerpt: {(contract.raw_text or '')[:8000]}",
        "",
        "=== PERTURBATIONS ===",
        json.dumps(perturbations, indent=2),
        "",
        "Task: estimate the change in NPV / P&L vs the base case for these perturbations.",
        "Decompose the delta into the drivers actually moved (price, FX, volume, etc).",
        "Return the JSON envelope.",
    ]
    msg = "\n".join(ctx_parts)

    try:
        parsed, _raw, meta = await _call_abenix(user, "contractiq-whatif-analyzer", msg, timeout=600.0)
    except Exception as e:
        logger.exception("what-if agent failed")
        return error(f"What-if agent failed: {e}", 503)

    parsed = parsed or {}
    base = float(parsed.get("base_value_usd") or contract.contract_value or 0)
    scen = float(parsed.get("scenario_value_usd") or base)
    delta = scen - base
    delta_pct = (delta / base * 100.0) if base else 0.0

    sig_input = {
        "contract_id": str(contract_id),
        "perturbations": perturbations,
        "method": "what_if_v1",
    }
    calc_sig = hashlib.sha256(json.dumps(sig_input, sort_keys=True, default=str).encode()).hexdigest()

    row = ContractIQWhatIfRun(
        user_id=user.id,
        contract_id=contract_id,
        contract_type=contract_type,
        asset_class=asset_class,
        scenario_name=scenario_name,
        perturbations=perturbations,
        base_value_usd=base,
        scenario_value_usd=scen,
        delta_usd=delta,
        delta_pct=delta_pct,
        decomposition=parsed.get("decomposition"),
        narrative=parsed.get("narrative"),
        calc_signature=calc_sig,
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success({
        "id": str(row.id),
        "contract_id": str(contract_id),
        "scenario_name": scenario_name,
        "perturbations": perturbations,
        "base_value_usd": base,
        "scenario_value_usd": scen,
        "delta_usd": delta,
        "delta_pct": delta_pct,
        "decomposition": parsed.get("decomposition"),
        "narrative": parsed.get("narrative"),
        "calc_signature": calc_sig,
    })


@router.get("/contracts/{contract_id}/runs")
async def list_runs(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQWhatIfRun)
            .where(
                ContractIQWhatIfRun.user_id == user.id,
                ContractIQWhatIfRun.contract_id == contract_id,
            )
            .order_by(desc(ContractIQWhatIfRun.created_at))
        )
    ).scalars().all()
    return success([
        {
            "id": str(r.id),
            "scenario_name": r.scenario_name,
            "perturbations": r.perturbations,
            "base_value_usd": r.base_value_usd,
            "scenario_value_usd": r.scenario_value_usd,
            "delta_usd": r.delta_usd,
            "delta_pct": r.delta_pct,
            "decomposition": r.decomposition,
            "narrative": r.narrative,
            "calc_signature": r.calc_signature,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ])
