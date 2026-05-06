#!/usr/bin/env python3
"""Render EDGE_AGENTS_GUIDE.md to a polished client-facing PDF.

Pure reportlab — no pandoc, no headless browser. Handles:
  - h1/h2/h3 with section breaks for h1
  - paragraphs with **bold** + `code` + *italic* inline runs
  - bullet + numbered lists (1 level)
  - tables (markdown pipe-style)
  - fenced code blocks (preformatted, monospace, framed)
  - horizontal rules
  - block quotes
  - title page + auto TOC

Run: py -3 scripts/generate-edge-guide-pdf.py
Output: EDGE_AGENTS_GUIDE.pdf at repo root.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "EDGE_AGENTS_GUIDE.md"
DST = ROOT / "EDGE_AGENTS_GUIDE.pdf"


# Register Bitstream Vera (ships with reportlab) - full Unicode coverage so
# em-dashes, arrows, smart quotes etc. render correctly.
_RL_FONTS = (
    Path(pdfmetrics.__file__).resolve().parent.parent / "fonts"
)
pdfmetrics.registerFont(TTFont("Body", str(_RL_FONTS / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Body-Bold", str(_RL_FONTS / "VeraBd.ttf")))
pdfmetrics.registerFont(TTFont("Body-Italic", str(_RL_FONTS / "VeraIt.ttf")))
pdfmetrics.registerFont(
    TTFont("Body-BoldItalic", str(_RL_FONTS / "VeraBI.ttf"))
)
# Mono — try system Consolas (Windows) or fall back to built-in Courier.
_MONO = None
for cand in [
    Path("C:/Windows/Fonts/consola.ttf"),
    Path("/Library/Fonts/Menlo.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
]:
    if cand.exists():
        _MONO = str(cand)
        break

if _MONO:
    pdfmetrics.registerFont(TTFont("Mono", _MONO))
else:
    # Fall back to the built-in Type-1 Courier - code blocks are ASCII so
    # the missing-glyph problem doesn't apply there.
    from reportlab.lib.fonts import addMapping  # noqa: F401

    # alias "Mono" to Courier so style references keep working.
    pdfmetrics.registerFontFamily("Courier", normal="Courier")
    # registerFont copy-alias trick
    from reportlab.pdfbase.pdfmetrics import _fonts as _rl_fonts

    _rl_fonts["Mono"] = _rl_fonts["Courier"]
from reportlab.pdfbase.pdfmetrics import registerFontFamily

registerFontFamily(
    "Body",
    normal="Body",
    bold="Body-Bold",
    italic="Body-Italic",
    boldItalic="Body-BoldItalic",
)


# ── Palette ────────────────────────────────────────────────────────────
INK = colors.HexColor("#0f172a")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748b")
ACCENT = colors.HexColor("#06b6d4")
ACCENT_DARK = colors.HexColor("#0e7490")
BG_CODE = colors.HexColor("#0f172a")
FG_CODE = colors.HexColor("#e2e8f0")
TBL_HEAD = colors.HexColor("#0e7490")
TBL_ROW = colors.HexColor("#f1f5f9")


# ── Styles ─────────────────────────────────────────────────────────────
def build_styles():
    base = getSampleStyleSheet()
    s = {}

    s["title"] = ParagraphStyle(
        "title",
        parent=base["Title"],
        fontName="Body-Bold",
        fontSize=34,
        leading=42,
        textColor=INK,
        alignment=TA_CENTER,
        spaceAfter=18,
    )
    s["subtitle"] = ParagraphStyle(
        "subtitle",
        parent=base["Normal"],
        fontName="Body-Italic",
        fontSize=14,
        leading=20,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    s["h1"] = ParagraphStyle(
        "h1",
        parent=base["Heading1"],
        fontName="Body-Bold",
        fontSize=22,
        leading=28,
        textColor=ACCENT_DARK,
        spaceBefore=2,
        spaceAfter=10,
        keepWithNext=True,
    )
    s["h2"] = ParagraphStyle(
        "h2",
        parent=base["Heading2"],
        fontName="Body-Bold",
        fontSize=15,
        leading=20,
        textColor=INK,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    s["h3"] = ParagraphStyle(
        "h3",
        parent=base["Heading3"],
        fontName="Body-Bold",
        fontSize=12,
        leading=16,
        textColor=SLATE,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    s["body"] = ParagraphStyle(
        "body",
        parent=base["BodyText"],
        fontName="Body",
        fontSize=10,
        leading=15,
        textColor=INK,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    s["body_left"] = ParagraphStyle(
        "body_left",
        parent=s["body"],
        alignment=TA_LEFT,
    )
    s["bullet"] = ParagraphStyle(
        "bullet",
        parent=s["body_left"],
        leftIndent=14,
        bulletIndent=2,
        spaceAfter=3,
    )
    s["quote"] = ParagraphStyle(
        "quote",
        parent=s["body"],
        fontName="Body-Italic",
        leftIndent=18,
        rightIndent=18,
        textColor=SLATE,
        borderPadding=6,
        spaceAfter=8,
    )
    s["code"] = ParagraphStyle(
        "code",
        parent=base["Normal"],
        fontName="Mono",
        fontSize=8.5,
        leading=11,
        textColor=FG_CODE,
        backColor=BG_CODE,
        leftIndent=8,
        rightIndent=8,
        borderPadding=8,
        spaceBefore=6,
        spaceAfter=10,
    )
    s["toc_h1"] = ParagraphStyle(
        "toc_h1",
        parent=s["body_left"],
        fontName="Body-Bold",
        fontSize=11,
        leading=16,
        textColor=INK,
        leftIndent=0,
    )
    s["toc_h2"] = ParagraphStyle(
        "toc_h2",
        parent=s["body_left"],
        fontSize=10,
        leading=14,
        textColor=SLATE,
        leftIndent=14,
    )
    s["caption"] = ParagraphStyle(
        "caption",
        parent=s["body"],
        fontName="Body-Italic",
        fontSize=8.5,
        leading=11,
        textColor=MUTED,
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    s["page_footer"] = ParagraphStyle(
        "page_footer",
        parent=s["body"],
        fontSize=8,
        leading=10,
        textColor=MUTED,
        alignment=TA_CENTER,
    )
    return s


# ── Inline span conversion: markdown → reportlab mini-HTML ───────────
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
ITALIC_RE = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")


def md_inline(text: str) -> str:
    """Convert markdown inline syntax to reportlab paragraph mini-HTML."""
    # XML escape first
    text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # Vera (our body font) covers em-dash, ellipsis, smart quotes, degree.
    # It does NOT cover arrow glyphs - substitute with ASCII safe forms.
    text = (
        text.replace(chr(0x2192), " -> ")        # right arrow
        .replace(chr(0x2190), " <- ")            # left arrow
        .replace(chr(0x2191), " ^ ")             # up arrow
        .replace(chr(0x2193), " v ")             # down arrow
        .replace(chr(0x2194), " <-> ")           # left-right arrow
        .replace(chr(0x00D7), "x")               # multiplication
        .replace(chr(0x2713), "[ok]")            # check
        .replace(chr(0x2717), "[x]")             # x mark
        .replace(chr(0x2588), "#")               # block
        .replace(chr(0x25CF), "*")               # filled circle
        .replace(chr(0x25CB), "o")               # empty circle
    )
    # inline code → bg-tinted monospace
    text = INLINE_CODE_RE.sub(
        r'<font name="Mono" color="#0e7490">\1</font>', text
    )
    # bold
    text = BOLD_RE.sub(r"<b>\1</b>", text)
    # italic - single-asterisk only outside of words
    text = ITALIC_RE.sub(r"<i>\1</i>", text)
    return text


# ── Markdown line parser → flowables ──────────────────────────────────
def parse_table(rows):
    """Build a Table flowable from a list of pipe-split markdown rows."""
    cleaned = []
    for r in rows:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        cleaned.append(cells)
    if len(cleaned) < 2:
        return None
    # second row is the separator (---)
    header = cleaned[0]
    body = cleaned[2:]
    n_cols = len(header)

    s = build_styles()
    head_cells = [
        Paragraph(
            f'<font color="white"><b>{md_inline(h)}</b></font>',
            ParagraphStyle("th", parent=s["body_left"], fontSize=10, textColor=colors.white),
        )
        for h in header
    ]
    body_cells = [
        [Paragraph(md_inline(c), s["body_left"]) for c in row[:n_cols]]
        for row in body
    ]
    data = [head_cells] + body_cells

    # column widths — share usable width equally
    avail = 17 * cm
    col_w = [avail / n_cols] * n_cols
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TBL_HEAD),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Body-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TBL_ROW]),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, ACCENT_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return t


def parse_markdown(md: str):
    s = build_styles()
    flows = []
    h1_index = []
    h2_index = []

    lines = md.splitlines()
    i = 0
    in_code = False
    code_buf = []
    in_table = False
    table_buf = []
    in_list = False
    list_buf = []
    list_kind = None  # "ul" or "ol"

    def flush_list():
        nonlocal list_buf, in_list, list_kind
        if not list_buf:
            return
        items = [
            ListItem(Paragraph(md_inline(x), s["bullet"]), leftIndent=10)
            for x in list_buf
        ]
        bullet_type = "bullet" if list_kind == "ul" else "1"
        flows.append(
            ListFlowable(
                items,
                bulletType=bullet_type,
                start="bulletchar" if list_kind == "ul" else "1",
                bulletFontName="Body",
                bulletFontSize=10,
                leftIndent=14,
            )
        )
        flows.append(Spacer(1, 4))
        list_buf = []
        in_list = False
        list_kind = None

    def flush_table():
        nonlocal table_buf, in_table
        if table_buf:
            tbl = parse_table(table_buf)
            if tbl is not None:
                flows.append(KeepTogether(tbl))
                flows.append(Spacer(1, 6))
        table_buf = []
        in_table = False

    while i < len(lines):
        line = lines[i]

        # fenced code block
        if line.strip().startswith("```"):
            if in_code:
                flush_list()
                flush_table()
                # Render line-by-line as a multi-row Table so reportlab can
                # split the block across pages. Single-cell Tables can't.
                code_lines = code_buf if code_buf else [""]
                # One Preformatted flowable per line - they split cleanly
                # across pages when wrapped in a multi-row Table.
                rows = [[Preformatted(ln if ln else " ", s["code"])] for ln in code_lines]
                tbl = Table(rows, colWidths=[17 * cm], repeatRows=0)
                tbl.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), BG_CODE),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 0),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                            ("LINEABOVE", (0, 0), (-1, 0), 0.4, ACCENT_DARK),
                            ("LINEBELOW", (0, -1), (-1, -1), 0.4, ACCENT_DARK),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                flows.append(tbl)
                flows.append(Spacer(1, 8))
                code_buf = []
                in_code = False
            else:
                flush_list()
                flush_table()
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line.rstrip())
            i += 1
            continue

        # table — pipe-style
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            if not in_table:
                flush_list()
                in_table = True
            table_buf.append(line)
            i += 1
            continue
        elif in_table:
            flush_table()

        stripped = line.strip()

        # blank line
        if stripped == "":
            flush_list()
            flows.append(Spacer(1, 3))
            i += 1
            continue

        # horizontal rule
        if stripped == "---":
            flush_list()
            flows.append(Spacer(1, 4))
            flows.append(HRFlowable(width="100%", thickness=0.5, color=MUTED))
            flows.append(Spacer(1, 4))
            i += 1
            continue

        # headers
        if stripped.startswith("# "):
            flush_list()
            flows.append(PageBreak())
            txt = md_inline(stripped[2:])
            anchor = f"h1_{len(h1_index)}"
            flows.append(Paragraph(f'<a name="{anchor}"/>{txt}', s["h1"]))
            h1_index.append((stripped[2:], anchor))
            flows.append(HRFlowable(width="40%", thickness=2, color=ACCENT, hAlign="LEFT"))
            flows.append(Spacer(1, 8))
            i += 1
            continue
        if stripped.startswith("## "):
            flush_list()
            txt = md_inline(stripped[3:])
            anchor = f"h2_{len(h2_index)}"
            flows.append(Paragraph(f'<a name="{anchor}"/>{txt}', s["h2"]))
            h2_index.append((stripped[3:], anchor))
            i += 1
            continue
        if stripped.startswith("### "):
            flush_list()
            flows.append(Paragraph(md_inline(stripped[4:]), s["h3"]))
            i += 1
            continue

        # bullet list
        m_ul = re.match(r"^[\-\*]\s+(.*)$", stripped)
        m_ol = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if m_ul:
            if in_list and list_kind != "ul":
                flush_list()
            in_list = True
            list_kind = "ul"
            list_buf.append(m_ul.group(1))
            i += 1
            continue
        if m_ol:
            if in_list and list_kind != "ol":
                flush_list()
            in_list = True
            list_kind = "ol"
            list_buf.append(m_ol.group(2))
            i += 1
            continue
        if in_list:
            flush_list()

        # block quote
        if stripped.startswith(">"):
            txt = stripped.lstrip("> ").strip()
            flows.append(Paragraph(md_inline(txt), s["quote"]))
            i += 1
            continue

        # plain paragraph — collect until blank
        buf = [stripped]
        j = i + 1
        while j < len(lines) and lines[j].strip() and not (
            lines[j].strip().startswith(("#", "-", "*", ">", "|", "```"))
            or re.match(r"^\d+\.\s", lines[j].strip())
            or lines[j].strip() == "---"
        ):
            buf.append(lines[j].strip())
            j += 1
        flows.append(Paragraph(md_inline(" ".join(buf)), s["body"]))
        i = j

    # tail flushes
    flush_list()
    flush_table()
    if in_code and code_buf:
        flows.append(Preformatted("\n".join(code_buf), s["code"]))

    return flows, h1_index, h2_index


# ── Title page + TOC ──────────────────────────────────────────────────
def title_page(s):
    flows = [
        Spacer(1, 5 * cm),
        Paragraph("Abenix", s["title"]),
        Spacer(1, 0.3 * cm),
        Paragraph("The Edge Agent Guide", s["title"]),
        Spacer(1, 1 * cm),
        Paragraph(
            "How AI agents in the cloud and on the plant floor cooperate over MQTT — "
            "for clients, plant operators, and application developers.",
            s["subtitle"],
        ),
        Spacer(1, 4 * cm),
        HRFlowable(width="40%", thickness=1, color=ACCENT, hAlign="CENTER"),
        Spacer(1, 0.4 * cm),
        Paragraph(
            "An Abenix client-facing reference document.",
            ParagraphStyle("attr", parent=s["body"], alignment=TA_CENTER, textColor=MUTED, fontSize=9),
        ),
        PageBreak(),
    ]
    return flows


def toc_page(s, h1_list, h2_list):
    flows = [Paragraph("Contents", s["h1"]), Spacer(1, 6)]
    # interleave h1 and h2 in document order
    # We rebuild by walking h1 then any h2 before next h1.
    for title, anchor in h1_list:
        flows.append(
            Paragraph(
                f'<a href="#{anchor}" color="#0f172a">{md_inline(title)}</a>',
                s["toc_h1"],
            )
        )
    flows.append(PageBreak())
    return flows


# ── Page header / footer ──────────────────────────────────────────────
def on_page(canvas, doc):
    canvas.saveState()
    width, height = A4
    # footer
    canvas.setFont("Body", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(2 * cm, 1.5 * cm, "Abenix · Edge Agent Guide")
    canvas.drawRightString(
        width - 2 * cm, 1.5 * cm, f"Page {doc.page}"
    )
    # header rule
    canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
    canvas.setLineWidth(0.4)
    canvas.line(2 * cm, height - 1.6 * cm, width - 2 * cm, height - 1.6 * cm)
    canvas.restoreState()


def on_first_page(canvas, doc):
    # No header/footer on cover.
    pass


# ── Main ──────────────────────────────────────────────────────────────
def main():
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    md = SRC.read_text(encoding="utf-8")
    s = build_styles()

    body, h1_list, _ = parse_markdown(md)

    # the first chunk of body has a leading PageBreak from the first "# "
    # heading; remove it so the first H1 renders right after the TOC.
    if body and isinstance(body[0], PageBreak):
        body.pop(0)

    story = title_page(s) + toc_page(s, h1_list, _) + body

    doc = BaseDocTemplate(
        str(DST),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.2 * cm,
        bottomMargin=2 * cm,
        title="Abenix — Edge Agent Guide",
        author="Abenix",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal"
    )
    cover_template = PageTemplate(
        id="cover", frames=[frame], onPage=on_first_page
    )
    body_template = PageTemplate(id="body", frames=[frame], onPage=on_page)
    doc.addPageTemplates([cover_template, body_template])

    doc.build(story)
    size_kb = DST.stat().st_size // 1024
    print(f"wrote {DST}  ({size_kb} KB)")


if __name__ == "__main__":
    main()
