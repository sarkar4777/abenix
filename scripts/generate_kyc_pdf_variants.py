#!/usr/bin/env python3
"""Generate 5 varied MET-template KYC PDFs covering different risk profiles
and all four outcome states. Output to contractiq/e2e/fixtures/variants/ so
they don't clash with the existing safety-test fixtures.

Scenarios:
  1. clean-de-power.pdf            — German utility, low risk, positive
  2. mid-br-trading.pdf            — Brazilian trading house, medium risk, positive with conditions
  3. high-risk-ru-gas.pdf          — Russian counterparty, sanctions hit, negative
  4. gambling-mt.pdf               — Maltese gambling operator, high-risk industry, pending
  5. clean-ch-finance.pdf          — Swiss financial services, low risk, positive

Usage:
  python scripts/generate_kyc_pdf_variants.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        PageBreak,
    )
except ImportError:
    sys.stderr.write("reportlab is required. Install with: pip install reportlab\n")
    sys.exit(2)


@dataclass
class Scenario:
    """One KYC PDF scenario — every visible value is parameterised."""

    filename: str
    # Administrative block
    profit_centre: str
    activity_trigger: str
    business_relationship: str
    start_date: str
    # Counterparty
    counterparty: str
    address: str
    primary_business: str
    short_description: str
    # Sanctions
    country: str
    sanctions_applicable: str
    sanctions_conclusion: str
    # Tri-indicator (Country / Notional / Industry)
    cpi_rank: str
    cpi_score: str
    notional_band: str
    notional_score: str
    industry_label: str
    industry_score: str
    aggregated_score: str
    check_type: str
    # Basic compliance
    legal_existence_outcome: str
    legal_existence_comment: str
    # Intermediate checks — list of (status, risk_grade, comment)
    inter_rows: list[tuple[str, str, str]]
    # Page 2
    questionnaire_collected: str
    shareholder_structure: str
    ubos_list: str
    risk_summary: str
    general_comments: str
    legal_consulted: str
    legal_opinion: str
    outcome: str  # positive / positive_with_conditions / negative / pending
    supporting_docs: str
    kyc_expert: str
    expert_signature: str
    signature_date: str
    footer_note: str


SCENARIOS: list[Scenario] = [
    Scenario(
        filename="clean-de-power.pdf",
        profit_centre="MET Deutschland AG",
        activity_trigger="Pre-Check",
        business_relationship="Core",
        start_date="14.01.2026",
        counterparty="STADTWERKE MUNCHEN GmbH",
        address="Emmy-Noether-Strasse 2, 80287 Munich, Germany",
        primary_business="Power Distribution / Public Utility",
        short_description="Counterparty/Power Supply",
        country="Germany",
        sanctions_applicable="no",
        sanctions_conclusion="Standard Check possible",
        cpi_rank="9",
        cpi_score="2",
        notional_band="EUR 75M band",
        notional_score="25",
        industry_label="Power Distribution (Tier 1 OECD)",
        industry_score="10.0",
        aggregated_score="37.0",
        check_type="Standard",
        legal_existence_outcome="OK",
        legal_existence_comment="confirmed via Handelsregister Munich HRB 167270",
        inter_rows=[("completed", "L", "no adverse signal")] * 10,
        questionnaire_collected="x (collected)",
        shareholder_structure="Wholly owned by City of Munich",
        ubos_list="N/A — public-sector entity",
        risk_summary="Low — top-quartile OECD jurisdiction, public-sector counterparty",
        general_comments="Multi-year supply relationship, no escalation history.",
        legal_consulted="no",
        legal_opinion="n/a",
        outcome="positive",
        supporting_docs="Docusign/sharedrive",
        kyc_expert="Hans Lutter",
        expert_signature="signed",
        signature_date="14-01-2026",
        footer_note="Outcome positive — counterparty cleared for Core relationship.",
    ),
    Scenario(
        filename="mid-br-trading.pdf",
        profit_centre="MET Trading International",
        activity_trigger="Annual Review",
        business_relationship="Noncore",
        start_date="22.02.2026",
        counterparty="COMERCIAL ITAMARATY ENERGIA LTDA",
        address="Av. Brigadeiro Faria Lima 3600, Sao Paulo SP 04538-132, Brazil",
        primary_business="Wholesale Energy Trading",
        short_description="Counterparty/LNG-Power Spread Trades",
        country="Brazil",
        sanctions_applicable="no",
        sanctions_conclusion="Standard Check possible — collateral required",
        cpi_rank="94",
        cpi_score="18",
        notional_band="USD 100M+ band",
        notional_score="35",
        industry_label="Wholesale Energy Trading",
        industry_score="22.5",
        aggregated_score="75.5",
        check_type="Enhanced",
        legal_existence_outcome="OK",
        legal_existence_comment="confirmed via JUCESP SP filings — CNPJ verified",
        inter_rows=[
            ("completed", "L", "structure clear"),
            ("completed", "M", "UBOs verified, one with previous regulatory censure 2019"),
            ("completed", "L", "no sanctions hit"),
            ("completed", "L", "no sanctions hit"),
            ("completed", "M", "two adverse news items 2022-2024 — both resolved"),
            ("completed", "L", "no adverse signal"),
            ("completed", "M", "PRC notification pending — sector level"),
            ("completed", "L", "no adverse signal"),
            ("completed", "L", "no PEP signal"),
            ("completed", "L", "no PEP signal"),
        ],
        questionnaire_collected="x (collected — Q4 2025 refresh)",
        shareholder_structure="Diversified — see Moody's report",
        ubos_list="3 UBOs disclosed, all over 20% — see Moody's report",
        risk_summary="Medium — emerging-market jurisdiction, two M-rated rows on adverse media and PRC pending",
        general_comments="Collateral posting + quarterly review imposed as condition.",
        legal_consulted="yes",
        legal_opinion="No legal impediment — recommend conditions outlined in commercial terms.",
        outcome="positive_with_conditions",
        supporting_docs="Docusign/sharedrive",
        kyc_expert="Laila Andrade",
        expert_signature="signed",
        signature_date="22-02-2026",
        footer_note="Outcome positive with conditions — collateral + quarterly review required.",
    ),
    Scenario(
        filename="high-risk-ru-gas.pdf",
        profit_centre="MET Trading International",
        activity_trigger="Reverse Inquiry",
        business_relationship="Noncore",
        start_date="11.03.2026",
        counterparty="GAZSERVIS NORTHWEST OOO",
        address="ul. Tverskaya 16, 125009 Moscow, Russian Federation",
        primary_business="Natural Gas Trading",
        short_description="Counterparty/Spot Gas Supply Inquiry",
        country="Russia",
        sanctions_applicable="yes",
        sanctions_conclusion="Sanctions hit — counterparty SDN-affiliated, no standard check possible",
        cpi_rank="141",
        cpi_score="32",
        notional_band="EUR 50M band",
        notional_score="22",
        industry_label="Natural Gas Trading (high-risk jurisdiction)",
        industry_score="28.0",
        aggregated_score="82.0",
        check_type="Blocked",
        legal_existence_outcome="OK",
        legal_existence_comment="Entity exists per Russian unified state register, but sanctioned",
        inter_rows=[
            ("completed", "H", "complex offshore layering — Cyprus + UAE shells"),
            ("completed", "H", "two UBOs are SDN-listed individuals"),
            ("completed", "H", "OFAC SDN hit — direct match on UBOs"),
            ("completed", "H", "OFAC SDN hit on UBOs"),
            ("completed", "H", "multiple adverse media items — sanctions evasion allegations"),
            ("completed", "H", "adverse media on UBOs — same family of allegations"),
            ("completed", "M", "regulatory consent revoked Q3 2024"),
            ("completed", "H", "two UBOs hit"),
            ("completed", "H", "PEP exposure — political affiliations"),
            ("completed", "H", "PEP exposure — UBO family members"),
        ],
        questionnaire_collected="x (collected)",
        shareholder_structure="Layered via Cyprus and UAE — see Moody's report",
        ubos_list="2 UBOs disclosed, both SDN-listed — see Moody's report",
        risk_summary="HIGH — sanctions hit on entity-affiliated UBOs, 8 H-graded rows on intermediate checklist",
        general_comments="No commercial relationship possible under current sanctions regime.",
        legal_consulted="yes",
        legal_opinion="Sanctions block any further engagement. Onboarding rejected.",
        outcome="negative",
        supporting_docs="Docusign/sharedrive — SDN screenshots attached",
        kyc_expert="Diana Wojcik",
        expert_signature="signed",
        signature_date="11-03-2026",
        footer_note="Outcome NEGATIVE — counterparty blocked. No commercial engagement permitted.",
    ),
    Scenario(
        filename="gambling-mt.pdf",
        profit_centre="MET Polska S.A.",
        activity_trigger="Pre-Check",
        business_relationship="Noncore",
        start_date="05.04.2026",
        counterparty="PINNACLE ENTERTAINMENT MALTA LIMITED",
        address="Level 3 Quantum House, Triq Mikiel Anton Vassalli, Valletta VLT 1310, Malta",
        primary_business="Online Gaming & Sports Betting Operator",
        short_description="Counterparty/Power Supply — data centre load",
        country="Malta",
        sanctions_applicable="no",
        sanctions_conclusion="Standard Check possible — sectoral enhanced DD applies",
        cpi_rank="51",
        cpi_score="12",
        notional_band="EUR 15M band",
        notional_score="14",
        industry_label="Online Gambling (FATF high-risk sector)",
        industry_score="25.5",
        aggregated_score="51.5",
        check_type="Enhanced",
        legal_existence_outcome="OK",
        legal_existence_comment="Maltese Companies Register C 71204, MGA licence MGA/B2C/470/2018",
        inter_rows=[
            ("completed", "L", "single-tier holding — Malta + Cayman parent"),
            ("completed", "M", "one UBO has Cypriot residence, beneficial ownership opaque"),
            ("completed", "L", "no sanctions hit"),
            ("completed", "L", "no sanctions hit"),
            ("pending", "", "Sigma 2024 panel mention — under review by Compliance"),
            ("completed", "L", "no adverse signal"),
            ("completed", "L", "MGA active, no enforcement"),
            ("completed", "L", "no UBO concerns"),
            ("completed", "L", "no PEP signal"),
            ("pending", "", "PEP screen on Cayman trust beneficiaries pending"),
        ],
        questionnaire_collected="x (collected)",
        shareholder_structure="Cayman trust — see Moody's report",
        ubos_list="UBO disclosure pending Cayman trust unwrap",
        risk_summary="Pending — two pending intermediate rows, sector is FATF-elevated. Awaiting Compliance sign-off.",
        general_comments="Defer outcome until Pinnacle delivers updated UBO certificate from trust administrator.",
        legal_consulted="yes",
        legal_opinion="Standby — outcome conditional on UBO disclosure.",
        outcome="pending",
        supporting_docs="Docusign/sharedrive",
        kyc_expert="Karina Nowak",
        expert_signature="",
        signature_date="",
        footer_note="Outcome PENDING — awaiting Cayman trust UBO disclosure before final decision.",
    ),
    Scenario(
        filename="clean-ch-finance.pdf",
        profit_centre="MET Trading International",
        activity_trigger="Annual Review",
        business_relationship="Core",
        start_date="18.05.2026",
        counterparty="ZURICH KANTONALBANK ENERGY TRADING AG",
        address="Bahnhofstrasse 9, 8001 Zurich, Switzerland",
        primary_business="Bank-Owned Energy Trading Desk",
        short_description="Counterparty/Power & Carbon Trading",
        country="Switzerland",
        sanctions_applicable="no",
        sanctions_conclusion="Standard Check possible",
        cpi_rank="7",
        cpi_score="2",
        notional_band="CHF 200M band",
        notional_score="35",
        industry_label="Bank-Owned Trading (cantonal bank)",
        industry_score="8.5",
        aggregated_score="45.5",
        check_type="Standard",
        legal_existence_outcome="OK",
        legal_existence_comment="Confirmed via Zefix CH-020.3.046.847-5",
        inter_rows=[("completed", "L", "no adverse signal")] * 10,
        questionnaire_collected="x (collected)",
        shareholder_structure="100% Zurich Kantonalbank (statutory entity, Canton Zurich)",
        ubos_list="N/A — public-law cantonal bank",
        risk_summary="Low — Swiss public-sector bank, multi-year clean track record",
        general_comments="Existing ISDA in place since 2019, no incidents.",
        legal_consulted="no",
        legal_opinion="n/a",
        outcome="positive",
        supporting_docs="Docusign/sharedrive",
        kyc_expert="Bruno Frei",
        expert_signature="signed",
        signature_date="18-05-2026",
        footer_note="Outcome positive — Core relationship maintained.",
    ),
]


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=14, alignment=1, spaceAfter=6),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=10, spaceBefore=6, spaceAfter=4),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=8, leading=10),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontSize=7, leading=9),
    }


def _kv_table(rows, col_widths):
    t = Table(rows, colWidths=col_widths)
    t.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E8EEF7")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ])
    )
    return t


_INTER_ITEMS = [
    "Shareholders' Structure Chart",
    "UBOs identified with >=20% stake",
    "Sanctions check on counterparty",
    "Sanctions check on UBOs (>=20%)",
    "Negative news search on counterparty",
    "Negative news search on UBOs (>=20%)",
    "Regulatory Compliance Check on counterparty",
    "Regulatory Compliance Check on UBOs (>=20%)",
    "Reputational / PEP on counterparty",
    "Reputational / PEP Check on UBOs (>=20%)",
]


def build(path: Path, s: Scenario) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="MET Group Standard KYC Check Report",
    )
    st = _styles()
    story = []

    story.append(Paragraph("MET GROUP", st["title"]))
    story.append(Paragraph("Standard KYC Check Report", st["h2"]))
    story.append(Spacer(1, 4))

    admin = [
        ["Profit Centre", s.profit_centre],
        ["Activity Trigger", s.activity_trigger],
        ["Business Relationship", s.business_relationship],
        ["Start Date of the Check", s.start_date],
    ]
    story.append(_kv_table(admin, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Counterparty Identification", st["h2"]))
    cp = [
        ["Counterparty", s.counterparty],
        ["Address", s.address],
        ["Primary Business", s.primary_business],
        ["Short Description", s.short_description],
    ]
    story.append(_kv_table(cp, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Sanctions Pre-Screening", st["h2"]))
    sanc = [
        ["Country of Domicile", s.country],
        ["Sanctions applicable", s.sanctions_applicable],
        ["Conclusion", s.sanctions_conclusion],
    ]
    story.append(_kv_table(sanc, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Tri-Indicator Score", st["h2"]))
    tri_rows = [
        ["Indicator", "Title", "Value", "Score"],
        ["Indicator I", "Country of Domicile Corruption Index Rank", s.cpi_rank, s.cpi_score],
        ["Indicator II", "Annual Contracted Volume / Notional Value", s.notional_band, s.notional_score],
        ["Indicator III", "Industry Segment", s.industry_label, s.industry_score],
        ["Aggregated Score", "", "", s.aggregated_score],
        ["Type of Check", "", "", s.check_type],
    ]
    tri = Table(tri_rows, colWidths=[27 * mm, 80 * mm, 35 * mm, 33 * mm])
    tri.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("BACKGROUND", (0, 4), (-1, 5), colors.HexColor("#F4F8FC")),
        ("FONTNAME", (0, 4), (0, 5), "Helvetica-Bold"),
    ]))
    story.append(tri)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Basic Compliance Check", st["h2"]))
    bc = [
        ["Check", "Outcome", "Comment"],
        ["Verification of legal existence", s.legal_existence_outcome, s.legal_existence_comment],
    ]
    bc_t = Table(bc, colWidths=[80 * mm, 30 * mm, 65 * mm])
    bc_t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    story.append(bc_t)
    story.append(Spacer(1, 6))

    story.append(Paragraph("Intermediate Compliance Checks", st["h2"]))
    inter_rows = [["#", "Check", "Status", "Risk", "Comment"]]
    for i, (item, row) in enumerate(zip(_INTER_ITEMS, s.inter_rows), start=1):
        status, risk, comment = row
        inter_rows.append([str(i), item, status, risk, comment])
    inter = Table(inter_rows, colWidths=[8 * mm, 100 * mm, 22 * mm, 15 * mm, 30 * mm])
    # Risk column shading varies by grade — light green for L, amber for M, light red for H
    risk_cell_styles = []
    for row_idx, (_, risk, _) in enumerate(s.inter_rows, start=1):
        if risk == "L":
            color = colors.HexColor("#E8F8EF")
        elif risk == "M":
            color = colors.HexColor("#FFF4DB")
        elif risk == "H":
            color = colors.HexColor("#FCE4E4")
        else:
            color = colors.HexColor("#F0F0F0")
        risk_cell_styles.append(("BACKGROUND", (3, row_idx), (3, row_idx), color))
    inter.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        *risk_cell_styles,
    ]))
    story.append(inter)

    story.append(PageBreak())

    story.append(Paragraph("MET Group Standard KYC Check Report — Page 2", st["h2"]))
    story.append(Spacer(1, 4))

    page2 = [
        ["Questionnaire collected", s.questionnaire_collected],
        ["Shareholder structure", s.shareholder_structure],
        ["List of UBOs (>=20%)", s.ubos_list],
        ["Summary of compliance risk assessment", s.risk_summary],
        ["General Comments", s.general_comments],
        ["Legal consulted", s.legal_consulted],
        ["Legal opinion summary", s.legal_opinion],
        ["Outcome of the check", s.outcome],
        ["Supporting docs location", s.supporting_docs],
        ["KYC Expert", s.kyc_expert],
        ["KYC Expert signature", s.expert_signature],
        ["Signature date", s.signature_date],
    ]
    story.append(_kv_table(page2, [70 * mm, 105 * mm]))
    story.append(Spacer(1, 8))

    story.append(Paragraph(s.footer_note, st["small"]))
    doc.build(story)
    return path


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "contractiq" / "e2e" / "fixtures" / "variants"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"writing variants to: {out_dir}")
    for s in SCENARIOS:
        built = build(out_dir / s.filename, s)
        print(f"  wrote {built.name}  outcome={s.outcome}  country={s.country}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
