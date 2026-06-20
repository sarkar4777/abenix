"""ContractIQ precious metals — extractor, compliance, dispute, loco, sourcing, refiner watch."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.core.responses import error, success
from app.routers.auth import get_contractiq_user
from app.routers.insights import _call_abenix

from app.models.contractiq_models import (
    ContractIQUser,
    ContractIQContract,
    ContractIQClause,
    ContractIQMetalsExtraction,
    ContractIQMetalsCompliance,
    ContractIQMetalsDisputeRisk,
    ContractIQMetalsLoco,
    ContractIQMetalsSourcing,
    ContractIQMetalsRefinerWatch,
)


async def _contract_context(db: AsyncSession, contract: ContractIQContract) -> str:
    """Bundle the contract's text + extracted clauses into a single prompt fragment."""
    clauses = (
        await db.execute(
            select(ContractIQClause).where(ContractIQClause.contract_id == contract.id)
        )
    ).scalars().all()
    parts = [
        f"contract_id: {contract.id}",
        f"title: {contract.title}",
        f"counterparty_a: {contract.counterparty_a}",
        f"counterparty_b: {contract.counterparty_b}",
        f"contract_value_usd: {contract.contract_value or 'n/a'}",
        f"effective_date: {contract.effective_date}",
        f"expiry_date: {contract.expiry_date}",
        "",
        "=== CONTRACT TEXT (verbatim) ===",
        (contract.raw_text or "")[:30000],
        "",
        f"=== EXTRACTED CLAUSES ({len(clauses)}) ===",
    ]
    for c in clauses[:40]:
        parts.append(f"[{c.clause_type}] {c.clause_text[:1500]}")
    return "\n".join(parts)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/contractiq/metals", tags=["contractiq-metals"])


def _verify_contract(db: AsyncSession, user_id: uuid.UUID, contract_id: uuid.UUID):
    return select(ContractIQContract).where(
        ContractIQContract.id == contract_id,
        ContractIQContract.user_id == user_id,
    )


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in {"true", "yes", "1"}
    return None


async def _call_with_retry(user, slug: str, message: str, timeout: float, attempts: int = 3):
    last_raw = ""
    last_meta = None
    last_err: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            parsed, raw, meta = await _call_abenix(user, slug, message, timeout=timeout)
            if parsed:
                return parsed, raw, meta
            last_raw = raw
            last_meta = meta
        except Exception as e:
            last_err = e
            logger.warning("agent %s attempt %d failed: %s", slug, attempt, e)
        message = (
            "Your previous attempt did not produce a parseable JSON object. "
            "Run the workflow again and finish with a single fenced ```json``` "
            "block matching the agreed schema. Original task: " + message
        )
    if last_err is not None:
        logger.warning("agent %s exhausted %d attempts, returning empty: %s", slug, attempts, last_err)
    return None, last_raw, last_meta


# ─── 1. Metals extractor ────────────────────────────────────────────────


def _serialize_extraction(r: ContractIQMetalsExtraction) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "material": r.material,
        "material_form": r.material_form,
        "fineness_min": r.fineness_min,
        "fineness_target": r.fineness_target,
        "bar_weight_oz": r.bar_weight_oz,
        "bar_weight_tolerance_pct": r.bar_weight_tolerance_pct,
        "good_delivery_standard": r.good_delivery_standard,
        "accepted_refiners": r.accepted_refiners,
        "loco": r.loco,
        "loco_other": r.loco_other,
        "delivery_window_days": r.delivery_window_days,
        "late_delivery_penalty": r.late_delivery_penalty,
        "pricing_reference": r.pricing_reference,
        "pricing_formula": r.pricing_formula,
        "settlement_currency": r.settlement_currency,
        "payment_terms_days": r.payment_terms_days,
        "assay_method": r.assay_method,
        "assay_tolerance_pct": r.assay_tolerance_pct,
        "umpire_clause_present": r.umpire_clause_present,
        "split_sample_protocol": r.split_sample_protocol,
        "provisional_payment_pct": r.provisional_payment_pct,
        "vaulting_type": r.vaulting_type,
        "insurance_required": r.insurance_required,
        "insurance_min_coverage_pct": r.insurance_min_coverage_pct,
        "treatment_charge_per_tonne_usd": r.treatment_charge_per_tonne_usd,
        "refining_charge_per_oz_usd": r.refining_charge_per_oz_usd,
        "payable_percent_au": r.payable_percent_au,
        "payable_percent_ag": r.payable_percent_ag,
        "payable_percent_pt": r.payable_percent_pt,
        "payable_percent_pd": r.payable_percent_pd,
        "impurity_penalties": r.impurity_penalties,
        "compliance_refs": r.compliance_refs,
        "russian_origin_excluded": r.russian_origin_excluded,
        "ofac_clause_present": r.ofac_clause_present,
        "confidence": r.confidence,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/contracts/{contract_id}/extract")
async def extract_metals_fields(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (await db.execute(_verify_contract(db, user.id, contract_id))).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    ctx = await _contract_context(db, contract)
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-extractor",
            f"Extract precious-metals fields from this contract.\n\n{ctx}",
            timeout=600.0,
        )
    except Exception as e:
        logger.exception("Metals extractor failed")
        return error(f"Metals extractor failed: {e}", 503)

    if not parsed:
        parsed = {}

    row = ContractIQMetalsExtraction(
        user_id=user.id,
        contract_id=contract_id,
        material=parsed.get("material"),
        material_form=parsed.get("material_form"),
        fineness_min=parsed.get("fineness_min"),
        fineness_target=parsed.get("fineness_target"),
        bar_weight_oz=parsed.get("bar_weight_oz"),
        bar_weight_tolerance_pct=parsed.get("bar_weight_tolerance_pct"),
        good_delivery_standard=parsed.get("good_delivery_standard"),
        accepted_refiners=parsed.get("accepted_refiners") or [],
        loco=parsed.get("loco"),
        loco_other=parsed.get("loco_other"),
        delivery_window_days=parsed.get("delivery_window_days"),
        late_delivery_penalty=parsed.get("late_delivery_penalty"),
        pricing_reference=parsed.get("pricing_reference"),
        pricing_formula=parsed.get("pricing_formula"),
        settlement_currency=parsed.get("settlement_currency"),
        payment_terms_days=parsed.get("payment_terms_days"),
        assay_method=parsed.get("assay_method"),
        assay_tolerance_pct=parsed.get("assay_tolerance_pct"),
        umpire_clause_present=_bool(parsed.get("umpire_clause_present")),
        split_sample_protocol=_bool(parsed.get("split_sample_protocol")),
        provisional_payment_pct=parsed.get("provisional_payment_pct"),
        vaulting_type=parsed.get("vaulting_type"),
        insurance_required=_bool(parsed.get("insurance_required")),
        insurance_min_coverage_pct=parsed.get("insurance_min_coverage_pct"),
        treatment_charge_per_tonne_usd=parsed.get("treatment_charge_per_tonne_usd"),
        refining_charge_per_oz_usd=parsed.get("refining_charge_per_oz_usd"),
        payable_percent_au=parsed.get("payable_percent_au"),
        payable_percent_ag=parsed.get("payable_percent_ag"),
        payable_percent_pt=parsed.get("payable_percent_pt"),
        payable_percent_pd=parsed.get("payable_percent_pd"),
        impurity_penalties=parsed.get("impurity_penalties") or [],
        compliance_refs={
            k: parsed.get(k) for k in [
                "references_lbma_rgg", "references_lppm", "references_oecd_ddg",
                "references_rjc", "references_dodd_frank_1502",
                "references_eu_2017_821", "references_iso_9001",
                "references_iso_14001", "references_swiss_pmca",
                "references_reach", "references_hmrc_vat_701_14",
            ] if k in parsed
        },
        russian_origin_excluded=_bool(parsed.get("russian_origin_excluded")),
        ofac_clause_present=_bool(parsed.get("ofac_clause_present")),
        confidence=parsed.get("confidence"),
        raw_output=parsed,
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_extraction(row))


@router.get("/contracts/{contract_id}/extraction")
async def get_metals_extraction(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQMetalsExtraction)
            .where(
                ContractIQMetalsExtraction.user_id == user.id,
                ContractIQMetalsExtraction.contract_id == contract_id,
            )
            .order_by(desc(ContractIQMetalsExtraction.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        return success(None)
    return success(_serialize_extraction(row))


@router.get("/extractions")
async def list_metals_extractions(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsExtraction)
            .where(ContractIQMetalsExtraction.user_id == user.id)
            .order_by(desc(ContractIQMetalsExtraction.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([_serialize_extraction(r) for r in rows])


# ─── 2. Compliance auditor ──────────────────────────────────────────────


def _serialize_compliance(r: ContractIQMetalsCompliance) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "overall_score": r.overall_score,
        "block_level_issues": r.block_level_issues,
        "clarification_requests": r.clarification_requests,
        "verdicts": r.verdicts,
        "superseded_references": r.superseded_references,
        "summary": r.summary,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/contracts/{contract_id}/compliance-audit")
async def run_compliance_audit(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (await db.execute(_verify_contract(db, user.id, contract_id))).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    ctx = await _contract_context(db, contract)
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-compliance-auditor",
            f"Audit this contract for precious-metals industry compliance.\n\n{ctx}",
            timeout=900.0,
        )
    except Exception as e:
        logger.exception("Metals compliance auditor failed")
        return error(f"Compliance auditor failed: {e}", 503)

    if not parsed:
        parsed = {}

    row = ContractIQMetalsCompliance(
        user_id=user.id,
        contract_id=contract_id,
        overall_score=parsed.get("overall_compliance_score"),
        block_level_issues=int(parsed.get("block_level_issues") or 0),
        clarification_requests=int(parsed.get("clarification_requests") or 0),
        verdicts=parsed.get("verdicts") or [],
        superseded_references=parsed.get("superseded_references") or [],
        summary=parsed.get("summary"),
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_compliance(row))


@router.get("/compliance")
async def list_compliance(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsCompliance)
            .where(ContractIQMetalsCompliance.user_id == user.id)
            .order_by(desc(ContractIQMetalsCompliance.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([_serialize_compliance(r) for r in rows])


@router.get("/contracts/{contract_id}/compliance")
async def get_compliance_for_contract(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    row = (
        await db.execute(
            select(ContractIQMetalsCompliance)
            .where(
                ContractIQMetalsCompliance.user_id == user.id,
                ContractIQMetalsCompliance.contract_id == contract_id,
            )
            .order_by(desc(ContractIQMetalsCompliance.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not row:
        return success(None)
    return success(_serialize_compliance(row))


# ─── 3. Dispute risk scorer ─────────────────────────────────────────────


def _serialize_dispute(r: ContractIQMetalsDisputeRisk) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "aggregate_score": r.aggregate_score,
        "tier": r.tier,
        "expected_loss_usd": r.expected_loss_usd,
        "expected_loss_pct_of_notional": r.expected_loss_pct_of_notional,
        "dimensions": r.dimensions,
        "top_recommendations": r.top_recommendations,
        "comparable_disputes": r.comparable_disputes,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/contracts/{contract_id}/dispute-risk")
async def score_dispute_risk(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (await db.execute(_verify_contract(db, user.id, contract_id))).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    ctx = await _contract_context(db, contract)
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-dispute-scorer",
            f"Score dispute risk on this contract.\n\n{ctx}",
            timeout=600.0,
        )
    except Exception as e:
        logger.exception("Metals dispute scorer failed")
        return error(f"Dispute scorer failed: {e}", 503)

    if not parsed:
        parsed = {}

    row = ContractIQMetalsDisputeRisk(
        user_id=user.id,
        contract_id=contract_id,
        aggregate_score=parsed.get("aggregate_score"),
        tier=parsed.get("tier"),
        expected_loss_usd=parsed.get("expected_loss_usd"),
        expected_loss_pct_of_notional=parsed.get("expected_loss_pct_of_notional"),
        dimensions=parsed.get("dimensions") or [],
        top_recommendations=parsed.get("top_recommendations") or [],
        comparable_disputes=parsed.get("comparable_disputes") or [],
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_dispute(row))


@router.get("/disputes")
async def list_disputes(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsDisputeRisk)
            .where(ContractIQMetalsDisputeRisk.user_id == user.id)
            .order_by(desc(ContractIQMetalsDisputeRisk.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([_serialize_dispute(r) for r in rows])


# ─── 4. Loco analyzer ───────────────────────────────────────────────────


def _serialize_loco(r: ContractIQMetalsLoco) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "loco": r.loco,
        "reference_price_usd_per_oz": r.reference_price_usd_per_oz,
        "loco_premium_pct": r.loco_premium_pct,
        "loco_premium_usd_per_oz": r.loco_premium_usd_per_oz,
        "comparison": r.comparison,
        "insurance": r.insurance,
        "customs_tariff": r.customs_tariff,
        "chain_of_integrity": r.chain_of_integrity,
        "repatriation": r.repatriation,
        "vault_handover": r.vault_handover,
        "alerts": r.alerts,
        "recommendations": r.recommendations,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/contracts/{contract_id}/loco-analyze")
async def analyze_loco(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (await db.execute(_verify_contract(db, user.id, contract_id))).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    ctx = await _contract_context(db, contract)
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-loco-analyzer",
            f"Analyse loco delivery terms on this contract.\n\n{ctx}",
            timeout=600.0,
        )
    except Exception as e:
        logger.exception("Metals loco analyzer failed")
        return error(f"Loco analyzer failed: {e}", 503)

    if not parsed:
        parsed = {}

    row = ContractIQMetalsLoco(
        user_id=user.id,
        contract_id=contract_id,
        loco=parsed.get("loco"),
        reference_price_usd_per_oz=parsed.get("reference_price_usd_per_oz"),
        loco_premium_pct=parsed.get("loco_premium_pct"),
        loco_premium_usd_per_oz=parsed.get("loco_premium_usd_per_oz"),
        comparison=parsed.get("comparison"),
        insurance=parsed.get("insurance"),
        customs_tariff=parsed.get("customs_tariff"),
        chain_of_integrity=parsed.get("chain_of_integrity"),
        repatriation=parsed.get("repatriation"),
        vault_handover=parsed.get("vault_handover"),
        alerts=parsed.get("alerts") or [],
        recommendations=parsed.get("recommendations") or [],
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_loco(row))


@router.get("/loco")
async def list_loco(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsLoco)
            .where(ContractIQMetalsLoco.user_id == user.id)
            .order_by(desc(ContractIQMetalsLoco.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([_serialize_loco(r) for r in rows])


# ─── 5. Sourcing tracker ────────────────────────────────────────────────


def _serialize_sourcing(r: ContractIQMetalsSourcing) -> dict:
    return {
        "id": str(r.id),
        "contract_id": str(r.contract_id),
        "origin_country": r.origin_country,
        "origin_risk_class": r.origin_risk_class,
        "mine_disclosed": r.mine_disclosed,
        "mine_identity": r.mine_identity,
        "refiner_disclosed": r.refiner_disclosed,
        "refiner_lbma_status": r.refiner_lbma_status,
        "transport_route": r.transport_route,
        "oecd_5_step_evidence": r.oecd_5_step_evidence,
        "lbma_rgg_step_evidence": r.lbma_rgg_step_evidence,
        "rjc_chain_of_custody": r.rjc_chain_of_custody,
        "dore_integrity_protocol_applicable": r.dore_integrity_protocol_applicable,
        "high_risk_origin": r.high_risk_origin,
        "russian_origin_exclusion_present": r.russian_origin_exclusion_present,
        "artisanal_source_handling": r.artisanal_source_handling,
        "gaps_count": r.gaps_count,
        "gaps": r.gaps,
        "audit_readiness_score": r.audit_readiness_score,
        "cost_usd": r.cost_usd,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/contracts/{contract_id}/sourcing-audit")
async def run_sourcing_audit(
    contract_id: uuid.UUID,
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    contract = (await db.execute(_verify_contract(db, user.id, contract_id))).scalar_one_or_none()
    if not contract:
        return error("Contract not found", 404)

    ctx = await _contract_context(db, contract)
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-sourcing-tracker",
            f"Track responsible sourcing for this contract.\n\n{ctx}",
            timeout=600.0,
        )
    except Exception as e:
        logger.exception("Metals sourcing tracker failed")
        return error(f"Sourcing tracker failed: {e}", 503)

    if not parsed:
        parsed = {}

    row = ContractIQMetalsSourcing(
        user_id=user.id,
        contract_id=contract_id,
        origin_country=parsed.get("origin_country"),
        origin_risk_class=parsed.get("origin_risk_class"),
        mine_disclosed=_bool(parsed.get("mine_disclosed")),
        mine_identity=parsed.get("mine_identity"),
        refiner_disclosed=_bool(parsed.get("refiner_disclosed")),
        refiner_lbma_status=parsed.get("refiner_lbma_status"),
        transport_route=parsed.get("transport_route") or [],
        oecd_5_step_evidence=parsed.get("oecd_5_step_evidence") or [],
        lbma_rgg_step_evidence=parsed.get("lbma_rgg_step_evidence") or [],
        rjc_chain_of_custody=parsed.get("rjc_chain_of_custody"),
        dore_integrity_protocol_applicable=_bool(parsed.get("dore_integrity_protocol_applicable")),
        high_risk_origin=_bool(parsed.get("high_risk_origin")),
        russian_origin_exclusion_present=_bool(parsed.get("russian_origin_exclusion_present")),
        artisanal_source_handling=parsed.get("artisanal_source_handling"),
        gaps_count=int(parsed.get("gaps_count") or 0),
        gaps=parsed.get("gaps") or [],
        audit_readiness_score=parsed.get("audit_readiness_score"),
        cost_usd=(meta or {}).get("cost_usd"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return success(_serialize_sourcing(row))


@router.get("/sourcing")
async def list_sourcing(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsSourcing)
            .where(ContractIQMetalsSourcing.user_id == user.id)
            .order_by(desc(ContractIQMetalsSourcing.created_at))
            .limit(limit)
        )
    ).scalars().all()
    return success([_serialize_sourcing(r) for r in rows])


# ─── 6. Refiner watch ───────────────────────────────────────────────────


def _serialize_refiner(r: ContractIQMetalsRefinerWatch) -> dict:
    return {
        "id": str(r.id),
        "refiner": r.refiner,
        "lbma_gold": r.lbma_gold,
        "lbma_silver": r.lbma_silver,
        "lppm_platinum": r.lppm_platinum,
        "lppm_palladium": r.lppm_palladium,
        "ofac_sdn": r.ofac_sdn,
        "next_audit_date": r.next_audit_date,
        "last_audit_findings": r.last_audit_findings,
        "user_contracts": r.user_contracts,
        "last_alert": r.last_alert,
        "last_scanned_at": r.last_scanned_at.isoformat() if r.last_scanned_at else None,
    }


@router.post("/refiner-watch/scan")
async def run_refiner_watch(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    try:
        parsed, _raw, meta = await _call_with_retry(
            user,
            "contractiq-metals-refiner-watch",
            "Run the refiner counterparty watch across my metals portfolio.",
            timeout=900.0,
        )
    except Exception as e:
        logger.exception("Refiner watch failed")
        return error(f"Refiner watch failed: {e}", 503)

    if not parsed:
        parsed = {}

    updated_refiners: list[dict] = []
    for entry in parsed.get("watchlist") or []:
        name = (entry.get("refiner") or "").strip()
        if not name:
            continue
        existing = (
            await db.execute(
                select(ContractIQMetalsRefinerWatch).where(
                    ContractIQMetalsRefinerWatch.user_id == user.id,
                    ContractIQMetalsRefinerWatch.refiner == name,
                )
            )
        ).scalar_one_or_none()
        last_alert = next(
            (
                a for a in (parsed.get("alerts") or [])
                if (a.get("refiner") or "").strip() == name
            ),
            None,
        )
        if existing:
            existing.lbma_gold = entry.get("lbma_gold")
            existing.lbma_silver = entry.get("lbma_silver")
            existing.lppm_platinum = entry.get("lppm_platinum")
            existing.lppm_palladium = entry.get("lppm_palladium")
            existing.ofac_sdn = _bool(entry.get("ofac_sdn"))
            existing.next_audit_date = entry.get("next_audit_date")
            existing.last_audit_findings = entry.get("last_audit_findings")
            existing.user_contracts = int(entry.get("user_contracts") or 0)
            existing.last_alert = last_alert
            existing.last_scanned_at = datetime.now(timezone.utc)
            updated_refiners.append(_serialize_refiner(existing))
        else:
            row = ContractIQMetalsRefinerWatch(
                user_id=user.id,
                refiner=name,
                lbma_gold=entry.get("lbma_gold"),
                lbma_silver=entry.get("lbma_silver"),
                lppm_platinum=entry.get("lppm_platinum"),
                lppm_palladium=entry.get("lppm_palladium"),
                ofac_sdn=_bool(entry.get("ofac_sdn")),
                next_audit_date=entry.get("next_audit_date"),
                last_audit_findings=entry.get("last_audit_findings"),
                user_contracts=int(entry.get("user_contracts") or 0),
                last_alert=last_alert,
            )
            db.add(row)
            updated_refiners.append({"pending_refresh": True, "refiner": name})
    await db.commit()
    return success({
        "scanned_refiners": parsed.get("scanned_refiners") or len(updated_refiners),
        "status_changes_since_last_run": parsed.get("status_changes_since_last_run") or 0,
        "alerts": parsed.get("alerts") or [],
        "summary": parsed.get("summary"),
        "refiners": updated_refiners,
    })


@router.get("/refiner-watch")
async def list_refiner_watch(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rows = (
        await db.execute(
            select(ContractIQMetalsRefinerWatch)
            .where(ContractIQMetalsRefinerWatch.user_id == user.id)
            .order_by(ContractIQMetalsRefinerWatch.refiner)
        )
    ).scalars().all()
    return success([_serialize_refiner(r) for r in rows])


# ─── 7. Portfolio overview ──────────────────────────────────────────────


@router.get("/overview")
async def metals_overview(
    user: ContractIQUser = Depends(get_contractiq_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:

    extractions = (
        await db.execute(
            select(ContractIQMetalsExtraction).where(
                ContractIQMetalsExtraction.user_id == user.id
            )
        )
    ).scalars().all()

    comp_rows = (
        await db.execute(
            select(ContractIQMetalsCompliance).where(
                ContractIQMetalsCompliance.user_id == user.id
            )
        )
    ).scalars().all()

    dr_rows = (
        await db.execute(
            select(ContractIQMetalsDisputeRisk).where(
                ContractIQMetalsDisputeRisk.user_id == user.id
            )
        )
    ).scalars().all()

    sourcing_rows = (
        await db.execute(
            select(ContractIQMetalsSourcing).where(
                ContractIQMetalsSourcing.user_id == user.id
            )
        )
    ).scalars().all()

    refiners = (
        await db.execute(
            select(ContractIQMetalsRefinerWatch).where(
                ContractIQMetalsRefinerWatch.user_id == user.id
            )
        )
    ).scalars().all()

    material_mix: dict[str, int] = {}
    loco_mix: dict[str, int] = {}
    for r in extractions:
        if r.material:
            material_mix[r.material] = material_mix.get(r.material, 0) + 1
        if r.loco:
            loco_mix[r.loco] = loco_mix.get(r.loco, 0) + 1

    total_expected_loss = sum((r.expected_loss_usd or 0) for r in dr_rows)
    avg_compliance = (
        sum((r.overall_score or 0) for r in comp_rows) / len(comp_rows)
        if comp_rows else None
    )
    avg_audit_readiness = (
        sum((r.audit_readiness_score or 0) for r in sourcing_rows) / len(sourcing_rows)
        if sourcing_rows else None
    )
    refiners_at_risk = sum(
        1 for r in refiners
        if r.lbma_gold in {"suspended", "delisted"}
        or r.lppm_platinum in {"suspended", "delisted"}
        or r.ofac_sdn
    )

    return success({
        "contracts_with_extraction": len(extractions),
        "compliance_runs": len(comp_rows),
        "dispute_scans": len(dr_rows),
        "sourcing_audits": len(sourcing_rows),
        "tracked_refiners": len(refiners),
        "refiners_at_risk": refiners_at_risk,
        "total_expected_dispute_loss_usd": round(total_expected_loss, 2),
        "avg_compliance_score": (
            round(avg_compliance, 3) if avg_compliance is not None else None
        ),
        "avg_audit_readiness_score": (
            round(avg_audit_readiness, 3) if avg_audit_readiness is not None else None
        ),
        "material_mix": material_mix,
        "loco_mix": loco_mix,
    })
