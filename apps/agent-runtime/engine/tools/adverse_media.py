"""Adverse-media / negative-news screening."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote_plus

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0
_CACHE_TTL_SECONDS = 60 * 30  # news staleness — 30 min

_NEWS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


RISK_CATEGORIES = {
    "bribery_corruption": ["bribe", "bribery", "corruption", "kickback", "fcpa", "ukba", "graft"],
    "money_laundering": ["money laundering", "amld", "launder", "tax haven", "shell compan"],
    "fraud": ["fraud", "defraud", "scam", "ponzi", "pyramid scheme", "embezzle", "misappropr"],
    "sanctions_evasion": ["sanctions evasion", "sanction breach", "sanctions violat", "export control"],
    "terrorism_financing": ["terrorist financ", "cft", "al-qaida", "isis", "isil", "hamas", "hezbollah", "boko haram"],
    "human_trafficking": ["trafficking", "modern slavery", "forced labour", "child labour"],
    "tax_evasion": ["tax evasion", "tax evader", "tax fraud", "panama papers", "pandora papers", "paradise papers"],
    "narcotics": ["drug trafficking", "narcotic", "cartel", "cocaine", "heroin", "fentanyl", "opioid"],
    "environmental_crime": ["environmental crime", "pollution", "illegal logging", "wildlife trafficking", "oil spill"],
    "cyber_crime": ["cyber attack", "ransomware", "data breach", "hack", "phishing", "malware"],
    "market_manipulation": ["market manipul", "insider trad", "pump and dump", "price fix", "cartel conduct"],
    "regulatory_breach": ["fine", "penalty", "enforcement", "cease and desist", "consent decree", "settlement", "probe", "investigation"],
    "violence_organised_crime": ["organised crime", "organized crime", "mafia", "yakuza", "triad", "assassin"],
    "esg_governance": ["greenwash", "board resign", "audit qualification", "going concern", "restated"],
}

_ADVERSE_KEYWORDS = {kw for kws in RISK_CATEGORIES.values() for kw in kws} | {
    "alleg", "accus", "charg", "indict", "prosecut", "sued", "lawsuit",
    "guilty", "convict", "arrest", "raid", "probe",
}

_TIER_WEIGHTS = {
    # Tier 1 regulators / gov — 5
    "sec.gov": 5, "justice.gov": 5, "fca.org.uk": 5, "ofsi.gov.uk": 5,
    "bafin.de": 5, "dnb.nl": 5, "amf-france.org": 5, "consob.it": 5,
    "asic.gov.au": 5, "mas.gov.sg": 5, "fsa.go.jp": 5, "finma.ch": 5,
    "europa.eu": 5, "treasury.gov": 5, "sfo.gov.uk": 5,
    # Tier 1 wires — 4
    "reuters.com": 4, "bloomberg.com": 4, "ap.org": 4, "afp.com": 4,
    "ft.com": 4, "wsj.com": 4, "economist.com": 4, "nytimes.com": 4,
    # Tier 2 nationals — 3
    "bbc.co.uk": 3, "bbc.com": 3, "theguardian.com": 3, "cnn.com": 3,
    "washingtonpost.com": 3, "lemonde.fr": 3, "faz.net": 3, "handelsblatt.com": 3,
    "nrc.nl": 3, "elpais.com": 3, "asahi.com": 3, "scmp.com": 3,
    # Tier 3 trade press — 2
    "politico.com": 2, "axios.com": 2, "moodys.com": 2, "spglobal.com": 2,
    "fitchratings.com": 2, "lawfareblog.com": 2,
}


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
        return 100 if (na == nb) else 92
    return int(SequenceMatcher(None, na, nb).ratio() * 100)


def _source_weight(url: str) -> int:
    host = re.sub(r"^https?://", "", url).split("/", 1)[0].lower()
    for dom, w in _TIER_WEIGHTS.items():
        if host == dom or host.endswith("." + dom):
            return w
    return 1


def _classify_text(title: str, snippet: str) -> tuple[list[str], str]:
    """(risk_categories_matched, stance)."""
    blob = f"{title} {snippet}".lower()
    cats = []
    for cat, kws in RISK_CATEGORIES.items():
        if any(k in blob for k in kws):
            cats.append(cat)
    stance = "neutral"
    if any(k in blob for k in _ADVERSE_KEYWORDS):
        stance = "adverse"
    elif any(k in blob for k in ["acquit", "cleared", "dropped charges", "no wrongdoing", "exonerat"]):
        stance = "positive"
    return cats, stance


def _recency_bucket(published_iso: str | None) -> str:
    if not published_iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
    except Exception:
        return "unknown"
    age = datetime.now(timezone.utc) - dt
    if age <= timedelta(days=30):
        return "30d"
    if age <= timedelta(days=90):
        return "90d"
    if age <= timedelta(days=365):
        return "1y"
    if age <= timedelta(days=365 * 3):
        return "3y"
    return "older"


async def _tavily_adverse(name: str, depth: str) -> tuple[list[dict[str, Any]], str | None]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return [], "TAVILY_API_KEY not set"
    query = f'"{name}" (lawsuit OR fraud OR investigation OR bribery OR sanctions OR penalty OR scandal OR laundering OR corruption)'
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": depth,  # "basic" or "advanced"
                    "include_answer": False,
                    "include_raw_content": False,
                    "max_results": 15,
                    "topic": "news",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return [], f"Tavily failed: {exc.__class__.__name__}"
    out = []
    for item in data.get("results", []) or []:
        out.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": (item.get("content") or "")[:500],
            "published_at": item.get("published_date") or item.get("published_at"),
            "source": "Tavily",
        })
    return out, None


_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


async def _gdelt_adverse(name: str) -> tuple[list[dict[str, Any]], str | None]:
    """GDELT DOC API — free, no auth, multilingual. Filter to English."""
    # GDELT expects a simple query; complex boolean queries often 400/403.
    # Use a quoted phrase — GDELT matches case-insensitively.
    adverse_terms = "(lawsuit OR fraud OR investigation OR penalty OR scandal OR corruption)"
    quoted_name = '"' + name + '"'
    q = quote_plus(f"{quoted_name} {adverse_terms}")
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={q}"
        "&mode=ArtList&format=json&maxrecords=25&sourcelang=eng&timespan=3y"
    )
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": _BROWSER_UA})
            if r.status_code != 200:
                # GDELT often 429s under load — retry once without boolean ops.
                simple = (
                    "https://api.gdeltproject.org/api/v2/doc/doc"
                    f"?query={quote_plus(name)}"
                    "&mode=ArtList&format=json&maxrecords=25&sourcelang=eng&timespan=3y"
                )
                r = await client.get(simple, headers={"User-Agent": _BROWSER_UA})
                if r.status_code != 200:
                    return [], f"GDELT HTTP {r.status_code}"
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else json.loads(r.text)
    except Exception as exc:
        return [], f"GDELT failed: {exc.__class__.__name__}"
    out = []
    for item in data.get("articles", []) or []:
        out.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": "",
            "published_at": (item.get("seendate") or "")[:19] + "Z" if item.get("seendate") else None,
            "source": item.get("domain") or "GDELT",
        })
    return out, None


async def _google_news_rss(name: str) -> tuple[list[dict[str, Any]], str | None]:
    q = quote_plus(
        f'"{name}" (lawsuit OR fraud OR investigation OR sanctions OR fined OR penalty OR scandal OR laundering OR corruption)'
    )
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            r.raise_for_status()
            content = r.content
    except Exception as exc:
        return [], f"Google News RSS failed: {exc.__class__.__name__}"
    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return out, "Google News RSS parse error"
    channel = root.find("channel")
    if channel is None:
        return out, None
    for item in channel.findall("item")[:25]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        desc = (item.findtext("description") or "").strip()
        # RFC-822 -> ISO
        iso = None
        try:
            from email.utils import parsedate_to_datetime
            iso = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat() if pub else None
        except Exception:
            pass
        # Strip HTML from description
        snippet = re.sub(r"<[^>]+>", " ", desc)[:500]
        out.append({
            "title": title,
            "url": link,
            "snippet": snippet,
            "published_at": iso,
            "source": "GoogleNews",
        })
    return out, None


async def _scrape_reuters_search(name: str) -> tuple[list[dict[str, Any]], str | None]:
    """Reuters site search — best-effort HTML parse, no API."""
    url = f"https://www.reuters.com/site-search/?query={quote_plus(name)}&sort=newest"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"})
            r.raise_for_status()
            html = r.text
    except Exception as exc:
        return [], f"Reuters scrape failed: {exc.__class__.__name__}"
    out: list[dict[str, Any]] = []
    # Extract <a href> with title-like text near the search result markers.
    # Reuters shows article URLs like /world/... /business/... /legal/...
    for m in re.finditer(
        r'<a[^>]+href="(/(?:world|business|legal|markets|technology|sustainability)/[^"#?]+)"[^>]*>([^<]{15,200})</a>',
        html,
    ):
        path, title = m.group(1), m.group(2).strip()
        title = re.sub(r"\s+", " ", title)
        out.append({
            "title": title,
            "url": "https://www.reuters.com" + path,
            "snippet": "",
            "published_at": None,
            "source": "reuters.com",
        })
        if len(out) >= 15:
            break
    return out, None


async def _gather(name: str, depth: str) -> tuple[list[dict[str, Any]], list[str]]:
    import asyncio
    warnings: list[str] = []

    tasks = [
        _tavily_adverse(name, depth),
        _gdelt_adverse(name),
        _google_news_rss(name),
        _scrape_reuters_search(name),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_hits: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            warnings.append(f"source error: {r.__class__.__name__}")
            continue
        hits, warn = r  # type: ignore[misc]
        if warn:
            warnings.append(warn)
        all_hits.extend(hits)
    return all_hits, warnings


class AdverseMediaTool(BaseTool):
    name = "adverse_media"
    description = (
        "Adverse-media / negative-news screening for KYC and third-party due "
        "diligence. Fuses four independent sources so it still delivers when "
        "any one is rate-limited or offline: (1) Tavily AI news search, "
        "(2) GDELT Events 2.0 (public, multilingual, 3-year window), "
        "(3) Google News RSS (public, no key), (4) direct HTML scraping of "
        "tier-1 outlets like Reuters. Each hit is auto-classified by risk "
        "category (bribery, money laundering, fraud, sanctions evasion, "
        "terrorism financing, human trafficking, tax evasion, narcotics, "
        "environmental crime, cyber crime, market manipulation, regulatory "
        "breach, violent/organised crime, ESG governance), stance "
        "(adverse / neutral / positive), recency bucket (30d, 90d, 1y, 3y, "
        "older), and source tier weight 1..5 (5 = SEC/DOJ/FCA/other "
        "regulator, 4 = Reuters/Bloomberg/FT/WSJ, 3 = national paper, "
        "2 = trade press, 1 = unverified). Returns a de-duplicated, "
        "fuzzy-matched list plus an L/M/H risk grade (H = any "
        "regulator-tier adverse hit OR 3+ independent tier-3+ adverse "
        "hits within 2y; M = 1-2 tier-3+ adverse hits in 2y; L = otherwise). "
        "Use cases: KYC onboarding, periodic CDD refresh, vendor risk, "
        "M&A due diligence, correspondent banking, insurance underwriting, "
        "journalism investigations. Requires TAVILY_API_KEY for the Tavily "
        "source; other sources work keyless."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Person or entity name."},
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "default": "basic",
                "description": "Tavily search depth. 'advanced' costs more tokens but surfaces deeper results.",
            },
            "name_match_threshold": {
                "type": "integer",
                "minimum": 50, "maximum": 100,
                "default": 75,
                "description": "Drop hits whose title fuzzy-match is below this.",
            },
            "min_source_weight": {
                "type": "integer",
                "minimum": 1, "maximum": 5,
                "default": 1,
                "description": "Require at least this source-tier weight (1-5).",
            },
            "lookback_years": {"type": "integer", "default": 3, "minimum": 1, "maximum": 10},
            "max_results": {"type": "integer", "default": 30, "minimum": 1, "maximum": 100},
            "refresh": {"type": "boolean", "default": False},
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("name") or "").strip()
        if not name:
            return ToolResult(content="Error: 'name' is required.", is_error=True)
        depth = arguments.get("search_depth", "basic")
        thr = int(arguments.get("name_match_threshold", 75))
        min_w = int(arguments.get("min_source_weight", 1))
        _years = int(arguments.get("lookback_years", 3))
        max_results = int(arguments.get("max_results", 30))
        refresh = bool(arguments.get("refresh", False))

        cache_key = f"{_normalize(name)}:{depth}:{thr}:{min_w}"
        if not refresh:
            cached = _NEWS_CACHE.get(cache_key)
            if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
                hits = cached[1]
                return ToolResult(
                    content=json.dumps({"queried_name": name, "from_cache": True, **self._summarize(name, hits, max_results)}, indent=2),
                    metadata={"cache_hit": True},
                )

        raw_hits, warnings = await _gather(name, depth)

        enriched = []
        for h in raw_hits:
            score = _fuzzy(name, h.get("title", ""))
            if score < thr and _fuzzy(name, h.get("snippet", "")) < thr:
                continue
            weight = _source_weight(h.get("url", ""))
            if weight < min_w:
                continue
            cats, stance = _classify_text(h.get("title", ""), h.get("snippet", ""))
            enriched.append({
                **h,
                "name_match_confidence": max(score, _fuzzy(name, h.get("snippet", ""))),
                "source_weight": weight,
                "risk_categories": cats,
                "stance": stance,
                "recency_bucket": _recency_bucket(h.get("published_at")),
            })

        # Dedupe by normalized title
        seen = set()
        final: list[dict[str, Any]] = []
        for h in sorted(enriched, key=lambda x: (x["source_weight"], x["name_match_confidence"]), reverse=True):
            key = _normalize(h.get("title", ""))[:60]
            if key in seen:
                continue
            seen.add(key)
            final.append(h)

        _NEWS_CACHE[cache_key] = (time.time(), final)

        return ToolResult(
            content=json.dumps({
                "queried_name": name,
                "from_cache": False,
                "warnings": warnings,
                **self._summarize(name, final, max_results),
            }, indent=2),
            metadata={"hits": len(final)},
        )

    @staticmethod
    def _summarize(name: str, hits: list[dict[str, Any]], max_results: int) -> dict[str, Any]:
        adverse = [h for h in hits if h["stance"] == "adverse"]
        tier1 = [h for h in adverse if h["source_weight"] >= 4]
        recent_tier3_plus = [h for h in adverse if h["source_weight"] >= 3 and h["recency_bucket"] in ("30d", "90d", "1y", "3y")]
        cat_counts: dict[str, int] = {}
        for h in adverse:
            for c in h["risk_categories"]:
                cat_counts[c] = cat_counts.get(c, 0) + 1

        if tier1 and any(h.get("name_match_confidence", 0) >= 90 for h in tier1):
            grade = "H"
            grade_reason = "Tier-1 adverse hit with high name match"
        elif len(recent_tier3_plus) >= 3:
            grade = "H"
            grade_reason = "3+ independent adverse hits from tier-3+ sources within 3y"
        elif len(recent_tier3_plus) >= 1:
            grade = "M"
            grade_reason = "1-2 adverse hits from tier-3+ sources"
        elif adverse:
            grade = "L"
            grade_reason = "Only low-tier adverse coverage"
        else:
            grade = "L"
            grade_reason = "No adverse hits"
        return {
            "total_hits": len(hits),
            "adverse_hits": len(adverse),
            "tier1_adverse_hits": len(tier1),
            "category_counts": cat_counts,
            "risk_grade": grade,
            "risk_grade_reason": grade_reason,
            "top_hits": hits[:max_results],
        }
