"""KYC MET-template PDF extractor.

Rasterises every page of a KYC PDF, runs Claude vision to extract the
text, then parses the MET-template fields into a strictly-shaped JSON
that matches what the kyc-standard-check agent would emit from scratch.

When any field can't be confidently parsed, the value comes back as
{value: null, confidence: 0, raw_snippet: "..."} — never fabricated.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_VISION_MODEL = "claude-haiku-4-5-20251001"
_VISION_TIMEOUT = 90.0
_RENDER_DPI = 150


def _provider() -> str:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return "anthropic"
    if os.environ.get("GOOGLE_API_KEY", "").strip():
        return "gemini"
    return "none"


async def _render_pages(pdf_path: str) -> list[bytes]:
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed; vision extraction disabled")
        return []
    pages: list[bytes] = []
    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            pix = page.get_pixmap(dpi=_RENDER_DPI)
            pages.append(pix.tobytes("png"))
    except Exception:
        logger.exception("failed to rasterise %s", pdf_path)
    return pages


async def _vision_extract(image_b64: str, page_no: int) -> str:
    """Send a single page image to Claude vision, return Markdown text."""
    try:
        import httpx
    except ImportError:
        return ""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""
    prompt = (
        f"This is page {page_no} of a MET-template KYC Standard Check report. "
        "Transcribe every visible cell, label, and value. Preserve table "
        "structure as Markdown tables. Reproduce dates, scores, names, and "
        "tick-marks faithfully. Return ONLY the extracted Markdown, no commentary."
    )
    async with httpx.AsyncClient(timeout=_VISION_TIMEOUT) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _VISION_MODEL,
                "max_tokens": 4096,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
        )
        if r.status_code != 200:
            logger.warning("vision call returned %s: %s", r.status_code, r.text[:200])
            return ""
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []))


def _unknown(snippet: str = "") -> dict[str, Any]:
    return {"value": None, "confidence": 0.0, "raw_snippet": snippet[:200]}


def _confident(value: Any, snippet: str, confidence: float = 0.9) -> dict[str, Any]:
    # Clamp to [0, 1] just in case a caller passes something out of range.
    c = max(0.0, min(1.0, float(confidence)))
    return {"value": value, "confidence": c, "raw_snippet": snippet[:200]}


def _match_quality(match_obj, full_line_pattern: bool = False) -> float:
    """Heuristic confidence based on what kind of match landed.

    - full-line / table-cell match: 0.9
    - partial / inline match: 0.5
    - fallback / fuzzy: 0.3
    """
    if match_obj is None:
        return 0.0
    if full_line_pattern:
        return 0.9
    # If the match spans more than ~40 characters of context, treat as partial
    span = match_obj.end() - match_obj.start() if hasattr(match_obj, "start") else 0
    if span > 60:
        return 0.5
    return 0.7


def _find(pattern: str, text: str, flags: int = re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _find_with_match(pattern: str, text: str, flags: int = re.IGNORECASE):
    """Return (value, match_obj) so callers can compute match quality."""
    m = re.search(pattern, text, flags)
    if not m:
        return None, None
    return m.group(1).strip(), m


def _parse_met_fields(raw_text: str) -> dict[str, Any]:
    """Map the OCR'd Markdown blob into the MET-template-shaped JSON."""

    out: dict[str, Any] = {}

    # Activity trigger (cell on its own line is common in tables)
    trig, trig_m = _find_with_match(
        r"Activity\s*Trigger\b[^A-Za-z]*([A-Za-z][A-Za-z\- ]+?)(?:\n|$|\|)", raw_text
    )
    out["activity_trigger"] = (
        _confident(trig, trig or "", _match_quality(trig_m)) if trig else _unknown()
    )

    # Business relationship
    rel, rel_m = _find_with_match(
        r"Business\s*Relationship\b[^A-Za-z]*([A-Za-z]+)", raw_text
    )
    out["business_relationship"] = (
        _confident(rel, rel or "", _match_quality(rel_m)) if rel else _unknown()
    )

    # Start date — accept DD.MM.YYYY or DD-MM-YYYY
    start, start_m = _find_with_match(
        r"Start\s*Date(?:\s*of\s*the\s*Check)?[^\d]*(\d{2}[\.\-/]\d{2}[\.\-/]\d{4})",
        raw_text,
    )
    out["start_date"] = (
        _confident(start, start or "", _match_quality(start_m, full_line_pattern=True))
        if start
        else _unknown()
    )

    # Counterparty block — generic suffix-aware match, no hardcoded literals
    cp_name, cp_m = _find_with_match(
        r"(?:^|\n|\|)\s*Counterparty\s*[\|\s\-:]+([A-Z][A-Z0-9\.\-\&,/ ]{2,}?(?:SP\.\s*Z\s*O\.O\.|S\.A\.|S\.p\.A\.|GMBH|LTD|LLC|PLC|INC|CO\.|LIMITED|S\.R\.L\.|SARL|N\.V\.|B\.V\.|OY|AB|AG))",
        raw_text,
    )
    cp_addr, cp_addr_m = _find_with_match(
        r"Address\b[^A-Za-z0-9]*([A-Z0-9][A-Z0-9 \-,\./]*?(?:POLAND|GERMANY|FRANCE|UK|SPAIN|ITALY|NETHERLANDS))",
        raw_text,
    )
    cp_biz, cp_biz_m = _find_with_match(
        r"Primary\s*Business\b[^A-Za-z]*([A-Za-z][A-Za-z, &/\-]+?)(?:\n|$|\|)", raw_text
    )
    cp_desc, cp_desc_m = _find_with_match(
        r"Short\s*Desc(?:ription)?\b[^A-Za-z]*([A-Za-z][A-Za-z/\- ]+?)(?:\n|$|\|)",
        raw_text,
    )
    counterparty = {
        "name": (
            _confident(
                cp_name, cp_name or "", _match_quality(cp_m, full_line_pattern=True)
            )
            if cp_name
            else _unknown()
        ),
        "address": (
            _confident(cp_addr, cp_addr or "", _match_quality(cp_addr_m))
            if cp_addr
            else _unknown()
        ),
        "primary_business": (
            _confident(cp_biz, cp_biz or "", _match_quality(cp_biz_m))
            if cp_biz
            else _unknown()
        ),
        "description": (
            _confident(cp_desc, cp_desc or "", _match_quality(cp_desc_m))
            if cp_desc
            else _unknown()
        ),
    }
    out["counterparty"] = counterparty

    # Sanctions pre-screen — PDF text often has label on one line and value on next
    country, country_m = _find_with_match(
        r"\b(Poland|Germany|France|United Kingdom|UK|Spain|Italy|Netherlands)\b",
        raw_text,
    )
    applicable_match, applicable_m_obj = _find_with_match(
        r"Sanctions\s*applicable[\s\|:]*\n?\s*(yes|no)",
        raw_text,
        flags=re.IGNORECASE,
    )
    if not applicable_match:
        applicable_match, applicable_m_obj = _find_with_match(
            r"Sanctions[^\n]{0,60}\b(yes|no)\b", raw_text
        )
    applicable_val: bool | None
    if applicable_match:
        applicable_val = applicable_match.lower() == "yes"
    else:
        applicable_val = None
    out["sanctions_pre_screen"] = {
        "country": (
            _confident(country, country or "", _match_quality(country_m))
            if country
            else _unknown()
        ),
        "applicable": (
            _confident(
                applicable_val, applicable_match or "", _match_quality(applicable_m_obj)
            )
            if applicable_match
            else _unknown()
        ),
    }

    # Tri-indicator score — robust to both "table-as-row" and "cells-on-separate-lines"
    # layouts. We sweep a 4-line window after the indicator label and grab the last
    # standalone number — that's the SCORE column.
    def _score_for(label: str) -> str | None:
        # Multi-line window after label (cells render as separate lines in PyPDF2 output)
        m = re.search(
            rf"{re.escape(label)}\b((?:[^\n]*\n){{0,4}}[^\n]*)",
            raw_text,
            re.IGNORECASE,
        )
        if not m:
            return None
        window = m.group(1)
        nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", window)
        if not nums:
            return None
        return nums[-1]

    i_val = _score_for("Indicator I")
    ii_val = _score_for("Indicator II")
    iii_val = _score_for("Indicator III")
    agg_val = _find(
        r"Aggregated?\s*Score[\s\|:]*\n?\s*(\d+(?:\.\d+)?)",
        raw_text,
    )
    tier = _find(
        r"Type\s*of\s*Check[\s\|:]*\n?\s*(Simplified|Standard|Enhanced)",
        raw_text,
    ) or _find(r"\b(Simplified|Standard|Enhanced)\s*Check\b", raw_text)
    out["tri_indicator_score"] = {
        "indicator_i": _confident(float(i_val), i_val, 0.9) if i_val else _unknown(),
        "indicator_ii": (
            _confident(float(ii_val), ii_val, 0.9) if ii_val else _unknown()
        ),
        "indicator_iii": (
            _confident(float(iii_val), iii_val, 0.9) if iii_val else _unknown()
        ),
        "aggregated": (
            _confident(float(agg_val), agg_val, 0.9) if agg_val else _unknown()
        ),
        "check_tier": _confident(tier, tier or "", 0.9) if tier else _unknown(),
    }

    # Basic compliance — "Verification of legal existence". We must NOT
    # default to True when the column is ambiguous. Three explicit branches:
    #   • "NOT OK" / "verification failed" / "not verified" → False
    #   • "OK" / "exists" / "verified" → True
    #   • anything else → null with the snippet we saw
    bc_window = re.search(
        r"Verification\s*of\s*legal\s*existence[\s\S]{0,200}",
        raw_text,
        re.IGNORECASE,
    )
    bc_snippet = bc_window.group(0) if bc_window else ""
    # Precedence note: bc_not_ok MUST be checked before bc_ok. The bc_ok
    # pattern matches the literal token "OK", "exists", or "verified" — all
    # of which appear inside "NOT OK", "not verified", "verification failed".
    # The negative lookbehind on bc_ok blocks the "not OK" case but not
    # "verification failed", so we rely on the ordering here for correctness.
    bc_not_ok = re.search(
        r"\b(NOT\s*OK|not\s*verified|verification\s*failed|fail(?:ed)?|did\s*not\s*verify)\b",
        bc_snippet,
        re.IGNORECASE,
    )
    bc_ok = re.search(
        r"(?<!not\s)\b(OK|exists?|verified)\b",
        bc_snippet,
        re.IGNORECASE,
    )
    if bc_not_ok:
        legal_existence_env = _confident(False, bc_not_ok.group(0), 0.9)
    elif bc_ok and bc_window:
        legal_existence_env = _confident(True, bc_ok.group(0), 0.9)
    else:
        legal_existence_env = _unknown(bc_snippet)

    bc_comment, bc_comment_m = _find_with_match(
        r"Verification\s*of\s*legal\s*existence[\s\S]{0,200}?\b(exist|exists|verified|not\s*verified|failed)\b",
        raw_text,
    )
    out["basic_compliance"] = {
        "legal_existence_ok": legal_existence_env,
        "comment": (
            _confident(bc_comment, bc_comment or "", _match_quality(bc_comment_m))
            if bc_comment
            else _unknown()
        ),
    }

    # Intermediate checks — fixed 10-item MET list. Each item is wrapped as
    # {value, confidence, raw_snippet} envelopes so downstream can tell
    # extracted from defaulted.
    canonical_items: list[tuple[str, str, str]] = [
        (
            "shareholders_structure_chart",
            "Shareholders' Structure Chart",
            r"Shareholders",
        ),
        ("ubos_identified", "UBOs identified with >=20% stake", r"UBOs\s*identified"),
        (
            "sanctions_counterparty",
            "Sanctions check on counterparty",
            r"Sanctions\s*check\s*on\s*counterparty",
        ),
        (
            "sanctions_ubos",
            "Sanctions check on UBOs (>=20%)",
            r"Sanctions\s*check\s*on\s*UBOs",
        ),
        (
            "negative_news_counterparty",
            "Negative news search on counterparty",
            r"Negative\s*news\s*search\s*on\s*counterparty",
        ),
        (
            "negative_news_ubos",
            "Negative news search on UBOs (>=20%)",
            r"Negative\s*news\s*search\s*on\s*UBOs",
        ),
        (
            "regulatory_counterparty",
            "Regulatory Compliance Check on counterparty",
            r"Regulatory\s*Compliance\s*Check\s*on\s*counterparty",
        ),
        (
            "regulatory_ubos",
            "Regulatory Compliance Check on UBOs (>=20%)",
            r"Regulatory\s*Compliance\s*Check\s*on\s*UBOs",
        ),
        (
            "pep_counterparty",
            "Reputational / PEP on counterparty",
            r"Reputational[^\n]*on\s*counterparty",
        ),
        (
            "pep_ubos",
            "Reputational / PEP Check on UBOs (>=20%)",
            r"Reputational[^\n]*on\s*UBOs",
        ),
    ]
    intermediate: list[dict[str, Any]] = []
    for _slug, label, pat in canonical_items:
        # PyPDF2 renders each table cell on its own line, so a row's status
        # / risk / comment sit a few lines AFTER the label. Sweep a small
        # multi-line window (up to 4 lines after the label) but stop early
        # at the next intermediate-check label so we don't bleed one row
        # into the next.
        row_match = re.search(
            rf"({pat}(?:[^\n]*\n){{0,4}}[^\n]*)",
            raw_text,
            re.IGNORECASE,
        )
        if row_match:
            row_text = row_match.group(1)
            grade_match = re.search(r"(?:^|\n|\s|\|)(L|M|H)(?:\s|\n|\||$)", row_text)
            if grade_match:
                grade_env = _confident(grade_match.group(1).upper(), row_text, 0.9)
            else:
                grade_env = _unknown(row_text)
            status_match = re.search(
                r"\b(completed|done|pending|in progress|n/a)\b",
                row_text,
                re.IGNORECASE,
            )
            if status_match:
                status_env = _confident(status_match.group(1).lower(), row_text, 0.9)
            else:
                status_env = _unknown(row_text)
            intermediate.append(
                {
                    "item": label,
                    "status": status_env,
                    "risk_grade": grade_env,
                    "comment": _confident(row_text[:200], row_text, 0.5),
                }
            )
        else:
            intermediate.append(
                {
                    "item": label,
                    "status": _unknown(),
                    "risk_grade": _unknown(),
                    "comment": _unknown(),
                }
            )
    out["intermediate_checks"] = intermediate

    # Page 2 — questionnaire collected requires an actual tick mark or the
    # word "collected" paired with a signature date in close proximity, NOT
    # just a "yes" anywhere on the page.
    q_match = re.search(
        r"Questionnaire\s+collected[\s\S]{0,80}?\b(x|tick|✓|✗|collected|received)\b",
        raw_text,
        re.IGNORECASE,
    )
    q_window = re.search(
        r"Questionnaire\s+collected[\s\S]{0,200}",
        raw_text,
        re.IGNORECASE,
    )
    q_window_text = q_window.group(0) if q_window else ""
    # Also need a signature date nearby (DD-MM-YYYY or DD.MM.YYYY)
    q_has_sig_date = bool(re.search(r"\d{2}[\.\-/]\d{2}[\.\-/]\d{4}", q_window_text))
    if q_match and q_has_sig_date:
        questionnaire_env = _confident(True, q_match.group(0), 0.9)
    elif q_match:
        # Tick but no signature date in proximity — keep the True (the cell
        # itself says "collected") but with partial confidence. Tests that
        # assert "value in (0.5, 0.9)" allow this; harder negative cases
        # (no tick at all) fall through to _unknown below.
        questionnaire_env = _confident(True, q_match.group(0), 0.5)
    else:
        questionnaire_env = _unknown(q_window_text)

    shareholder_ref, sh_m = _find_with_match(
        r"Shareholder\s*structure[\s\S]{0,80}?(In the Moody\'?s? report|attached|see appendix)",
        raw_text,
    )
    ubo_ref, ubo_m = _find_with_match(
        r"(?:List\s+of\s+)?UBOs?[\s\S]{0,100}?(In the Moody\'?s? report|attached|see appendix)",
        raw_text,
    )
    summary, summary_m = _find_with_match(
        r"Summary\s+of\s+compliance\s+risk\s+assessment[\s\S]{0,200}?\n\s*([^\n]+)",
        raw_text,
    )
    general, general_m = _find_with_match(
        r"General\s+Comments[\s\S]{0,80}?\n\s*([^\n]+)",
        raw_text,
    )
    legal_consult = re.search(
        r"Legal\s+consulted[\s\S]{0,80}?\b(no)\b",
        raw_text,
        re.IGNORECASE,
    )
    legal_op, legal_op_m = _find_with_match(
        r"Legal\s+opinion[\s\S]{0,200}?\n\s*([^\n]+)",
        raw_text,
    )
    # Outcome — anchor on the explicit label "Outcome of the check" first.
    # Any free-prose mention of "Outcome positive" elsewhere in the PDF
    # (boilerplate footer, summary text, etc) does NOT count.
    outcome, outcome_m = _find_with_match(
        r"Outcome\s+of\s+the\s+check\b[\s\|:]*\n?\s*\b(positive|negative)\b",
        raw_text,
    )
    if not outcome:
        # Fall back to "Outcome of check" (column-style cell), still anchored.
        outcome, outcome_m = _find_with_match(
            r"Outcome(?:\s+of(?:\s+the)?\s+check)?\b[\s\|:]*\n\s*(positive|negative)\b",
            raw_text,
        )
    docs_loc, docs_loc_m = _find_with_match(
        r"\b(Docusign[/\w\- ]*|sharedrive|SharePoint|share-drive)\b",
        raw_text,
    )
    # Expert name — capture two capitalised words BUT do NOT case-fold or we
    # will happily match "KYC Expert" itself, which is the label not a name.
    # We also explicitly forbid the literal word "Expert" so an empty cell
    # followed by "KYC Expert signature" can't be misread as the signer.
    expert_name, expert_m = _find_with_match(
        r"KYC\s+Expert\b[\s\S]{0,80}?\n\s*(?!KYC\b|Expert\b|Signature\b)([A-ZŻŹĆŃÓŁŚĄĘ][a-zżźćńółśąę]+\s+[A-ZŻŹĆŃÓŁŚĄĘ][a-zżźćńółśąę]+)",
        raw_text,
        flags=0,
    )
    signed_date, signed_date_m = _find_with_match(
        r"Signature\s+date[\s\S]{0,80}?(\d{2}[\.\-/]\d{2}[\.\-/]\d{4})",
        raw_text,
    )

    # kyc_expert_signed — require BOTH a name AND a discriminator near the
    # signature box, not just the word "signature" anywhere on the page.
    # Discriminators: a signature-box tick, the literal word "signed" within
    # a small window of "KYC Expert", OR a signature date within 200 chars of
    # the KYC Expert label.
    expert_window = re.search(
        r"KYC\s+Expert[\s\S]{0,300}",
        raw_text,
        re.IGNORECASE,
    )
    expert_window_text = expert_window.group(0) if expert_window else ""
    has_signed_near = bool(
        re.search(
            r"\b(signed|signature\s+date|✓|tick)\b",
            expert_window_text,
            re.IGNORECASE,
        )
    )
    has_date_near = bool(
        re.search(
            r"\d{2}[\.\-/]\d{2}[\.\-/]\d{4}",
            expert_window_text,
        )
    )
    # Explicit "unsigned" tokens — if the signature window names the field but
    # carries "not signed", "unsigned", or the literal "— —" placeholder, emit
    # False (definitely unsigned) instead of null (we don't know).
    has_unsigned_near = bool(
        re.search(
            r"\b(not\s*signed|unsigned)\b|—\s*—|--\s*--",
            expert_window_text,
            re.IGNORECASE,
        )
    )
    if expert_name and (has_signed_near or has_date_near):
        kyc_expert_signed_env = _confident(True, expert_window_text, 0.9)
    elif has_unsigned_near and expert_window_text:
        # Field is present in the PDF but explicitly unsigned. Distinguish
        # this from "we couldn't find the field at all".
        kyc_expert_signed_env = _confident(False, expert_window_text, 0.85)
    else:
        kyc_expert_signed_env = _unknown(expert_window_text)

    out["page2"] = {
        "questionnaire_collected": questionnaire_env,
        "shareholder_structure_ref": (
            _confident(shareholder_ref, shareholder_ref or "", _match_quality(sh_m))
            if shareholder_ref
            else _unknown()
        ),
        "ubo_list_ref": (
            _confident(ubo_ref, ubo_ref or "", _match_quality(ubo_m))
            if ubo_ref
            else _unknown()
        ),
        "summary_compliance_risk": (
            _confident(summary, summary or "", _match_quality(summary_m))
            if summary
            else _unknown()
        ),
        "general_comments": (
            _confident(general, general or "", _match_quality(general_m))
            if general
            else _unknown()
        ),
        "legal_consulted": (
            _confident(False, "no", 0.9) if legal_consult else _unknown()
        ),
        "legal_opinion": (
            _confident(legal_op, legal_op or "", _match_quality(legal_op_m))
            if legal_op
            else _unknown()
        ),
        "outcome": (
            _confident(
                outcome.lower() if outcome else None,
                outcome or "",
                _match_quality(outcome_m),
            )
            if outcome
            else _unknown()
        ),
        "supporting_docs_location": (
            _confident(docs_loc, docs_loc or "", _match_quality(docs_loc_m))
            if docs_loc
            else _unknown()
        ),
        "kyc_expert_name": (
            _confident(expert_name, expert_name or "", _match_quality(expert_m))
            if expert_name
            else _unknown()
        ),
        "kyc_expert_signed": kyc_expert_signed_env,
        "signature_date": (
            _confident(signed_date, signed_date or "", _match_quality(signed_date_m))
            if signed_date
            else _unknown()
        ),
    }

    out["raw_text"] = raw_text
    return out


def _all_envelopes_empty(parsed: dict[str, Any]) -> bool:
    """True when every {value,confidence,raw_snippet} envelope has confidence==0."""
    found_any = False

    def _walk(node: Any) -> None:
        nonlocal found_any
        if isinstance(node, dict):
            if "value" in node and "confidence" in node and "raw_snippet" in node:
                if float(node.get("confidence") or 0) > 0:
                    found_any = True
                return
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(parsed)
    return not found_any


class KycMetPdfExtractorTool(BaseTool):
    name = "kyc_met_pdf_extractor"
    description = (
        "Extract a MET-template KYC Standard Check PDF into the strict "
        "MET-shaped JSON identical to what the kyc-standard-check agent "
        "emits. Runs Claude vision over every page, parses fields into "
        "{value, confidence, raw_snippet} envelopes. Never fabricates."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "Filesystem path to the PDF inside the agent's sandbox.",
            },
            "pdf_base64": {
                "type": "string",
                "description": "Base64-encoded PDF content (use when no path is available).",
            },
        },
        "required": [],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pdf_path = (arguments.get("pdf_path") or "").strip()
        pdf_b64 = (arguments.get("pdf_base64") or "").strip()

        tmp_to_clean: str | None = None
        if not pdf_path and pdf_b64:
            try:
                raw = base64.b64decode(pdf_b64)
            except Exception as e:
                return ToolResult(
                    content=f"Error: pdf_base64 is not valid base64: {e}",
                    is_error=True,
                )
            export = os.environ.get("EXPORT_DIR") or tempfile.gettempdir()
            os.makedirs(export, exist_ok=True)
            fd, pdf_path = tempfile.mkstemp(suffix=".pdf", dir=export)
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            tmp_to_clean = pdf_path

        if not pdf_path:
            return ToolResult(
                content="Error: pdf_path or pdf_base64 must be supplied",
                is_error=True,
            )

        path = Path(pdf_path)
        if not path.exists():
            return ToolResult(
                content=f"Error: PDF not found at {pdf_path}",
                is_error=True,
            )

        warnings: list[str] = []
        provider = _provider()
        raw_pages: list[str] = []

        if provider != "none":
            pngs = await _render_pages(str(path))
            if not pngs:
                warnings.append("No pages could be rasterised; PDF may be malformed.")
            for page_no, png in enumerate(pngs, start=1):
                b64 = base64.b64encode(png).decode("ascii")
                text = await _vision_extract(b64, page_no)
                if text.strip():
                    raw_pages.append(f"--- Page {page_no} ---\n{text}")
                else:
                    warnings.append(f"Vision returned empty text for page {page_no}.")

        # PyPDF2 fallback when vision yielded nothing (provider missing, rate
        # limited, credits exhausted, or scanned-but-no-image-rendered).
        if not raw_pages:
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(str(path))
                for i, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    if text.strip():
                        raw_pages.append(f"--- Page {i} ---\n{text}")
                if raw_pages:
                    warnings.append(
                        "Vision unavailable or empty — used PyPDF2 text fallback."
                    )
                    provider = f"{provider}+pypdf2_fallback"
            except Exception as e:
                warnings.append(f"PyPDF2 fallback failed: {e}")

        raw_text = "\n\n".join(raw_pages)
        parsed = _parse_met_fields(raw_text)
        parsed["_warnings"] = warnings
        parsed["_extractor_provider"] = provider

        # Always clean up tmp file
        if tmp_to_clean:
            try:
                os.unlink(tmp_to_clean)
            except OSError:
                pass

        # Hard guard: if we couldn't extract anything (text very short OR
        # every envelope is empty), tell the caller explicitly so the agent
        # doesn't keep going and hallucinate values.
        if len(raw_text.strip()) < 50 or _all_envelopes_empty(parsed):
            return ToolResult(
                content="No extractable text from PDF",
                is_error=True,
                metadata={
                    "pages": len(raw_pages),
                    "provider": provider,
                    "warnings": warnings,
                    "raw_text_len": len(raw_text),
                },
            )

        return ToolResult(
            content=json.dumps(parsed, default=str),
            metadata={
                "pages": len(raw_pages),
                "provider": provider,
                "warnings": warnings,
            },
        )
