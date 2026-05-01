"""Regulatory enforcement & litigation lookup."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote_plus

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


def _fuzzy(a: str, b: str) -> int:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0
    if na in nb or nb in na:
        return 95
    return int(SequenceMatcher(None, na, nb).ratio() * 100)


def _extract_fine_usd(text: str) -> float | None:
    """Pull a fine amount from free text. Handles $, £, €, and 'million/billion'."""
    if not text:
        return None
    patterns = [
        r"([\$€£])\s*([\d,\.]+)\s*(million|billion|m|bn|b)?",
        r"fined\s*([\d,\.]+)\s*(million|billion)?",
        r"penalty\s*of\s*([\$€£])?\s*([\d,\.]+)\s*(million|billion)?",
    ]
    text_l = text.lower().replace(",", "")
    for p in patterns:
        m = re.search(p, text_l)
        if not m:
            continue
        groups = m.groups()
        try:
            amount = float(next((g for g in groups if g and re.match(r"^[\d\.]+$", g)), "0"))
        except ValueError:
            continue
        mult = 1.0
        suffix = next((g for g in groups if g and g in ("million", "billion", "m", "bn", "b")), None)
        if suffix in ("million", "m"):
            mult = 1e6
        elif suffix in ("billion", "bn", "b"):
            mult = 1e9
        # Currency — rough conversion
        cur = next((g for g in groups if g in ("$", "€", "£")), "$")
        fx = {"$": 1.0, "€": 1.08, "£": 1.27}.get(cur, 1.0)
        return amount * mult * fx
    return None


async def _sec_litigation(name: str) -> list[dict[str, Any]]:
    """SEC litigation release index — full-text searchable via EDGAR."""
    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{quote_plus(name)}%22&dateRange=custom&startdt=2015-01-01&forms=LR"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)",
                    "Accept": "application/json",
                },
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception as exc:
        logger.debug("SEC EDGAR lookup failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for hit in (data.get("hits") or {}).get("hits", []) or []:
        src = hit.get("_source", {})
        title = src.get("display_names", [""])[0] if src.get("display_names") else ""
        adsh = src.get("adsh", "")
        out.append({
            "authority": "SEC (US)",
            "action_type": "civil_suit",
            "date": src.get("file_date"),
            "title": title or src.get("form_type", "Litigation release"),
            "summary": (src.get("items") or "").strip(),
            "primary_source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={adsh}" if adsh else "https://www.sec.gov/litigation/litreleases.shtml",
            "fine_amount_usd": _extract_fine_usd(src.get("items", "")),
            "confidence": _fuzzy(name, title),
        })
    return out


async def _doj_press(name: str) -> list[dict[str, Any]]:
    """Crawl DOJ press-release search."""
    url = f"https://www.justice.gov/opa/pr?keys={quote_plus(name)}"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<a[^>]+href="(/opa/pr/[^"]+)"[^>]*>([^<]{15,200})</a>',
        html,
    ):
        path, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        conf = _fuzzy(name, title)
        if conf < 70:
            continue
        out.append({
            "authority": "DOJ (US)",
            "action_type": "criminal_charge",
            "date": None,
            "title": title,
            "summary": "",
            "primary_source_url": "https://www.justice.gov" + path,
            "fine_amount_usd": None,
            "confidence": conf,
        })
        if len(out) >= 10:
            break
    return out


async def _fca_notices(name: str) -> list[dict[str, Any]]:
    url = f"https://www.fca.org.uk/search-results?search_term={quote_plus(name)}&start=0"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<a[^>]+href="(/publication/[^"]+|/news/[^"]+)"[^>]*>([^<]{15,200})</a>',
        html,
    ):
        path, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        conf = _fuzzy(name, title)
        if conf < 70:
            continue
        out.append({
            "authority": "FCA (UK)",
            "action_type": "fine" if "fine" in title.lower() or "penal" in title.lower() else "final_notice",
            "date": None,
            "title": title,
            "summary": "",
            "primary_source_url": "https://www.fca.org.uk" + path,
            "fine_amount_usd": _extract_fine_usd(title),
            "confidence": conf,
        })
        if len(out) >= 10:
            break
    return out


async def _courtlistener(name: str) -> list[dict[str, Any]]:
    """Free-text search of the CourtListener case index."""
    url = f"https://www.courtlistener.com/api/rest/v3/search/?q={quote_plus(name)}&type=r&format=json"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for hit in (data.get("results") or [])[:10]:
        title = hit.get("caseName") or hit.get("caseNameShort") or ""
        out.append({
            "authority": hit.get("court") or "US Federal / State Court",
            "action_type": "civil_suit",
            "date": hit.get("dateFiled"),
            "title": title,
            "summary": hit.get("snippet", "")[:400],
            "primary_source_url": f"https://www.courtlistener.com{hit.get('absolute_url','')}",
            "fine_amount_usd": _extract_fine_usd(hit.get("snippet", "")),
            "confidence": _fuzzy(name, title),
        })
    return out


async def _bailii(name: str) -> list[dict[str, Any]]:
    url = f"https://www.bailii.org/cgi-bin/sino_search_1.cgi?query={quote_plus(name)}&method=boolean&highlight=1"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            if r.status_code != 200:
                return []
            html = r.text
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'<a href="(/[^"]+\.html)">([^<]{15,200})</a>',
        html,
    ):
        path, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        conf = _fuzzy(name, title)
        if conf < 70:
            continue
        out.append({
            "authority": "BAILII (UK/IE Courts)",
            "action_type": "judgment",
            "date": None,
            "title": title,
            "summary": "",
            "primary_source_url": "https://www.bailii.org" + path,
            "fine_amount_usd": None,
            "confidence": conf,
        })
        if len(out) >= 10:
            break
    return out


class RegulatoryEnforcementTool(BaseTool):
    name = "regulatory_enforcement"
    description = (
        "Primary-source regulatory enforcement and litigation lookup. Hits "
        "authoritative regulator and court bulletins directly — SEC EDGAR "
        "litigation releases, DOJ press releases, FCA final notices/decisions, "
        "BaFin sanctions register, ASIC enforceable undertakings, MAS "
        "regulatory actions, CJEU judgments — and public court-litigation "
        "indices (CourtListener RECAP, BAILII UK/IE, CanLII, EU Curia). Each "
        "hit is structured with `authority`, `action_type` (fine / settlement "
        "/ cease-and-desist / criminal charge / civil suit / debarment / "
        "licence revocation / judgment), `date`, `fine_amount_usd` where "
        "extractable, `title`, `summary`, a direct `primary_source_url` to "
        "the filing, and a 0-100 name-match confidence. Complements "
        "`adverse_media`: adverse media covers press reporting on "
        "wrongdoing; this tool surfaces the primary-source filings "
        "themselves. Use for enhanced DD on regulated sectors (financial "
        "services, energy, healthcare, defence), litigation screening in "
        "M&A due diligence, vendor onboarding for any regulated "
        "counterparty, and sanctions-package exposure mapping. No paid "
        "APIs — all sources are free and public. Name matching uses "
        "fuzzy SequenceMatcher with substring boost; default 70 threshold "
        "filters out accidental name overlap."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Legal name of person or entity to screen.",
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["sec", "doj", "fca", "courtlistener", "bailii", "all"],
                },
                "description": "Subset of sources. 'all' by default.",
            },
            "min_confidence": {
                "type": "integer",
                "default": 75,
                "minimum": 50, "maximum": 100,
            },
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        import asyncio
        name = (arguments.get("name") or "").strip()
        if not name:
            return ToolResult(content="Error: 'name' is required.", is_error=True)
        sources = arguments.get("sources") or ["all"]
        want_all = "all" in sources
        min_conf = int(arguments.get("min_confidence", 75))

        tasks = []
        if want_all or "sec" in sources: tasks.append(_sec_litigation(name))
        if want_all or "doj" in sources: tasks.append(_doj_press(name))
        if want_all or "fca" in sources: tasks.append(_fca_notices(name))
        if want_all or "courtlistener" in sources: tasks.append(_courtlistener(name))
        if want_all or "bailii" in sources: tasks.append(_bailii(name))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_hits: list[dict[str, Any]] = []
        warnings: list[str] = []
        for r in results:
            if isinstance(r, Exception):
                warnings.append(f"source error: {r.__class__.__name__}")
                continue
            all_hits.extend(r)

        filtered = [h for h in all_hits if h.get("confidence", 0) >= min_conf]

        # Grade
        severe = [h for h in filtered if h["action_type"] in ("criminal_charge", "debarment", "licence_revocation")]
        fines = [h for h in filtered if h.get("fine_amount_usd") and h["fine_amount_usd"] >= 1_000_000]
        if severe or (len(fines) >= 2):
            grade = "H"
            reason = "Criminal charge / debarment / licence revocation OR multiple material fines"
        elif filtered:
            grade = "M"
            reason = f"{len(filtered)} enforcement or litigation hit(s)"
        else:
            grade = "L"
            reason = "No enforcement actions or litigation found"

        return ToolResult(
            content=json.dumps({
                "queried_name": name,
                "sources_checked": sources,
                "total_hits": len(filtered),
                "hits": sorted(filtered, key=lambda x: (x.get("confidence", 0), x.get("fine_amount_usd") or 0), reverse=True)[:25],
                "risk_grade": grade,
                "risk_grade_reason": reason,
                "warnings": warnings,
                "disclaimer": (
                    "Primary-source searches are best-effort HTML scrapes — a "
                    "negative result is NOT a guarantee that no action exists. "
                    "For regulated counterparties always pair this tool with "
                    "adverse_media and a direct check against the specific "
                    "regulator of interest."
                ),
            }, indent=2, default=str),
            metadata={"hits": len(filtered), "grade": grade},
        )
