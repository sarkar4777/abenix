from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db
from app.routers.auth import get_contractiq_user
from app.models.contractiq_models import (
    ContractIQCounterparty,
    ContractIQFinancialStatement,
    ContractIQFinancialRatio,
    ContractIQRegulatoryPermit,
    ContractIQComplianceAlert,
    ContractIQDataProvenance,
    ContractIQUser,
)
from app.core.quickwin_seed import seed_quickwin_data
import json
import logging
import os

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/contractiq", tags=["quickwin"])


def _tier_for(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 70:
        return "green"
    if score >= 50:
        return "amber"
    return "red"


def _serialize_cp(cp: ContractIQCounterparty) -> dict[str, Any]:
    return {
        "id": str(cp.id),
        "legal_name": cp.legal_name,
        "ticker": cp.ticker,
        "sector": cp.sector,
        "country": cp.country,
        "credit_rating": cp.credit_rating,
        "credit_rating_agency": cp.credit_rating_agency,
        "credit_score_1_100": cp.credit_score_1_100,
        "risk_tier": cp.risk_tier or _tier_for(cp.credit_score_1_100),
        "credit_limit_usd": cp.credit_limit_usd,
        "credit_utilisation_pct": cp.credit_utilisation_pct,
        "last_kyc_at": cp.last_kyc_at.isoformat() if cp.last_kyc_at else None,
    }


@router.get("/counterparties")
async def list_counterparties(
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    rows = (await db.execute(select(ContractIQCounterparty).order_by(ContractIQCounterparty.credit_score_1_100.desc()))).scalars().all()
    items = [_serialize_cp(cp) for cp in rows]
    bands = {"green": 0, "amber": 0, "red": 0, "unknown": 0}
    for it in items:
        bands[it["risk_tier"]] = bands.get(it["risk_tier"], 0) + 1
    return {
        "data": {
            "items": items,
            "total": len(items),
            "bands": bands,
            "avg_score": (sum(i["credit_score_1_100"] or 0 for i in items) / len(items)) if items else 0,
        }
    }


@router.get("/counterparties/{cp_id}")
async def get_counterparty(
    cp_id: str,
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(cp_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    cp = (await db.execute(select(ContractIQCounterparty).where(ContractIQCounterparty.id == uid))).scalar_one_or_none()
    if cp is None:
        raise HTTPException(404, "counterparty not found")
    return {"data": _serialize_cp(cp)}


@router.get("/counterparties/{cp_id}/financials")
async def get_financials(
    cp_id: str,
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(cp_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    cp = (await db.execute(select(ContractIQCounterparty).where(ContractIQCounterparty.id == uid))).scalar_one_or_none()
    if cp is None:
        raise HTTPException(404, "counterparty not found")
    stmts = (await db.execute(
        select(ContractIQFinancialStatement)
        .where(ContractIQFinancialStatement.counterparty_id == uid)
        .order_by(ContractIQFinancialStatement.fiscal_year.asc())
    )).scalars().all()
    ratios = (await db.execute(
        select(ContractIQFinancialRatio)
        .where(ContractIQFinancialRatio.counterparty_id == uid)
        .order_by(ContractIQFinancialRatio.fiscal_year.asc())
    )).scalars().all()

    years = sorted({s.fiscal_year for s in stmts})
    line_labels = set()
    for s in stmts:
        line_labels.update((s.line_items or {}).keys())

    def _row(label: str) -> dict[str, Any]:
        out: dict[str, Any] = {"label": label}
        for s in stmts:
            out[str(s.fiscal_year)] = (s.line_items or {}).get(label)
        return out

    ordered_labels = [
        "revenue", "ebitda", "net_income",
        "total_assets", "current_assets", "cash_and_equivalents",
        "total_liabilities", "current_liabilities", "long_term_debt", "total_equity",
        "interest_expense", "operating_cash_flow", "free_cash_flow",
    ]
    rows = [_row(l) for l in ordered_labels if l in line_labels]

    ratio_rows = [
        {
            "fiscal_year": r.fiscal_year,
            "current_ratio": r.current_ratio,
            "quick_ratio": r.quick_ratio,
            "debt_to_equity": r.debt_to_equity,
            "interest_coverage": r.interest_coverage,
            "net_margin_pct": r.net_margin_pct,
            "return_on_assets_pct": r.return_on_assets_pct,
            "return_on_equity_pct": r.return_on_equity_pct,
            "altman_z": r.altman_z,
        }
        for r in ratios
    ]

    return {
        "data": {
            "counterparty": _serialize_cp(cp),
            "years": [int(y) for y in years],
            "currency": "USD",
            "statement_rows": rows,
            "ratios": ratio_rows,
            "source": stmts[0].source if stmts else None,
        }
    }


@router.get("/counterparties/{cp_id}/permits")
async def get_permits(
    cp_id: str,
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(cp_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    rows = (await db.execute(
        select(ContractIQRegulatoryPermit)
        .where(ContractIQRegulatoryPermit.counterparty_id == uid)
        .order_by(ContractIQRegulatoryPermit.valid_to.asc().nulls_last())
    )).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for p in rows:
        days_to_expiry = None
        if p.valid_to:
            days_to_expiry = (p.valid_to - now).days
        status = p.status
        if status == "active" and days_to_expiry is not None and days_to_expiry < 0:
            status = "expired"
        out.append({
            "id": str(p.id),
            "license_type": p.license_type,
            "issuer": p.issuer,
            "identifier": p.identifier,
            "status": status,
            "valid_from": p.valid_from.isoformat() if p.valid_from else None,
            "valid_to": p.valid_to.isoformat() if p.valid_to else None,
            "days_to_expiry": days_to_expiry,
            "notes": p.notes,
        })
    return {"data": {"items": out}}


@router.get("/compliance-alerts")
async def list_compliance_alerts(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    q = select(ContractIQComplianceAlert, ContractIQCounterparty).join(
        ContractIQCounterparty,
        ContractIQCounterparty.id == ContractIQComplianceAlert.counterparty_id,
        isouter=True,
    )
    if status:
        q = q.where(ContractIQComplianceAlert.status == status)
    if severity:
        q = q.where(ContractIQComplianceAlert.severity == severity)
    q = q.order_by(ContractIQComplianceAlert.raised_at.desc()).limit(limit)
    rows = (await db.execute(q)).all()
    items = []
    for alert, cp in rows:
        items.append({
            "id": str(alert.id),
            "counterparty_id": str(alert.counterparty_id) if alert.counterparty_id else None,
            "counterparty_name": cp.legal_name if cp else None,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "title": alert.title,
            "description": alert.description,
            "status": alert.status,
            "raised_at": alert.raised_at.isoformat() if alert.raised_at else None,
            "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        })
    counts = {"open": 0, "acknowledged": 0, "resolved": 0}
    severities = {"info": 0, "warning": 0, "critical": 0}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
        severities[it["severity"]] = severities.get(it["severity"], 0) + 1
    return {"data": {"items": items, "status_counts": counts, "severity_counts": severities}}


@router.post("/compliance-alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(alert_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    a = (await db.execute(select(ContractIQComplianceAlert).where(ContractIQComplianceAlert.id == uid))).scalar_one_or_none()
    if a is None:
        raise HTTPException(404, "alert not found")
    a.status = "acknowledged"
    a.acknowledged_at = datetime.now(timezone.utc)
    a.acknowledged_by = user.id if hasattr(user, "id") else None
    await db.commit()
    return {"data": {"id": str(a.id), "status": a.status}}


@router.post("/compliance-alerts/sweep")
async def run_compliance_sweep(
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    raised = 0
    now = datetime.now(timezone.utc)

    permits = (await db.execute(select(ContractIQRegulatoryPermit, ContractIQCounterparty).join(
        ContractIQCounterparty, ContractIQCounterparty.id == ContractIQRegulatoryPermit.counterparty_id
    ))).all()
    for permit, cp in permits:
        if permit.valid_to is None:
            continue
        delta = (permit.valid_to - now).days
        if delta < 0:
            title = f"{permit.license_type} permit has EXPIRED ({permit.identifier})"
            severity = "critical"
        elif delta < 60:
            title = f"{permit.license_type} permit expires in {delta} days ({permit.identifier})"
            severity = "critical" if delta < 14 else "warning"
        else:
            continue
        exists = (await db.execute(select(ContractIQComplianceAlert).where(
            ContractIQComplianceAlert.counterparty_id == cp.id,
            ContractIQComplianceAlert.title == title,
        ))).first()
        if exists:
            continue
        db.add(ContractIQComplianceAlert(
            counterparty_id=cp.id,
            alert_type="LICENSE_EXPIRING",
            severity=severity,
            title=title,
            description=f"{cp.legal_name} — {permit.license_type} expires {permit.valid_to.date().isoformat()}.",
        ))
        raised += 1

    cps = (await db.execute(select(ContractIQCounterparty))).scalars().all()
    for cp in cps:
        if cp.last_kyc_at is None:
            continue
        age_days = (now - cp.last_kyc_at).days
        if age_days < 180:
            continue
        title = f"KYC report is {age_days} days old"
        exists = (await db.execute(select(ContractIQComplianceAlert).where(
            ContractIQComplianceAlert.counterparty_id == cp.id,
            ContractIQComplianceAlert.title == title,
        ))).first()
        if exists:
            continue
        db.add(ContractIQComplianceAlert(
            counterparty_id=cp.id,
            alert_type="KYC_OVERDUE",
            severity="warning",
            title=title,
            description=f"{cp.legal_name} — last KYC ran {age_days} days ago; policy requires refresh every 180 days.",
        ))
        raised += 1

    for cp in cps:
        if cp.credit_utilisation_pct is None:
            continue
        if cp.credit_utilisation_pct < 80:
            continue
        title = f"Credit utilisation at {cp.credit_utilisation_pct:.0f}%"
        exists = (await db.execute(select(ContractIQComplianceAlert).where(
            ContractIQComplianceAlert.counterparty_id == cp.id,
            ContractIQComplianceAlert.title == title,
        ))).first()
        if exists:
            continue
        db.add(ContractIQComplianceAlert(
            counterparty_id=cp.id,
            alert_type="CREDIT_LIMIT_BREACHED",
            severity="warning",
            title=title,
            description=f"{cp.legal_name} — utilisation {cp.credit_utilisation_pct:.0f}% above 80% threshold.",
        ))
        raised += 1

    await db.commit()
    return {"data": {"raised": raised, "swept_at": now.isoformat()}}


@router.post("/quickwin/reseed")
async def reseed_demo_data(
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    summary = await seed_quickwin_data(db)
    return {"data": summary}


@router.post("/counterparties/{cp_id}/refresh")
async def refresh_counterparty(
    cp_id: str,
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(cp_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    cp = (await db.execute(select(ContractIQCounterparty).where(ContractIQCounterparty.id == uid))).scalar_one_or_none()
    if cp is None:
        raise HTTPException(404, "counterparty not found")

    api_key = os.environ.get("CONTRACTIQ_ABENIX_API_KEY", "")
    api_base = os.environ.get("ABENIX_API_URL", "http://abenix-api:8000")
    if not api_key:
        raise HTTPException(503, "abenix integration not configured (CONTRACTIQ_ABENIX_API_KEY missing)")

    payload = {
        "counterparty_id": str(cp.id),
        "legal_name": cp.legal_name,
        "ticker": cp.ticker,
        "country": cp.country,
        "sector": cp.sector,
    }

    try:
        from abenix_sdk import Abenix
        async with Abenix(api_key=api_key, base_url=api_base, timeout=180.0) as forge:
            result = await forge.execute(
                "ciq-counterparty-refresher",
                json.dumps(payload),
                wait_timeout_seconds=180,
            )
    except Exception as e:
        logger.exception("Abenix orchestration failed for %s", cp.legal_name)
        raise HTTPException(502, f"refresher agent failed: {e}")

    execution_id_raw = getattr(result, "execution_id", None)
    try:
        execution_id = uuid.UUID(str(execution_id_raw)) if execution_id_raw else None
    except Exception:
        execution_id = None
    output_text = getattr(result, "output", None) or "{}"
    try:
        parsed: dict[str, Any] = json.loads(output_text) if isinstance(output_text, str) else dict(output_text)
    except Exception:
        first = output_text.find("{"); last = output_text.rfind("}")
        parsed = json.loads(output_text[first:last + 1]) if (first != -1 and last > first) else {}

    summary = await _persist_refresh(db, cp, parsed, execution_id)
    cp.last_kyc_at = datetime.now(timezone.utc)
    await db.commit()
    return {
        "data": {
            "counterparty_id": str(cp.id),
            "execution_id": str(execution_id) if execution_id else None,
            "summary": summary,
            "agent_summary": parsed.get("summary"),
        }
    }


async def _persist_refresh(
    db: AsyncSession,
    cp: ContractIQCounterparty,
    parsed: dict[str, Any],
    execution_id: uuid.UUID | None,
) -> dict[str, int]:
    counts = {"statements": 0, "permits": 0, "ratings": 0, "provenance": 0}

    financials = (parsed.get("financials") or {})
    if financials.get("status") == "ok":
        stmts = financials.get("statements") or {}
        prov = financials.get("provenance") or {}
        source_url_tpl = financials.get("source_url_template") or ""
        for year_str, line_items in stmts.items():
            try:
                year = int(year_str)
            except Exception:
                continue
            existing = (await db.execute(
                select(ContractIQFinancialStatement).where(
                    ContractIQFinancialStatement.counterparty_id == cp.id,
                    ContractIQFinancialStatement.fiscal_year == year,
                    ContractIQFinancialStatement.statement_type == "balance_sheet",
                )
            )).scalar_one_or_none()
            if existing is None:
                row = ContractIQFinancialStatement(
                    counterparty_id=cp.id,
                    fiscal_year=year,
                    statement_type="balance_sheet",
                    currency=financials.get("currency") or "USD",
                    line_items=line_items,
                    source=f"{financials.get('source')} · refreshed {datetime.now(timezone.utc).date().isoformat()}",
                    extracted_by=financials.get("source") or "ciq-financial-extractor",
                )
                db.add(row)
                await db.flush()
                target_row_id = row.id
            else:
                existing.line_items = line_items
                existing.source = f"{financials.get('source')} · refreshed {datetime.now(timezone.utc).date().isoformat()}"
                existing.extracted_by = financials.get("source") or existing.extracted_by
                target_row_id = existing.id
            counts["statements"] += 1
            year_prov = prov.get(str(year)) or {}
            for field, source_ident in year_prov.items():
                db.add(ContractIQDataProvenance(
                    counterparty_id=cp.id,
                    target_table="contractiq_financial_statements",
                    target_row_id=target_row_id,
                    target_field=field,
                    source_tool=financials.get("source") or "edgar_filings",
                    source_url=source_url_tpl,
                    source_identifier=str(source_ident),
                    fetched_by_agent="ciq-financial-extractor",
                    execution_id=execution_id,
                    confidence=1.0,
                ))
                counts["provenance"] += 1

    permits = (parsed.get("permits") or {})
    for perm in (permits.get("permits") or []):
        existing = (await db.execute(
            select(ContractIQRegulatoryPermit).where(
                ContractIQRegulatoryPermit.counterparty_id == cp.id,
                ContractIQRegulatoryPermit.license_type == perm.get("license_type"),
                ContractIQRegulatoryPermit.identifier == perm.get("identifier"),
            )
        )).scalar_one_or_none()
        vt = _parse_iso(perm.get("valid_to"))
        vf = _parse_iso(perm.get("valid_from"))
        if existing is None:
            row = ContractIQRegulatoryPermit(
                counterparty_id=cp.id,
                license_type=perm.get("license_type") or "UNKNOWN",
                issuer=perm.get("issuer") or "UNKNOWN",
                identifier=perm.get("identifier"),
                status=perm.get("status") or "active",
                valid_from=vf,
                valid_to=vt,
                notes=perm.get("source_filing"),
            )
            db.add(row)
            await db.flush()
            target_row_id = row.id
        else:
            existing.status = perm.get("status") or existing.status
            existing.valid_from = vf or existing.valid_from
            existing.valid_to = vt or existing.valid_to
            existing.notes = perm.get("source_filing") or existing.notes
            target_row_id = existing.id
        counts["permits"] += 1
        db.add(ContractIQDataProvenance(
            counterparty_id=cp.id,
            target_table="contractiq_regulatory_permits",
            target_row_id=target_row_id,
            source_tool=perm.get("source_tool") or "ferc_elibrary",
            source_url=perm.get("source_url"),
            source_identifier=perm.get("source_filing"),
            fetched_by_agent="ciq-permit-checker",
            execution_id=execution_id,
            confidence=1.0,
        ))
        counts["provenance"] += 1

    ratings = (parsed.get("ratings") or {})
    rating_list = ratings.get("ratings") or []
    if rating_list:
        top = rating_list[0]
        cp.credit_rating = top.get("rating") or cp.credit_rating
        cp.credit_rating_agency = top.get("agency") or cp.credit_rating_agency
        counts["ratings"] += 1
        db.add(ContractIQDataProvenance(
            counterparty_id=cp.id,
            target_table="contractiq_counterparties",
            target_row_id=cp.id,
            target_field="credit_rating",
            source_tool=top.get("agency") or "ratings",
            source_url=top.get("source_url"),
            source_identifier=f"{top.get('agency')} {top.get('rating')} · outlook {top.get('outlook')} · as of {top.get('as_of')}",
            fetched_by_agent="ciq-rating-fetcher",
            execution_id=execution_id,
            confidence=1.0,
        ))
        counts["provenance"] += 1

    return counts


def _parse_iso(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


@router.get("/counterparties/{cp_id}/provenance")
async def get_provenance(
    cp_id: str,
    db: AsyncSession = Depends(get_db),
    _user: ContractIQUser = Depends(get_contractiq_user),
):
    try:
        uid = uuid.UUID(cp_id)
    except Exception:
        raise HTTPException(400, "invalid id")
    rows = (await db.execute(
        select(ContractIQDataProvenance)
        .where(ContractIQDataProvenance.counterparty_id == uid)
        .order_by(ContractIQDataProvenance.fetched_at.desc())
        .limit(500)
    )).scalars().all()
    return {"data": {"items": [
        {
            "id": str(r.id),
            "target_table": r.target_table,
            "target_row_id": str(r.target_row_id),
            "target_field": r.target_field,
            "source_tool": r.source_tool,
            "source_url": r.source_url,
            "source_identifier": r.source_identifier,
            "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
            "fetched_by_agent": r.fetched_by_agent,
            "execution_id": str(r.execution_id) if r.execution_id else None,
        }
        for r in rows
    ]}}
