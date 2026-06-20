"""Idempotent seed for counterparties + 5y financials + permits + alerts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contractiq_models import (
    ContractIQCounterparty,
    ContractIQFinancialStatement,
    ContractIQFinancialRatio,
    ContractIQRegulatoryPermit,
    ContractIQComplianceAlert,
)


logger = logging.getLogger(__name__)


# Demo-tenant placeholder used when the Abenix tenants table has no `demo` row.
# Matches the fallback in the c0d1e2f3a4b5 migration so seed + backfill agree.
_PLACEHOLDER_TENANT = "00000000-0000-0000-0000-000000000000"


async def _resolve_demo_tenant_id(db: AsyncSession) -> str:
    """Look up the Abenix `demo` tenant id; fall back to a deterministic
    placeholder so the seed never breaks the NOT NULL constraint on a cluster
    that hasn't seeded an Abenix demo tenant yet."""
    try:
        row = (await db.execute(
            text("SELECT id::text FROM tenants WHERE name = 'demo' LIMIT 1")
        )).first()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.warning("demo tenant lookup failed (%s); using placeholder", e)
    return _PLACEHOLDER_TENANT


COUNTERPARTIES: list[dict] = [
    {"legal_name": "Shell plc",            "ticker": "SHEL", "sector": "Integrated Oil & Gas", "country": "UK",       "incorporation_year": 1907, "credit_rating": "AA-",  "agency": "S&P", "score": 81, "limit_usd": 250_000_000},
    {"legal_name": "BP plc",               "ticker": "BP",   "sector": "Integrated Oil & Gas", "country": "UK",       "incorporation_year": 1909, "credit_rating": "A",    "agency": "S&P", "score": 74, "limit_usd": 220_000_000},
    {"legal_name": "Equinor ASA",          "ticker": "EQNR", "sector": "Integrated Oil & Gas", "country": "Norway",   "incorporation_year": 1972, "credit_rating": "AA-",  "agency": "S&P", "score": 83, "limit_usd": 280_000_000},
    {"legal_name": "TotalEnergies SE",     "ticker": "TTE",  "sector": "Integrated Oil & Gas", "country": "France",   "incorporation_year": 1924, "credit_rating": "A+",   "agency": "S&P", "score": 79, "limit_usd": 260_000_000},
    {"legal_name": "Exxon Mobil Corp",     "ticker": "XOM",  "sector": "Integrated Oil & Gas", "country": "USA",      "incorporation_year": 1999, "credit_rating": "AA-",  "agency": "S&P", "score": 84, "limit_usd": 300_000_000},
    {"legal_name": "Vitol Group",          "ticker": None,   "sector": "Commodity Trading",   "country": "Switzerland","incorporation_year": 1966,"credit_rating": "BBB+", "agency": "Fitch","score": 62,"limit_usd": 150_000_000},
    {"legal_name": "Trafigura Group",      "ticker": None,   "sector": "Commodity Trading",   "country": "Singapore","incorporation_year": 1993, "credit_rating": "BB+",  "agency": "Fitch","score": 48,"limit_usd": 120_000_000},
    {"legal_name": "RWE AG",               "ticker": "RWE",  "sector": "Utilities",            "country": "Germany",  "incorporation_year": 1898, "credit_rating": "BBB+", "agency": "S&P", "score": 64, "limit_usd": 170_000_000},
    {"legal_name": "Iberdrola SA",         "ticker": "IBE",  "sector": "Utilities",            "country": "Spain",    "incorporation_year": 1992, "credit_rating": "BBB+", "agency": "S&P", "score": 67, "limit_usd": 180_000_000},
    {"legal_name": "Engie SA",             "ticker": "ENGI", "sector": "Utilities",            "country": "France",   "incorporation_year": 2008, "credit_rating": "BBB+", "agency": "S&P", "score": 65, "limit_usd": 175_000_000},
    {"legal_name": "Glencore plc",         "ticker": "GLEN", "sector": "Commodity Trading",   "country": "Switzerland","incorporation_year": 1974,"credit_rating": "BBB",  "agency": "S&P", "score": 58, "limit_usd": 140_000_000},
    {"legal_name": "Mercuria Energy Group","ticker": None,   "sector": "Commodity Trading",   "country": "Switzerland","incorporation_year": 2004,"credit_rating": "BB+",  "agency": "Fitch","score": 42,"limit_usd": 110_000_000},
]


_YEAR_SCALE = {2020: 0.62, 2021: 0.80, 2022: 1.34, 2023: 1.09, 2024: 1.00}

# Year-on-year balance-sheet trajectories. Assets ramp up smoothly; long-term debt
# is paid down through the cycle (typical post-COVID majors profile). Working-capital
# items (current_assets / current_liabilities / cash) flex with revenue, not assets.
_ASSET_GROWTH = {2020: 1.000, 2021: 1.027, 2022: 1.064, 2023: 1.100, 2024: 1.135}
_DEBT_TRAJECTORY = {2020: 1.000, 2021: 0.910, 2022: 0.790, 2023: 0.680, 2024: 0.580}


def _build_statements(cp_size_usd_bn: float, sector: str) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    rev_base = cp_size_usd_bn * 1_000.0
    ebitda_margin = {"Integrated Oil & Gas": 0.22, "Utilities": 0.18, "Commodity Trading": 0.04}.get(sector, 0.15)
    net_margin = {"Integrated Oil & Gas": 0.08, "Utilities": 0.06, "Commodity Trading": 0.015}.get(sector, 0.05)
    # Starting (2020) long-term-debt / assets ratio. Oil majors entered 2020 over-levered;
    # by 2024 they had paid down ~42% (matches Exxon 67B->39B).
    debt_ratio_2020 = {"Integrated Oil & Gas": 0.198, "Utilities": 0.42, "Commodity Trading": 0.34}.get(sector, 0.30)
    # Assets-to-revenue at the FY2024 baseline (scale=1.0). Tuned so Exxon
    # (size_bn=339) lands at ~420B in 2024.
    asset_to_rev_2024 = {"Integrated Oil & Gas": 1.24, "Utilities": 2.30, "Commodity Trading": 0.55}.get(sector, 1.10)
    assets_2024 = rev_base * asset_to_rev_2024
    assets_2020 = assets_2024 / _ASSET_GROWTH[2024]  # rebase so 2024 hits target

    for year, scale in _YEAR_SCALE.items():
        revenue = rev_base * scale
        ebitda = revenue * ebitda_margin * (0.9 + 0.2 * (year - 2020) / 4)
        net_income = revenue * net_margin * (0.7 + 0.3 * scale)

        total_assets = assets_2020 * _ASSET_GROWTH[year]
        # Working capital flexes with revenue, not assets (this is what broke before).
        current_assets = revenue * 0.27
        cash = revenue * 0.055
        current_liabilities = revenue * 0.21
        # Long-term debt: paid down on the trajectory; anchored to 2020 assets.
        long_term_debt = assets_2020 * debt_ratio_2020 * _DEBT_TRAJECTORY[year]
        total_liabilities = current_liabilities + long_term_debt
        total_equity = total_assets - total_liabilities
        interest_expense = long_term_debt * 0.045
        operating_cf = ebitda * 0.78
        free_cf = operating_cf - rev_base * 0.06
        out[year] = {
            "revenue": revenue,
            "ebitda": ebitda,
            "net_income": net_income,
            "total_assets": total_assets,
            "current_assets": current_assets,
            "cash_and_equivalents": cash,
            "total_liabilities": total_liabilities,
            "current_liabilities": current_liabilities,
            "long_term_debt": long_term_debt,
            "total_equity": total_equity,
            "interest_expense": interest_expense,
            "operating_cash_flow": operating_cf,
            "free_cash_flow": free_cf,
        }
    return out


_CP_SIZE_BN: dict[str, float] = {
    "Shell plc": 323,            "BP plc": 213,                 "Equinor ASA": 109,
    "TotalEnergies SE": 218,     "Exxon Mobil Corp": 339,       "Vitol Group": 405,
    "Trafigura Group": 244,      "RWE AG": 32,                  "Iberdrola SA": 50,
    "Engie SA": 86,              "Glencore plc": 217,           "Mercuria Energy Group": 174,
}


_PERMITS: list[tuple[str, str, str, str, int]] = [
    ("Shell plc",             "FERC_MBR",        "FERC",    "ER21-1872",          410),
    ("Shell plc",             "EPA_TITLE_V",     "EPA",     "TV-CA-2019-0042",    280),
    ("BP plc",                "FERC_MBR",        "FERC",    "ER20-2541",          155),
    ("BP plc",                "RTO_PJM",         "PJM",     "MEMBER-2018-091",   1095),
    ("Equinor ASA",           "FERC_MBR",        "FERC",    "ER22-1109",          780),
    ("Equinor ASA",           "BOEM_OCS_LEASE",  "BOEM",    "OCS-G-37304",       1825),
    ("TotalEnergies SE",      "FERC_MBR",        "FERC",    "ER19-2010",           45),
    ("Exxon Mobil Corp",      "FERC_MBR",        "FERC",    "ER18-2207",          900),
    ("Exxon Mobil Corp",      "PHMSA_PIPELINE",  "PHMSA",   "27814-22-001",      1500),
    ("Vitol Group",           "FERC_MBR",        "FERC",    "ER23-552",           650),
    ("Vitol Group",           "CFTC_NFA",        "CFTC",    "NFA-0494817",        300),
    ("Trafigura Group",       "FERC_MBR",        "FERC",    "ER22-1865",         -30),
    ("RWE AG",                "RTO_MISO",        "MISO",    "MEMBER-2014-018",   1460),
    ("RWE AG",                "EPA_TITLE_V",     "EPA",     "TV-TX-2021-0117",    250),
    ("Iberdrola SA",          "FERC_MBR",        "FERC",    "ER21-1402",          540),
    ("Engie SA",              "FERC_MBR",        "FERC",    "ER20-987",            10),
    ("Glencore plc",          "FERC_MBR",        "FERC",    "ER22-2204",          730),
    ("Mercuria Energy Group", "CFTC_NFA",        "CFTC",    "NFA-0476290",        180),
    ("Mercuria Energy Group", "FERC_MBR",        "FERC",    "ER19-744",          -120),
]


_PERMIT_NOTES: dict[str, str] = {
    "FERC_MBR":        "Market-Based Rate Authority — required to sell wholesale power into US markets.",
    "EPA_TITLE_V":     "Title V air-emissions permit for the operating facility.",
    "RTO_PJM":         "PJM Interconnection membership — required to bid into PJM day-ahead + real-time.",
    "RTO_MISO":        "MISO membership — required to participate in MISO energy + capacity markets.",
    "BOEM_OCS_LEASE":  "Bureau of Ocean Energy Management offshore lease.",
    "PHMSA_PIPELINE":  "Pipeline operator certification — PHMSA part-192 compliance.",
    "CFTC_NFA":        "CFTC + NFA registration — required to broker / introduce US commodity derivatives.",
}


_PRE_SEEDED_ALERTS: list[tuple[str, str, str, str, str]] = [
    ("Engie SA",
     "LICENSE_EXPIRING", "critical",
     "FERC Market-Based Rate authority expires in 10 days",
     "Engie SA — FERC MBR (ER20-987) expires 10 days from now. Renewal filing is the only way to keep selling wholesale power into US markets. Recommend opening triennial-update workflow immediately."),
    ("TotalEnergies SE",
     "LICENSE_EXPIRING", "warning",
     "FERC Market-Based Rate authority expires in 45 days",
     "TotalEnergies SE — FERC MBR (ER19-2010) expires in 45 days. 30-day notice window opens shortly; flag for renewal."),
    ("Trafigura Group",
     "LICENSE_EXPIRING", "critical",
     "FERC Market-Based Rate authority has EXPIRED",
     "Trafigura Group — FERC MBR (ER22-1865) expired 30 days ago. Active US wholesale trades against this entity are exposed; suspend new business until renewal lands."),
    ("Mercuria Energy Group",
     "LICENSE_EXPIRING", "critical",
     "FERC Market-Based Rate authority has EXPIRED",
     "Mercuria Energy Group — FERC MBR (ER19-744) expired 120 days ago. Critical compliance gap; legal review required before any US power trade."),
    ("Vitol Group",
     "KYC_OVERDUE", "warning",
     "KYC report is over 6 months old",
     "Vitol Group — last KYC run was > 180 days ago. Policy requires refresh every 180 days for BBB-rated commodity-trading counterparties."),
    ("Trafigura Group",
     "CREDIT_LIMIT_BREACHED", "warning",
     "Counterparty credit utilisation at 87%",
     "Trafigura Group — current utilisation $104.4M of $120M limit (87%). Above 80% threshold triggers desk-head review per credit policy."),
    ("Glencore plc",
     "SANCTION_LIST_ADDED", "info",
     "New OFAC SDN entries — re-screen recommended",
     "OFAC published 14 new SDN entries today (Russian energy sector). Glencore plc has > 5% revenue exposure to flagged region per last KYC. Recommend automated re-screen."),
]


async def _get_or_create_counterparty(
    db: AsyncSession, payload: dict, tenant_id: str
) -> ContractIQCounterparty:
    existing = await db.execute(select(ContractIQCounterparty).where(
        ContractIQCounterparty.legal_name == payload["legal_name"]
    ))
    cp = existing.scalar_one_or_none()
    if cp:
        # Repair rows from before tenant_id existed — leave already-tenanted
        # rows alone so we never silently re-home another tenant's data.
        if not cp.tenant_id:
            cp.tenant_id = tenant_id
        cp.credit_score_1_100 = payload.get("score")
        cp.credit_rating = payload.get("credit_rating") or cp.credit_rating
        cp.credit_rating_agency = payload.get("agency") or cp.credit_rating_agency
        cp.risk_tier = (
            "green" if (payload.get("score") or 0) >= 70
            else "amber" if (payload.get("score") or 0) >= 50
            else "red"
        )
        return cp
    cp = ContractIQCounterparty(
        tenant_id=tenant_id,
        legal_name=payload["legal_name"],
        ticker=payload.get("ticker"),
        sector=payload.get("sector"),
        country=payload.get("country"),
        incorporation_year=payload.get("incorporation_year"),
        credit_rating=payload.get("credit_rating"),
        credit_rating_agency=payload.get("agency"),
        credit_score_1_100=payload.get("score"),
        risk_tier=("green" if payload["score"] >= 70 else "amber" if payload["score"] >= 50 else "red"),
        credit_limit_usd=payload.get("limit_usd"),
        credit_utilisation_pct=37 + (payload["score"] % 50),
        last_kyc_at=datetime.now(timezone.utc) - timedelta(days=30 + (payload["score"] % 200)),
    )
    db.add(cp)
    await db.flush()
    return cp


async def _compute_and_persist_ratios(db: AsyncSession, cp_id, year: int, stmt: dict) -> None:
    revenue = stmt["revenue"]
    cur_a = stmt["current_assets"]
    cur_l = stmt["current_liabilities"]
    total_liab = stmt["total_liabilities"]
    equity = stmt["total_equity"]
    int_exp = stmt["interest_expense"]
    ebitda = stmt["ebitda"]
    net_income = stmt["net_income"]
    total_assets = stmt["total_assets"]

    def _safe(num, den):
        try:
            return float(num) / float(den) if den else None
        except Exception:
            return None

    current_ratio = _safe(cur_a, cur_l)
    quick_ratio = _safe(cur_a - (cur_a * 0.4), cur_l)
    debt_to_equity = _safe(total_liab, equity)
    interest_coverage = _safe(ebitda, int_exp)
    net_margin = _safe(net_income, revenue)
    roa = _safe(net_income, total_assets)
    roe = _safe(net_income, equity)
    working_cap = cur_a - cur_l
    a = _safe(working_cap, total_assets) or 0
    b = _safe(net_income * 0.6, total_assets) or 0
    c = _safe(ebitda, total_assets) or 0
    d = _safe(equity, total_liab) or 0
    e = _safe(revenue, total_assets) or 0
    z = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e

    db.add(ContractIQFinancialRatio(
        counterparty_id=cp_id,
        fiscal_year=year,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        debt_to_equity=debt_to_equity,
        interest_coverage=interest_coverage,
        net_margin_pct=(net_margin or 0) * 100,
        return_on_assets_pct=(roa or 0) * 100,
        return_on_equity_pct=(roe or 0) * 100,
        revenue_growth_yoy_pct=None,
        altman_z=z,
    ))


async def seed_quickwin_data(db: AsyncSession, tenant_id: str | None = None) -> dict:
    summary = {"counterparties": 0, "statements": 0, "ratios": 0, "permits": 0, "alerts": 0}

    cp_lookup: dict[str, ContractIQCounterparty] = {}
    tid = tenant_id or await _resolve_demo_tenant_id(db)

    for cp_payload in COUNTERPARTIES:
        cp = await _get_or_create_counterparty(db, cp_payload, tid)
        cp_lookup[cp.legal_name] = cp
        if cp not in db.new:
            summary["counterparties"] += 1

    for cp_payload in COUNTERPARTIES:
        cp = cp_lookup[cp_payload["legal_name"]] = (
            cp_lookup.get(cp_payload["legal_name"])
            or (await db.execute(select(ContractIQCounterparty).where(
                ContractIQCounterparty.legal_name == cp_payload["legal_name"]
            ))).scalar_one()
        )

        existing_stmts = (await db.execute(select(ContractIQFinancialStatement).where(
            ContractIQFinancialStatement.counterparty_id == cp.id
        ))).scalars().all()
        # Self-healing upgrade path: if statements exist but balance-sheet items are
        # flat across years (the old _build_statements bug), wipe + rebuild. The
        # detector compares total_assets across the seeded fiscal years.
        if existing_stmts:
            assets_seen = {
                s.fiscal_year: round(float((s.line_items or {}).get("total_assets") or 0), 2)
                for s in existing_stmts
                if (s.line_items or {}).get("total_assets") is not None
            }
            is_flat = len(set(assets_seen.values())) <= 1 and len(assets_seen) >= 2
            if not is_flat:
                continue
            for s in existing_stmts:
                await db.delete(s)
            existing_ratios = (await db.execute(select(ContractIQFinancialRatio).where(
                ContractIQFinancialRatio.counterparty_id == cp.id
            ))).scalars().all()
            for r in existing_ratios:
                await db.delete(r)
            await db.flush()
            logger.info("quickwin_seed: rebuilt flat financials for %s", cp.legal_name)

        size_bn = _CP_SIZE_BN.get(cp.legal_name, 50.0)
        per_year = _build_statements(size_bn, cp.sector or "")

        for year, stmt in per_year.items():
            period_end = datetime(year, 12, 31, tzinfo=timezone.utc)
            db.add(ContractIQFinancialStatement(
                counterparty_id=cp.id, fiscal_year=year, period_end=period_end,
                currency="USD", statement_type="combined",
                line_items={k: round(v, 2) for k, v in stmt.items()},
                source=f"FY{year} Annual Report (synthesised for demo)",
            ))
            summary["statements"] += 1
            await _compute_and_persist_ratios(db, cp.id, year, stmt)
            summary["ratios"] += 1

    for cp_name, lic_type, issuer, ident, days_to_exp in _PERMITS:
        cp = cp_lookup.get(cp_name)
        if cp is None:
            continue
        existing = await db.execute(select(ContractIQRegulatoryPermit).where(
            ContractIQRegulatoryPermit.counterparty_id == cp.id,
            ContractIQRegulatoryPermit.identifier == ident,
        ))
        if existing.first():
            continue
        valid_to = datetime.now(timezone.utc) + timedelta(days=days_to_exp)
        valid_from = valid_to - timedelta(days=3 * 365)
        status = "expired" if days_to_exp < 0 else "active"
        db.add(ContractIQRegulatoryPermit(
            counterparty_id=cp.id, license_type=lic_type, issuer=issuer,
            identifier=ident, status=status, valid_from=valid_from,
            valid_to=valid_to, notes=_PERMIT_NOTES.get(lic_type),
        ))
        summary["permits"] += 1

    for cp_name, alert_type, severity, title, description in _PRE_SEEDED_ALERTS:
        cp = cp_lookup.get(cp_name)
        if cp is None:
            continue
        existing = await db.execute(select(ContractIQComplianceAlert).where(
            ContractIQComplianceAlert.counterparty_id == cp.id,
            ContractIQComplianceAlert.title == title,
        ))
        if existing.first():
            continue
        db.add(ContractIQComplianceAlert(
            counterparty_id=cp.id, alert_type=alert_type, severity=severity,
            title=title, description=description,
        ))
        summary["alerts"] += 1

    await db.commit()
    logger.info("Quick-Win seed result: %s", summary)
    return summary
