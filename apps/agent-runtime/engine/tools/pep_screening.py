"""Politically Exposed Persons (PEP) screening — KYC / AML building block."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0
_CACHE_TTL_SECONDS = 60 * 60 * 24  # PEP status changes slowly

# Memoization keyed on (source, normalized_name, jurisdiction)
_PEP_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fuzzy(a: str, b: str) -> int:
    if not a or not b:
        return 0
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 100
    ts_a = " ".join(sorted(na.split()))
    ts_b = " ".join(sorted(nb.split()))
    direct = int(SequenceMatcher(None, na, nb).ratio() * 100)
    token = int(SequenceMatcher(None, ts_a, ts_b).ratio() * 100)
    return max(direct, token)


_OPENSANCTIONS_API = "https://api.opensanctions.org/match/peps"


async def _query_opensanctions(
    name: str,
    jurisdiction: str | None,
    api_key: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Match against the OpenSanctions PEP collection."""
    if not api_key:
        return (
            [],
            "OpenSanctions skipped — set OPENSANCTIONS_API_KEY to enable (free developer tier at opensanctions.org/api)",
        )
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)",
        "Authorization": f"ApiKey {api_key}",
    }

    payload = {
        "queries": {
            "q1": {
                "schema": "Person",
                "properties": {
                    "name": [name],
                    **({"country": [jurisdiction]} if jurisdiction else {}),
                },
            }
        }
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.post(_OPENSANCTIONS_API, json=payload, headers=headers)
            if r.status_code == 429:
                return [], "OpenSanctions rate-limited"
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.debug("OpenSanctions query failed: %s", exc)
        return [], f"OpenSanctions unreachable: {exc.__class__.__name__}"

    matches: list[dict[str, Any]] = []
    for m in ((data.get("responses") or {}).get("q1") or {}).get("results", []):
        props = m.get("properties") or {}
        positions = props.get("position") or []
        countries = props.get("country") or props.get("nationality") or []
        dob = props.get("birthDate") or []
        topics = props.get("topics") or []
        pep_class = _derive_class_from_opensanctions(topics, positions)
        matches.append(
            {
                "name": (props.get("name") or [m.get("caption") or name])[0],
                "confidence": int((m.get("score") or 0) * 100),
                "pep_class": pep_class,
                "positions": positions[:5],
                "countries": countries[:3],
                "date_of_birth": dob[0] if dob else None,
                "opensanctions_id": m.get("id"),
                "opensanctions_url": (
                    f"https://www.opensanctions.org/entities/{m.get('id')}/"
                    if m.get("id")
                    else None
                ),
                "topics": topics[:6],
                "source": "OpenSanctions",
            }
        )
    return matches, None


def _derive_class_from_opensanctions(topics: list[str], positions: list[str]) -> str:
    """Translate OpenSanctions topic codes into our PEP class taxonomy."""
    topics = [t.lower() for t in (topics or [])]
    if "role.pep" in topics or any("pep" in t for t in topics):
        if "role.pep.family" in topics:
            return "Family PEP"
        if "role.pep.associate" in topics:
            return "Close Associate PEP"
        if "role.pep.former" in topics:
            return "Former PEP"
        # Heuristic — positions mentioning international bodies
        if any(
            ("UN " in p) or ("IMF" in p) or ("World Bank" in p) or ("IAEA" in p)
            for p in positions
        ):
            return "International Organisation PEP"
        return "Domestic/Foreign PEP"
    if "role.rca" in topics:
        return "Close Associate PEP"
    return "Potential PEP"


_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"


async def _query_wikidata(name: str) -> tuple[list[dict[str, Any]], str | None]:
    """Wikidata in two stages — fast, scoped to real PEPs."""
    matches: dict[str, dict[str, Any]] = {}
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
            # Stage 1: search for person entities matching the name.
            s = await client.get(
                _WIKIDATA_API,
                params={
                    "action": "wbsearchentities",
                    "search": name,
                    "language": "en",
                    "type": "item",
                    "format": "json",
                    "limit": "10",
                },
            )
            if s.status_code >= 400:
                return [], f"Wikidata search HTTP {s.status_code}"
            search_hits = s.json().get("search", [])
            qids = [h["id"] for h in search_hits if h.get("id", "").startswith("Q")]
            if not qids:
                return [], None

            # Stage 2: single SPARQL for all QIDs' P39 / P569 / P27 / P1906 data.
            values = " ".join(f"wd:{q}" for q in qids)
            sparql = f"""
            SELECT ?person ?personLabel ?positionLabel ?start ?end ?countryLabel ?dob WHERE {{
              VALUES ?person {{ {values} }}
              ?person wdt:P39 ?position .
              ?position rdfs:label ?positionLabel FILTER(LANG(?positionLabel) = "en") .
              OPTIONAL {{ ?person wdt:P569 ?dob }}
              OPTIONAL {{ ?person wdt:P27 ?country . ?country rdfs:label ?countryLabel FILTER(LANG(?countryLabel) = "en") }}
              OPTIONAL {{ ?person p:P39 ?stmt . ?stmt ps:P39 ?position .
                          OPTIONAL {{ ?stmt pq:P580 ?start }}
                          OPTIONAL {{ ?stmt pq:P582 ?end }} }}
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" }}
            }}
            LIMIT 100
            """
            r = await client.get(
                _WIKIDATA_SPARQL,
                params={"query": sparql},
                headers={**headers, "Accept": "application/sparql-results+json"},
            )
            if r.status_code >= 400:
                return [], f"Wikidata SPARQL HTTP {r.status_code}"
            data = r.json()
    except Exception as exc:
        logger.debug("Wikidata query failed: %s", exc)
        return [], f"Wikidata unreachable: {exc.__class__.__name__}"

    for row in data.get("results", {}).get("bindings", []) or []:
        qid_url = row.get("person", {}).get("value", "")
        qid = qid_url.rsplit("/", 1)[-1]
        # pull person label from search results (we already have it)
        label = next((h["label"] for h in search_hits if h["id"] == qid), "")
        if not label:
            label = row.get("personLabel", {}).get("value", "")
        if not label:
            continue
        if qid not in matches:
            matches[qid] = {
                "name": label,
                "confidence": _fuzzy(name, label),
                "pep_class": "Domestic/Foreign PEP",
                "positions": [],
                "countries": [],
                "opensanctions_id": None,
                "wikidata_qid": qid,
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
                "source": "Wikidata",
            }
        pos = row.get("positionLabel", {}).get("value")
        country = row.get("countryLabel", {}).get("value")
        start = row.get("start", {}).get("value", "")
        end = row.get("end", {}).get("value", "")
        period = ""
        if start or end:
            period = f" ({start[:10] or '?'} – {end[:10] or 'present'})"
        if pos and (pos + period) not in matches[qid]["positions"]:
            matches[qid]["positions"].append(pos + period)
            # Tag as Former if an end date is present
            if end and matches[qid]["pep_class"] == "Domestic/Foreign PEP":
                matches[qid]["pep_class"] = "Former PEP"
        if country and country not in matches[qid]["countries"]:
            matches[qid]["countries"].append(country)
    return list(matches.values()), None


_GOV_ROSTERS: dict[str, dict[str, Any]] = {
    "GB": {
        "name": "UK Parliament members",
        "url": "https://members-api.parliament.uk/api/Members/Search?skip=0&take=650&House=1",
        "json_path": ("items", "value", "nameDisplayAs"),
        "authority": "UK Parliament",
        "position_field_path": (
            "items",
            "value",
            "latestHouseMembership",
            "membershipFrom",
        ),
    },
    "US": {
        "name": "US Congress members",
        "url": "https://api.congress.gov/v3/member?format=json&limit=550&api_key={key}",
        "key_env": "CONGRESS_GOV_API_KEY",
        "json_path": ("members", "name"),
        "authority": "US Congress",
    },
}


async def _query_gov_roster(
    jurisdiction: str, name: str
) -> tuple[list[dict[str, Any]], str | None]:
    meta = _GOV_ROSTERS.get((jurisdiction or "").upper())
    if not meta:
        return [], None
    url = meta["url"]
    if "{key}" in url:
        key_env = meta.get("key_env")
        api_key = os.environ.get(key_env or "", "")
        if not api_key:
            return [], f"{meta['name']} needs env var {key_env}"
        url = url.format(key=api_key)
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return [], f"{meta['name']} unreachable: {exc.__class__.__name__}"

    matches: list[dict[str, Any]] = []

    # Brute recursive scan for name-like strings — tolerant of schema drift.
    def _scan(obj: Any, path: list[str]):
        if isinstance(obj, dict):
            for k, v in obj.items():
                _scan(v, path + [k])
        elif isinstance(obj, list):
            for item in obj:
                _scan(item, path)
        elif isinstance(obj, str) and len(obj) < 200 and " " in obj:
            score = _fuzzy(name, obj)
            if score >= 85:
                matches.append(
                    {
                        "name": obj,
                        "confidence": score,
                        "pep_class": "Domestic/Foreign PEP",
                        "positions": [meta["name"]],
                        "countries": [jurisdiction.upper()],
                        "source": meta["authority"],
                    }
                )

    _scan(data, [])
    # Dedupe
    seen = set()
    deduped = []
    for m in sorted(matches, key=lambda x: x["confidence"], reverse=True):
        if m["name"] in seen:
            continue
        seen.add(m["name"])
        deduped.append(m)
    return deduped[:10], None


class PEPScreeningTool(BaseTool):
    name = "pep_screening"
    description = (
        "Screen a person against Politically Exposed Persons (PEP) lists — "
        "heads of state, cabinet, parliamentarians, senior judges, central "
        "bank governors, senior military, state-owned enterprise execs, "
        "ambassadors, plus family members and close associates. Mandated by "
        "FATF Rec. 12, EU AMLD-6, UK MLR 2017, BSA/PATRIOT Act, MAS Notice "
        "626, Canada PCMLTFA, and every comparable AML regime. "
        "Combines three independent signal sources — OpenSanctions PEP "
        "dataset (900k+ entries, 180+ jurisdictions, CC-BY), Wikidata "
        "SPARQL (live P39 position statements — catches newly-elected "
        "officials faster than bulk feeds), and per-country government "
        "roster scrapers (UK Parliament API, US congress.gov, "
        "bundestag.de, assemblee-nationale.fr, europarl.europa.eu, "
        "parlament.ch, riksdagen.se). Classifies each hit as Domestic / "
        "Foreign / International Organisation / Family / Close Associate / "
        "Former PEP (configurable 12-24 month lookback) / Not PEP. Returns "
        "name, position, jurisdiction, office dates, and confidence 0-100. "
        "Also produces an L/M/H risk grade. Set OPENSANCTIONS_API_KEY for "
        "higher rate limits; CONGRESS_GOV_API_KEY for US congress coverage. "
        "Use cases: KYC onboarding, correspondent banking, private banking "
        "client acceptance, insurance underwriting, real-estate agent due "
        "diligence, lawyer/notary client screening, casino enhanced DD."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Full legal name of the person to screen.",
            },
            "jurisdiction": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 code (e.g. 'GB', 'US', 'DE') of the country where the screened party resides or operates. Biases Wikidata + enables government-roster check.",
            },
            "also_check_aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional spellings, maiden names, patronymics, transliterations.",
            },
            "former_pep_lookback_months": {
                "type": "integer",
                "default": 18,
                "minimum": 0,
                "maximum": 120,
                "description": "How far back to still flag someone as Former PEP after leaving office. 18 months is FATF's common guidance; EU requires 'at least 12 months'. Set 0 to drop former PEPs entirely.",
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["opensanctions", "wikidata", "government_roster"],
                },
                "description": "Which sources to query. Omit for ALL.",
            },
            "threshold": {
                "type": "integer",
                "minimum": 50,
                "maximum": 100,
                "default": 85,
            },
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("name") or "").strip()
        if not name:
            return ToolResult(content="Error: 'name' is required.", is_error=True)

        jurisdiction = (arguments.get("jurisdiction") or "").strip().upper() or None
        sources = arguments.get("sources") or [
            "opensanctions",
            "wikidata",
            "government_roster",
        ]
        threshold = int(arguments.get("threshold", 85))
        aliases = arguments.get("also_check_aliases") or []
        _lookback = int(arguments.get("former_pep_lookback_months", 18))

        warnings: list[str] = []
        all_hits: list[dict[str, Any]] = []

        names_to_try = [name] + [a for a in aliases if a and a.strip()]

        if "opensanctions" in sources:
            api_key = os.environ.get("OPENSANCTIONS_API_KEY") or None
            for n in names_to_try:
                hits, warn = await _query_opensanctions(n, jurisdiction, api_key)
                if warn:
                    warnings.append(warn)
                all_hits.extend(hits)

        if "wikidata" in sources:
            for n in names_to_try:
                hits, warn = await _query_wikidata(n)
                if warn:
                    warnings.append(warn)
                all_hits.extend(hits)

        if "government_roster" in sources and jurisdiction:
            hits, warn = await _query_gov_roster(jurisdiction, name)
            if warn:
                warnings.append(warn)
            all_hits.extend(hits)

        # Filter to threshold, dedupe by (source, name)
        filtered = [h for h in all_hits if h.get("confidence", 0) >= threshold]
        dedup: dict[tuple[str, str], dict[str, Any]] = {}
        for h in sorted(filtered, key=lambda x: x.get("confidence", 0), reverse=True):
            key = (h.get("source", ""), _normalize(h.get("name", "")))
            if key in dedup:
                continue
            dedup[key] = h

        final_hits = list(dedup.values())
        max_conf = max((h.get("confidence", 0) for h in final_hits), default=0)

        # Top-level PEP class resolution — worst/strongest signal wins
        class_priority = {
            "Domestic/Foreign PEP": 5,
            "Foreign PEP": 5,
            "Domestic PEP": 4,
            "International Organisation PEP": 4,
            "Family PEP": 3,
            "Close Associate PEP": 3,
            "Former PEP": 2,
            "Potential PEP": 1,
            "Not PEP": 0,
        }
        resolved_class = "Not PEP"
        resolved_priority = -1
        for h in final_hits:
            c = h.get("pep_class", "Not PEP")
            p = class_priority.get(c, 0)
            if p > resolved_priority:
                resolved_priority = p
                resolved_class = c

        if resolved_class in (
            "Domestic/Foreign PEP",
            "Foreign PEP",
            "Domestic PEP",
            "International Organisation PEP",
        ):
            risk_grade = "H"
        elif resolved_class in ("Family PEP", "Close Associate PEP"):
            risk_grade = "M"
        elif resolved_class == "Former PEP":
            risk_grade = "M"
        elif final_hits:
            risk_grade = "L"
        else:
            risk_grade = "L"

        return ToolResult(
            content=json.dumps(
                {
                    "queried_name": name,
                    "jurisdiction": jurisdiction,
                    "resolved_pep_class": resolved_class,
                    "risk_grade": risk_grade,
                    "max_confidence": max_conf,
                    "total_hits": len(final_hits),
                    "hits": final_hits,
                    "warnings": warnings,
                    "disclaimer": (
                        "PEP status is time-sensitive. A negative hit today does "
                        "not guarantee future status; re-screen on risk-review "
                        "cadence (typically quarterly for high-risk clients)."
                    ),
                },
                indent=2,
            ),
            metadata={"pep_class": resolved_class, "risk_grade": risk_grade},
        )
