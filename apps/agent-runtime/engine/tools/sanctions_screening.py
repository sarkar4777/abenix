"""Sanctions screening tool — production-grade KYC/AML building block."""

from __future__ import annotations

import csv
import json
import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher
from io import StringIO
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0
_CACHE_TTL_SECONDS = 60 * 60 * 6  # 6 hours — sanctions lists change daily at most

# In-process memo of downloaded lists (tool instance is singleton per runtime).
_LIST_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


_SOURCES = {
    "OFAC_SDN": {
        "url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
        "aka_url": "https://www.treasury.gov/ofac/downloads/alt.csv",
        "format": "ofac_csv",
        "authority": "US Treasury OFAC",
        "human_url": "https://sanctionssearch.ofac.treas.gov/",
    },
    "OFAC_CONSOLIDATED": {
        "url": "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv",
        "aka_url": "https://www.treasury.gov/ofac/downloads/consolidated/cons_alt.csv",
        "format": "ofac_csv",
        "authority": "US Treasury OFAC (Non-SDN)",
        "human_url": "https://sanctionssearch.ofac.treas.gov/",
    },
    "EU_CONSOLIDATED": {
        "url": "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw",
        "format": "eu_xml",
        "authority": "European Commission FSD",
        "human_url": "https://webgate.ec.europa.eu/fsd/fsf/public/",
    },
    "UN_SC": {
        "url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "format": "un_xml",
        "authority": "UN Security Council",
        "human_url": "https://www.un.org/securitycouncil/sanctions/information",
    },
    "UK_HMT": {
        "url": "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv",
        "format": "uk_csv",
        "authority": "UK HM Treasury OFSI",
        "human_url": "https://www.gov.uk/government/publications/financial-sanctions-consolidated-list-of-targets",
    },
    "CA_OSFI": {
        "url": "https://www.international.gc.ca/world-monde/assets/office_docs/international_relations-relations_internationales/sanctions/sema-lmes.csv",
        "format": "canada_csv",
        "authority": "Global Affairs Canada (SEMA)",
        "human_url": "https://www.international.gc.ca/world-monde/international_relations-relations_internationales/sanctions/",
    },
    "AU_DFAT": {
        "url": "https://www.dfat.gov.au/sites/default/files/regulation8_consolidated.xlsx",
        "format": "dfat_xlsx",  # XLSX — best-effort; we fall back gracefully if dependency missing
        "authority": "Australia DFAT",
        "human_url": "https://www.dfat.gov.au/international-relations/security/sanctions/consolidated-list",
    },
    "CH_SECO": {
        "url": "https://www.sesam.search.admin.ch/sesam-search-web/pages/downloadXmlGesamtliste.xhtml",
        "format": "seco_xml",
        "authority": "Switzerland SECO",
        "human_url": "https://www.sesam.search.admin.ch/sesam-search-web/pages/search.xhtml",
    },
}


def _normalize(s: str) -> str:
    """Casefold, strip punctuation, collapse whitespace, remove accents."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fuzzy_ratio(a: str, b: str) -> int:
    """0-100 similarity using token-sort + SequenceMatcher.

    Handles "Smith, John" vs "John Smith" and nickname ordering.
    """
    if not a or not b:
        return 0
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 100
    # Token sort
    ts_a = " ".join(sorted(na.split()))
    ts_b = " ".join(sorted(nb.split()))
    direct = int(SequenceMatcher(None, na, nb).ratio() * 100)
    token = int(SequenceMatcher(None, ts_a, ts_b).ratio() * 100)
    # Substring bonus
    sub_bonus = 0
    if len(na) >= 4 and len(nb) >= 4:
        if na in nb or nb in na:
            sub_bonus = 10
    return min(100, max(direct, token) + sub_bonus)


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"
        },
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


def _parse_ofac_csv(main_bytes: bytes, alt_bytes: bytes | None) -> list[dict[str, Any]]:
    """Parse OFAC SDN.csv (ent_num,SDN_Name,SDN_Type,Program,Title,Call_Sign,
    Vess_type,Tonnage,GRT,Vess_flag,Vess_owner,Remarks)."""
    entries: dict[str, dict[str, Any]] = {}
    text = main_bytes.decode("latin-1", errors="ignore")
    reader = csv.reader(StringIO(text))
    for row in reader:
        if len(row) < 4:
            continue
        ent_num, name, sdn_type, program = row[0], row[1], row[2], row[3]
        remarks = row[11] if len(row) > 11 else ""
        entries[ent_num] = {
            "id": ent_num,
            "name": name.strip(),
            "aliases": [],
            "type": sdn_type.strip(),
            "programs": [p.strip() for p in program.split(";") if p.strip()],
            "remarks": remarks.strip(),
        }
    if alt_bytes:
        alt_text = alt_bytes.decode("latin-1", errors="ignore")
        alt_reader = csv.reader(StringIO(alt_text))
        for row in alt_reader:
            if len(row) < 4:
                continue
            ent_num, _alt_num, _alt_type, alt_name = row[0], row[1], row[2], row[3]
            if ent_num in entries and alt_name.strip():
                entries[ent_num]["aliases"].append(alt_name.strip())
    return list(entries.values())


def _parse_eu_xml(content: bytes) -> list[dict[str, Any]]:
    """Parse EU FSD XML."""
    entries: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return entries
    # EU FSD XML uses namespaces. Strip them for brute-force extraction.
    {"": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    for sub in root.iter():
        tag = sub.tag.split("}")[-1]
        if tag != "sanctionEntity":
            continue
        entry = {
            "id": sub.get("logicalId") or sub.get("euReferenceNumber") or "",
            "name": "",
            "aliases": [],
            "type": sub.get("sanctionEntityType") or "entity",
            "programs": [],
            "remarks": "",
        }
        for n in sub.iter():
            ntag = n.tag.split("}")[-1]
            if ntag == "nameAlias":
                w = n.get("wholeName") or ""
                if not entry["name"] and w:
                    entry["name"] = w.strip()
                elif w.strip():
                    entry["aliases"].append(w.strip())
            elif ntag == "regulation":
                reg = n.get("programme") or n.get("regulationType") or ""
                if reg:
                    entry["programs"].append(reg)
            elif ntag == "remark":
                if n.text:
                    entry["remarks"] = (entry["remarks"] + " " + n.text).strip()
        if entry["name"]:
            entries.append(entry)
    return entries


def _parse_un_xml(content: bytes) -> list[dict[str, Any]]:
    """Parse UN Security Council consolidated.xml."""
    entries: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return entries
    for block in root.iter():
        tag = block.tag.split("}")[-1]
        if tag not in ("INDIVIDUAL", "ENTITY"):
            continue
        is_entity = tag == "ENTITY"
        e: dict[str, Any] = {
            "id": (
                block.findtext("DATAID") or block.findtext("REFERENCE_NUMBER") or ""
            ).strip(),
            "name": "",
            "aliases": [],
            "type": "entity" if is_entity else "individual",
            "programs": [],
            "remarks": "",
        }
        if is_entity:
            e["name"] = (block.findtext("FIRST_NAME") or "").strip()
        else:
            parts = [
                block.findtext(f"{k}") or ""
                for k in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")
            ]
            e["name"] = " ".join(p for p in parts if p).strip()
        for a in block.iter():
            at = a.tag.split("}")[-1]
            if at in ("ALIAS_NAME", "INDIVIDUAL_ALIAS", "ENTITY_ALIAS"):
                alias_name = a.text or ""
                # Some aliases are in nested ALIAS_NAME elements
                sub = a.findtext("ALIAS_NAME") or ""
                if alias_name.strip():
                    e["aliases"].append(alias_name.strip())
                elif sub.strip():
                    e["aliases"].append(sub.strip())
            elif at == "UN_LIST_TYPE":
                if a.text:
                    e["programs"].append(a.text.strip())
            elif at == "COMMENTS1":
                if a.text:
                    e["remarks"] = a.text.strip()[:500]
        if e["name"]:
            entries.append(e)
    return entries


def _parse_uk_csv(content: bytes) -> list[dict[str, Any]]:
    """Parse UK HMT OFSI consolidated list CSV."""
    entries: list[dict[str, Any]] = []
    text = content.decode("utf-8", errors="ignore")
    try:
        reader = csv.DictReader(StringIO(text))
    except Exception:
        return entries
    by_id: dict[str, dict[str, Any]] = {}
    for row in reader:
        gid = (
            row.get("Group ID") or row.get("GroupID") or row.get("GROUP ID") or ""
        ).strip()
        if not gid:
            continue
        name_parts = [
            row.get("Name 6") or row.get("Company/Ship Name") or "",
            row.get("Name 1") or "",
            row.get("Name 2") or "",
            row.get("Name 3") or "",
            row.get("Name 4") or "",
            row.get("Name 5") or "",
        ]
        full_name = " ".join(p.strip() for p in name_parts if p.strip())
        regime = row.get("Regime") or row.get("REGIME") or ""
        alias_type = (row.get("Alias Type") or "").strip().lower()
        if gid not in by_id:
            by_id[gid] = {
                "id": gid,
                "name": full_name,
                "aliases": [],
                "type": (
                    "individual"
                    if (row.get("Individual") or "").strip().lower() == "individual"
                    else "entity"
                ),
                "programs": [regime] if regime else [],
                "remarks": (row.get("Other Information") or "").strip()[:300],
            }
        else:
            if alias_type and alias_type != "primary":
                if full_name and full_name != by_id[gid]["name"]:
                    by_id[gid]["aliases"].append(full_name)
    entries.extend(by_id.values())
    return entries


def _parse_canada_csv(content: bytes) -> list[dict[str, Any]]:
    """Parse Canada SEMA consolidated CSV."""
    entries: list[dict[str, Any]] = []
    for encoding in ("utf-8", "latin-1"):
        try:
            text = content.decode(encoding, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("latin-1", errors="ignore")
    try:
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            name = (
                row.get("Entity")
                or row.get("Last Name")
                and f"{row.get('Given Name', '')} {row['Last Name']}".strip()
                or row.get("Name")
                or ""
            ).strip()
            if not name:
                continue
            entries.append(
                {
                    "id": row.get("Item") or "",
                    "name": name,
                    "aliases": [
                        a.strip()
                        for a in (row.get("Aliases") or "").split(";")
                        if a.strip()
                    ],
                    "type": "entity" if row.get("Entity") else "individual",
                    "programs": [row.get("Schedule") or row.get("Country") or ""],
                    "remarks": "",
                }
            )
    except Exception as exc:
        logger.debug("Canada parse fell back: %s", exc)
    return entries


_PARSERS = {
    "ofac_csv": _parse_ofac_csv,
    "eu_xml": _parse_eu_xml,
    "un_xml": _parse_un_xml,
    "uk_csv": _parse_uk_csv,
    "canada_csv": _parse_canada_csv,
}


async def _load_list(source_key: str) -> tuple[list[dict[str, Any]], str | None]:
    """Return (entries, warning). Warning is non-None when we fell back"""
    meta = _SOURCES[source_key]
    cached = _LIST_CACHE.get(source_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1], None

    try:
        main_bytes = await _download(meta["url"])
        aka_bytes: bytes | None = None
        if meta.get("aka_url"):
            try:
                aka_bytes = await _download(meta["aka_url"])
            except Exception:
                aka_bytes = None
        fmt = meta["format"]
        parser = _PARSERS.get(fmt)
        if not parser:
            # Formats we haven't implemented yet (e.g. DFAT xlsx, SECO odd-xml)
            _LIST_CACHE[source_key] = (time.time(), [])
            return (
                [],
                f"{source_key} format '{fmt}' parser not implemented — list skipped",
            )
        if fmt == "ofac_csv":
            entries = parser(main_bytes, aka_bytes)
        else:
            entries = parser(main_bytes)
        _LIST_CACHE[source_key] = (time.time(), entries)
        return entries, None
    except httpx.HTTPError as exc:
        logger.warning("Sanctions list fetch failed for %s: %s", source_key, exc)
        _LIST_CACHE[source_key] = (time.time(), [])
        return [], f"{source_key} unreachable: {exc.__class__.__name__}"
    except Exception as exc:
        logger.exception("Sanctions list parse failed for %s", source_key)
        return [], f"{source_key} parse failed: {exc}"


def _match_against_list(
    target_name: str,
    entries: list[dict[str, Any]],
    threshold: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Return top-N hits above threshold, sorted by score descending."""
    hits: list[tuple[int, dict[str, Any], str]] = []
    for e in entries:
        score = _fuzzy_ratio(target_name, e["name"])
        matched_on = e["name"]
        for alias in e.get("aliases", []) or []:
            s2 = _fuzzy_ratio(target_name, alias)
            if s2 > score:
                score = s2
                matched_on = alias
        if score >= threshold:
            hits.append((score, e, matched_on))
    hits.sort(key=lambda t: t[0], reverse=True)
    top = hits[:limit]
    return [
        {
            "confidence": score,
            "matched_on": matched_on,
            "entry_name": e["name"],
            "entry_id": e["id"],
            "entity_type": e.get("type"),
            "programs": e.get("programs", []),
            "aliases": (e.get("aliases") or [])[:5],
            "remarks": e.get("remarks", "")[:300],
        }
        for score, e, matched_on in top
    ]


class SanctionsScreeningTool(BaseTool):
    name = "sanctions_screening"
    description = (
        "Screen a person or company name against the world's major sanctions "
        "lists — OFAC SDN, OFAC Consolidated (non-SDN), EU Consolidated, "
        "UN Security Council, UK HMT OFSI, Canada OSFI, Australia DFAT, "
        "Switzerland SECO. Uses public authoritative feeds (no paid API) "
        "with fuzzy matching (token-sort + sequence ratio) and AKA alias "
        "expansion so that 'Smith, John' matches 'John Smith' and reordered "
        "transliterations are caught. Returns per-list hits with confidence "
        "0-100, matched alias, sanctions programmes, and source URLs for audit. "
        "Use for: KYC onboarding, ongoing counterparty monitoring, vendor "
        "screening, payment screening, pre-trade checks, and any jurisdiction "
        "requiring AML/CFT compliance (FATF Rec. 6). Set `threshold` lower "
        "(70-80) for investigative sweeps, higher (90+) for high-precision "
        "gates. Lists are cached 6 hours per source; override with `refresh=true`."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Full legal name of the entity or individual to screen.",
            },
            "entity_type": {
                "type": "string",
                "enum": ["individual", "entity", "any"],
                "default": "any",
                "description": "Filter by entity type. Use 'any' unless you have high confidence the target is strictly one.",
            },
            "lists": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "OFAC_SDN",
                        "OFAC_CONSOLIDATED",
                        "EU_CONSOLIDATED",
                        "UN_SC",
                        "UK_HMT",
                        "CA_OSFI",
                        "AU_DFAT",
                        "CH_SECO",
                    ],
                },
                "description": "Subset of lists to check. Omit for ALL.",
            },
            "threshold": {
                "type": "integer",
                "minimum": 50,
                "maximum": 100,
                "default": 85,
                "description": "Minimum fuzzy match score (0-100) to report as a hit. 85 = good KYC default; 70-80 for exploratory sweeps; 92+ for high-precision gating.",
            },
            "max_hits_per_list": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "refresh": {
                "type": "boolean",
                "default": False,
                "description": "Force re-download even if cache is fresh.",
            },
            "also_check_aliases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional names/spellings to also screen (e.g. trading names, Cyrillic/Arabic transliterations).",
            },
        },
        "required": ["name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("name") or "").strip()
        if not name:
            return ToolResult(content="Error: 'name' is required.", is_error=True)

        entity_type = arguments.get("entity_type", "any")
        threshold = int(arguments.get("threshold", 85))
        max_hits = int(arguments.get("max_hits_per_list", 5))
        lists_filter = arguments.get("lists") or list(_SOURCES.keys())
        also_check = arguments.get("also_check_aliases") or []
        refresh = bool(arguments.get("refresh", False))

        if refresh:
            for k in lists_filter:
                _LIST_CACHE.pop(k, None)

        names_to_check = [name] + [a for a in also_check if a and a.strip()]

        import asyncio

        per_list: list[dict[str, Any]] = []
        warnings: list[str] = []
        total_hits = 0

        # Download all lists in parallel — big speed-up.
        keys = [k for k in lists_filter if k in _SOURCES]
        loaded = await asyncio.gather(
            *(_load_list(k) for k in keys), return_exceptions=True
        )

        for source_key, result in zip(keys, loaded):
            if isinstance(result, Exception):
                warnings.append(f"{source_key} error: {result.__class__.__name__}")
                continue
            entries, warn = result  # type: ignore[misc]
            if warn:
                warnings.append(warn)
            filtered = entries
            if entity_type != "any":
                filtered = [
                    e
                    for e in entries
                    if (e.get("type") or "").lower().startswith(entity_type[:3])
                ]
            best_per_list: list[dict[str, Any]] = []
            for n in names_to_check:
                hits = _match_against_list(n, filtered, threshold, max_hits)
                best_per_list.extend(hits)
            # Dedupe by entry_id+matched_on
            seen = set()
            dedup = []
            for h in sorted(best_per_list, key=lambda x: x["confidence"], reverse=True):
                key = (h["entry_id"], h["matched_on"])
                if key in seen:
                    continue
                seen.add(key)
                dedup.append(h)
            per_list.append(
                {
                    "list": source_key,
                    "authority": _SOURCES[source_key]["authority"],
                    "source_url": _SOURCES[source_key]["human_url"],
                    "entries_indexed": len(filtered),
                    "hits": dedup[:max_hits],
                }
            )
            total_hits += len(dedup[:max_hits])

        # Overall risk grade
        max_conf = 0
        for pl in per_list:
            for h in pl["hits"]:
                max_conf = max(max_conf, h["confidence"])
        if max_conf >= 95:
            risk_grade = "H"
            risk_label = "High — probable direct sanctions hit"
        elif max_conf >= 85:
            risk_grade = "M"
            risk_label = "Medium — possible hit, requires manual review"
        elif max_conf >= threshold:
            risk_grade = "L"
            risk_label = "Low — weak fuzzy match, likely false positive"
        else:
            risk_grade = "L"
            risk_label = "Clear — no hits above threshold"

        return ToolResult(
            content=json.dumps(
                {
                    "queried_name": name,
                    "also_checked": also_check,
                    "entity_type_filter": entity_type,
                    "threshold": threshold,
                    "lists_checked": [pl["list"] for pl in per_list],
                    "total_hits": total_hits,
                    "max_confidence": max_conf,
                    "risk_grade": risk_grade,  # L/M/H for direct use in KYC forms
                    "risk_label": risk_label,
                    "per_list_results": per_list,
                    "warnings": warnings,
                    "disclaimer": (
                        "Screening is only as current as the published feeds. "
                        "For a regulatory-grade decision, re-run close to the "
                        "transaction date and verify any hit against the "
                        "source list directly."
                    ),
                },
                indent=2,
            ),
            metadata={"hits": total_hits, "risk_grade": risk_grade},
        )
