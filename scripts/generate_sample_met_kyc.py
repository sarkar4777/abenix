#!/usr/bin/env python3
"""Generate a sample MET-template KYC PDF used by the e2e suite.

The fixture mirrors the data on the reference screenshot:
  Profit centre: MET Polska S.A.
  Activity Trigger: Pre-Check
  Business Relationship: Noncore
  Start Date: 29.07.2025
  Counterparty: MALTA-DECOR SP. Z O.O.
  Address: WOLKOWYSKA 32 61-132 POZNAN Poland
  Primary Business: Wood, Furniture & Paper Manufacturing
  Short Desc: Counterparty/Gas Sales
  Sanctions: Poland, no (Standard Check possible)
  Indicators: I=7, II=20, III=16.25, Aggregated=42.25, Type=Standard
  Basic Compliance: Verification of legal existence OK, comment "exist"
  10 Intermediate Checks all completed with risk L
  Page 2: Questionnaire collected, references to Moody's report,
  outcome positive, KYC Expert "Przemyslaw Szczypinski", date 29-07-2025.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    sys.stderr.write(
        "reportlab is required. Install with: pip install reportlab\n"
    )
    sys.exit(2)


DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "contractiq"
    / "e2e"
    / "fixtures"
    / "sample_met_kyc.pdf"
)


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontSize=14,
            alignment=1,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontSize=10,
            spaceBefore=6,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontSize=8,
            leading=10,
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontSize=7,
            leading=9,
        ),
    }


def _kv_table(rows, col_widths):
    t = Table(rows, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
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
            ]
        )
    )
    return t


def build(path: Path, variant: str = "full") -> Path:
    """variant: full | blank | unsigned.

    - full: signed, filled, outcome positive (default).
    - blank: only headers — every value cell is empty so the parser must
      return null envelopes everywhere.
    - unsigned: filled administrative + indicator block but no KYC Expert
      signature, no signature date, and no outcome — questionnaire still
      collected without a date, kyc_expert_signed must be null.
    """
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
    blank = variant == "blank"
    unsigned = variant == "unsigned"

    # ── HEADER ──
    story.append(Paragraph("MET GROUP", st["title"]))
    story.append(Paragraph("Standard KYC Check Report", st["h2"]))
    story.append(Spacer(1, 4))

    # Administrative block
    if blank:
        admin = [
            ["Profit Centre", ""],
            ["Activity Trigger", ""],
            ["Business Relationship", ""],
            ["Start Date of the Check", ""],
        ]
    else:
        admin = [
            ["Profit Centre", "MET Polska S.A."],
            ["Activity Trigger", "Pre-Check"],
            ["Business Relationship", "Noncore"],
            ["Start Date of the Check", "29.07.2025"],
        ]
    story.append(_kv_table(admin, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    # Counterparty identification
    story.append(Paragraph("Counterparty Identification", st["h2"]))
    if blank:
        cp = [
            ["Counterparty", ""],
            ["Address", ""],
            ["Primary Business", ""],
            ["Short Description", ""],
        ]
    else:
        cp = [
            ["Counterparty", "MALTA-DECOR SP. Z O.O."],
            ["Address", "WOLKOWYSKA 32 61-132 POZNAN Poland"],
            ["Primary Business", "Wood, Furniture & Paper Manufacturing"],
            ["Short Description", "Counterparty/Gas Sales"],
        ]
    story.append(_kv_table(cp, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    # Sanctions pre-screen
    story.append(Paragraph("Sanctions Pre-Screening", st["h2"]))
    if blank:
        sanc = [
            ["Country of Domicile", ""],
            ["Sanctions applicable", ""],
            ["Conclusion", ""],
        ]
    else:
        sanc = [
            ["Country of Domicile", "Poland"],
            ["Sanctions applicable", "no"],
            ["Conclusion", "Standard Check possible"],
        ]
    story.append(_kv_table(sanc, [55 * mm, 120 * mm]))
    story.append(Spacer(1, 6))

    # Tri-indicator score
    story.append(Paragraph("Tri-Indicator Score", st["h2"]))
    tri_header = ["Indicator", "Title", "Value", "Score"]
    if blank:
        tri_rows = [
            tri_header,
            ["Indicator I", "", "", ""],
            ["Indicator II", "", "", ""],
            ["Indicator III", "", "", ""],
            ["Aggregated Score", "", "", ""],
            ["Type of Check", "", "", ""],
        ]
    else:
        tri_rows = [
            tri_header,
            ["Indicator I", "Country of Domicile Corruption Index Rank", "55", "7"],
            ["Indicator II", "Annual Contracted Volume / Notional Value", "USD 25M band", "20"],
            ["Indicator III", "Industry Segment", "Wood, Furniture & Paper", "16.25"],
            ["Aggregated Score", "", "", "42.25"],
            ["Type of Check", "", "", "Standard"],
        ]
    tri = Table(tri_rows, colWidths=[27 * mm, 80 * mm, 35 * mm, 33 * mm])
    tri.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 4), (-1, 5), colors.HexColor("#F4F8FC")),
                ("FONTNAME", (0, 4), (0, 5), "Helvetica-Bold"),
            ]
        )
    )
    story.append(tri)
    story.append(Spacer(1, 6))

    # Basic compliance
    story.append(Paragraph("Basic Compliance Check", st["h2"]))
    if blank:
        bc = [
            ["Check", "Outcome", "Comment"],
            ["Verification of legal existence", "", ""],
        ]
    else:
        bc = [
            ["Check", "Outcome", "Comment"],
            ["Verification of legal existence", "OK", "exist"],
        ]
    bc_t = Table(bc, colWidths=[80 * mm, 30 * mm, 65 * mm])
    bc_t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ]
        )
    )
    story.append(bc_t)
    story.append(Spacer(1, 6))

    # Intermediate compliance checks (10 items, all completed, all L)
    story.append(Paragraph("Intermediate Compliance Checks", st["h2"]))
    items = [
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
    inter_rows = [["#", "Check", "Status", "Risk", "Comment"]]
    for i, label in enumerate(items, start=1):
        if blank:
            inter_rows.append([str(i), label, "", "", ""])
        else:
            inter_rows.append([str(i), label, "completed", "L", "no adverse signal"])
    inter = Table(inter_rows, colWidths=[8 * mm, 100 * mm, 22 * mm, 15 * mm, 30 * mm])
    inter.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D8E2EF")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (3, 1), (3, -1), colors.HexColor("#E8F8EF")),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (3, 0), (3, -1), "CENTER"),
            ]
        )
    )
    story.append(inter)

    # PAGE BREAK
    story.append(PageBreak())

    story.append(Paragraph("MET Group Standard KYC Check Report — Page 2", st["h2"]))
    story.append(Spacer(1, 4))

    # Page 2 — review & sign-off block
    if blank:
        page2 = [
            ["Questionnaire collected", ""],
            ["Shareholder structure", ""],
            ["List of UBOs (>=20%)", ""],
            ["Summary of compliance risk assessment", ""],
            ["General Comments", ""],
            ["Legal consulted", ""],
            ["Legal opinion summary", ""],
            ["Outcome of the check", ""],
            ["Supporting docs location", ""],
            ["KYC Expert", ""],
            ["KYC Expert signature", ""],
            ["Signature date", ""],
        ]
    elif unsigned:
        # Filled but expert is NOT signed: KYC Expert blank, signature blank,
        # signature date blank, outcome blank too so the row stays unresolved.
        page2 = [
            ["Questionnaire collected", "x"],
            ["Shareholder structure", "In the Moody's report"],
            ["List of UBOs (>=20%)", "In the Moody's report"],
            ["Summary of compliance risk assessment", "Pending sign-off"],
            ["General Comments", "-"],
            ["Legal consulted", "no"],
            ["Legal opinion summary", "n/a"],
            ["Outcome of the check", ""],
            ["Supporting docs location", "Docusign/sharedrive"],
            ["KYC Expert", ""],
            ["KYC Expert signature", ""],
            ["Signature date", ""],
        ]
    else:
        page2 = [
            ["Questionnaire collected", "x (collected)"],
            ["Shareholder structure", "In the Moody's report"],
            ["List of UBOs (>=20%)", "In the Moody's report"],
            ["Summary of compliance risk assessment", "Low — no red flags identified across all 10 intermediate checks"],
            ["General Comments", "-"],
            ["Legal consulted", "no"],
            ["Legal opinion summary", "n/a"],
            ["Outcome of the check", "positive"],
            ["Supporting docs location", "Docusign/sharedrive"],
            ["KYC Expert", "Przemyslaw Szczypinski"],
            ["KYC Expert signature", "signed"],
            ["Signature date", "29-07-2025"],
        ]
    p2 = _kv_table(page2, [70 * mm, 105 * mm])
    story.append(p2)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "This document was produced for compliance evidence under the MET Group "
            "Standard KYC procedure. Outcome positive — counterparty cleared.",
            st["small"],
        )
    )

    doc.build(story)
    return path


def main() -> int:
    out_dir = Path(os.environ.get("MET_KYC_OUT") or DEFAULT_OUT)
    # When MET_KYC_VARIANT is set, emit only that variant. Default behaviour
    # emits all three side-by-side so the e2e suite has everything it needs.
    variant = os.environ.get("MET_KYC_VARIANT", "").strip().lower()
    if variant in {"full", "blank", "unsigned"}:
        target = out_dir
        if target.is_dir():
            target = target / f"sample_met_kyc_{variant}.pdf"
        built = build(target, variant=variant)
        print(f"wrote {built}")
        return 0
    # Default — emit all three under contractiq/e2e/fixtures/
    base = out_dir if out_dir.is_dir() else out_dir.parent
    base.mkdir(parents=True, exist_ok=True)
    for v, name in (
        ("full", "sample_met_kyc.pdf"),
        ("blank", "sample_met_kyc_blank.pdf"),
        ("unsigned", "sample_met_kyc_unsigned.pdf"),
    ):
        built = build(base / name, variant=v)
        print(f"wrote {built}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
