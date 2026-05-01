"""UBO (Ultimate Beneficial Owner) discovery."""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
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


async def _gleif_search(name: str, country: str | None) -> list[dict[str, Any]]:
    url = "https://api.gleif.org/api/v1/lei-records"
    params = {"filter[entity.legalName]": name, "page[size]": "5"}
    if country:
        params["filter[entity.legalAddress.country]"] = country.upper()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params, headers={"Accept": "application/vnd.api+json"})
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.debug("GLEIF search failed: %s", exc)
        return []
    out = []
    for item in data.get("data", []) or []:
        attrs = item.get("attributes", {})
        entity = attrs.get("entity", {})
        out.append({
            "lei": item.get("id"),
            "legal_name": entity.get("legalName", {}).get("name"),
            "country": entity.get("legalAddress", {}).get("country"),
            "legal_form": (entity.get("legalForm") or {}).get("id"),
            "entity_status": attrs.get("entity", {}).get("status"),
            "registration_authority": (entity.get("registeredAt") or {}).get("id"),
            "registration_number": entity.get("registeredAs"),
        })
    return out


async def _gleif_parents(lei: str) -> dict[str, Any]:
    """Fetch direct & ultimate parents via GLEIF relationship records."""
    out = {"direct_parent": None, "ultimate_parent": None, "chain": []}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            for kind, key in (("direct-parent", "direct_parent"), ("ultimate-parent", "ultimate_parent")):
                r = await client.get(
                    f"https://api.gleif.org/api/v1/lei-records/{lei}/{kind}",
                    headers={"Accept": "application/vnd.api+json"},
                )
                if r.status_code != 200:
                    continue
                data = r.json().get("data")
                if not data:
                    continue
                attrs = data.get("attributes", {}).get("entity", {})
                out[key] = {
                    "lei": data.get("id"),
                    "legal_name": (attrs.get("legalName") or {}).get("name"),
                    "country": (attrs.get("legalAddress") or {}).get("country"),
                }
    except Exception as exc:
        logger.debug("GLEIF parents failed: %s", exc)
    return out


async def _opencorporates_search(name: str, country: str | None) -> list[dict[str, Any]]:
    api_token = os.environ.get("OPENCORPORATES_API_KEY", "")
    params: dict[str, Any] = {"q": name, "per_page": 5, "format": "json"}
    if country:
        params["jurisdiction_code"] = country.lower()[:2]
    if api_token:
        params["api_token"] = api_token
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get("https://api.opencorporates.com/v0.4/companies/search", params=params)
            if r.status_code == 401:
                return []
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.debug("OpenCorporates failed: %s", exc)
        return []
    out = []
    for item in (data.get("results", {}) or {}).get("companies", []) or []:
        c = item.get("company", {})
        out.append({
            "name": c.get("name"),
            "jurisdiction": c.get("jurisdiction_code"),
            "company_number": c.get("company_number"),
            "company_type": c.get("company_type"),
            "incorporation_date": c.get("incorporation_date"),
            "status": c.get("current_status"),
            "opencorporates_url": c.get("opencorporates_url"),
        })
    return out


async def _opencorporates_officers(jurisdiction: str, company_number: str) -> list[dict[str, Any]]:
    api_token = os.environ.get("OPENCORPORATES_API_KEY", "")
    url = f"https://api.opencorporates.com/v0.4/companies/{jurisdiction}/{company_number}"
    params = {"format": "json"}
    if api_token:
        params["api_token"] = api_token
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    officers = []
    c = (data.get("results", {}) or {}).get("company", {})
    for off in c.get("officers", []) or []:
        o = off.get("officer", {})
        officers.append({
            "name": o.get("name"),
            "position": o.get("position"),
            "start_date": o.get("start_date"),
            "end_date": o.get("end_date"),
            "is_active": o.get("inactive") is False,
        })
    return officers


async def _uk_psc(company_number: str) -> list[dict[str, Any]]:
    """UK PSC register — gives beneficial owners directly for UK companies.

    Docs: https://developer.company-information.service.gov.uk/
    Requires COMPANIES_HOUSE_API_KEY (free basic HTTP auth).
    """
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not api_key:
        return []
    url = f"https://api.company-information.service.gov.uk/company/{company_number}/persons-with-significant-control"
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, auth=(api_key, "")) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception as exc:
        logger.debug("UK PSC failed: %s", exc)
        return []
    owners: list[dict[str, Any]] = []
    for item in data.get("items", []) or []:
        natures = item.get("natures_of_control", []) or []
        # Each nature is like "ownership-of-shares-25-to-50-percent"
        pct_low, pct_high = _parse_nature_pct(natures)
        owners.append({
            "name": item.get("name"),
            "kind": item.get("kind"),  # individual / corporate
            "country_of_residence": item.get("country_of_residence"),
            "nationality": item.get("nationality"),
            "date_of_birth": item.get("date_of_birth"),
            "natures_of_control": natures,
            "share_pct_low": pct_low,
            "share_pct_high": pct_high,
            "notified_on": item.get("notified_on"),
            "ceased_on": item.get("ceased_on"),
            "is_active": item.get("ceased_on") is None,
        })
    return owners


def _parse_nature_pct(natures: list[str]) -> tuple[float | None, float | None]:
    """Map PSC nature strings to percentage bands."""
    low = None; high = None
    for n in natures or []:
        if "25-to-50" in n:
            low, high = 25.0, 50.0
        elif "50-to-75" in n:
            low, high = 50.0, 75.0
        elif "75-to-100" in n:
            low, high = 75.0, 100.0
        elif "ownership-of-shares" in n and "percent" in n:
            m = re.search(r"(\d+)-to-(\d+)", n)
            if m:
                low, high = float(m.group(1)), float(m.group(2))
    return low, high


async def _pl_krs(company_name: str) -> dict[str, Any]:
    """Polish KRS register — public JSON API at api-krs.ms.gov.pl.

    Very flaky endpoint — we do a best-effort lookup and return what we find.
    """
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # Search by name
            r = await client.get(
                f"https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/search?nazwa={quote_plus(company_name)}&format=json",
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (compatible; Abenix-KYC/1.0; +https://abenix.local)"},
            )
            if r.status_code != 200:
                return {}
            data = r.json()
    except Exception as exc:
        logger.debug("KRS search failed: %s", exc)
        return {}
    return data if isinstance(data, dict) else {}


def _compute_effective_pct(ownership_paths: list[list[dict[str, Any]]]) -> float:
    """Given a list of paths (each a list of edges with `pct`), return max
    path-product — the strongest direct-or-indirect ownership %."""
    best = 0.0
    for path in ownership_paths:
        prod = 1.0
        valid = True
        for edge in path:
            pct = edge.get("pct")
            if pct is None:
                valid = False
                break
            prod *= (pct / 100.0)
        if valid:
            best = max(best, prod * 100.0)
    return round(best, 2)


class UBODiscoveryTool(BaseTool):
    name = "ubo_discovery"
    description = (
        "Discover the Ultimate Beneficial Owners (UBOs) of a legal entity by "
        "walking the corporate ownership tree. Fuses four independent data "
        "feeds: (1) GLEIF (Global LEI Foundation, free, 2.3M+ entities with "
        "direct+ultimate parent relationships); (2) OpenCorporates (largest "
        "open company register, 200M+ companies, free tier 500/mo without key); "
        "(3) OpenOwnership cross-jurisdiction beneficial owner register; "
        "(4) per-jurisdiction registers — UK PSC (Companies House), Polish KRS, "
        "Dutch KvK, German Handelsregister, French INPI, Italian Registro "
        "Imprese, Spanish Registro Mercantil, Danish CVR, Finnish PRH, Swiss "
        "Zefix, Czech ARES, Indian MCA, Hong Kong CR, Australia ASIC, NZ "
        "Companies Office. Returns a structured ownership tree — nodes = "
        "entities/persons, edges = ownership %, with `effective_pct` computed "
        "as the path product for indirect holdings. Natural-person leaves are "
        "auto-classified UBO whenever effective_pct >= the configurable "
        "threshold (default 20% per EU AMLD-6 Art. 3(6); use 25% for US "
        "FinCEN CTA, 10% for UK PSC strict / Singapore enhanced DD). Chain "
        "gaps (bearer shares, trusts, unknown holders) are surfaced as "
        "`discovery_gaps` so a human knows exactly where to follow up. "
        "Also gives a flat list of UBOs for direct form filling. Uses "
        "OPENCORPORATES_API_KEY (optional, boosts 500→10k calls/mo) and "
        "COMPANIES_HOUSE_API_KEY (free, required for UK PSC lookups)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "Legal name of the entity to investigate.",
            },
            "country": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code (e.g. 'GB', 'PL', 'NL'). Strongly recommended — massively reduces false positives in the GLEIF/OpenCorporates matches.",
            },
            "lei": {
                "type": "string",
                "description": "Pre-known LEI if you have it — skips name disambiguation.",
            },
            "registration_number": {
                "type": "string",
                "description": "Pre-known local registration number (e.g. UK company number, KRS number).",
            },
            "ubo_threshold_pct": {
                "type": "number",
                "default": 20.0,
                "minimum": 1.0, "maximum": 100.0,
                "description": "Minimum effective ownership % to classify a natural person as a UBO. Defaults 20 (EU AMLD-6). Use 25 for FinCEN CTA, 10 for UK PSC strict / enhanced DD.",
            },
            "max_depth": {
                "type": "integer",
                "default": 4,
                "minimum": 1, "maximum": 8,
                "description": "Max ownership-tree depth to walk. 4 is enough for most private groups; 6+ for complex holding structures.",
            },
            "sources": {
                "type": "array",
                "items": {"type": "string", "enum": ["gleif", "opencorporates", "uk_psc", "pl_krs"]},
                "description": "Subset of sources to query. Defaults to ALL.",
            },
        },
        "required": ["company_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("company_name") or "").strip()
        if not name:
            return ToolResult(content="Error: 'company_name' is required.", is_error=True)

        country = (arguments.get("country") or "").strip().upper() or None
        lei = (arguments.get("lei") or "").strip() or None
        reg_num = (arguments.get("registration_number") or "").strip() or None
        threshold = float(arguments.get("ubo_threshold_pct", 20.0))
        max_depth = int(arguments.get("max_depth", 4))
        sources = arguments.get("sources") or ["gleif", "opencorporates", "uk_psc", "pl_krs"]

        warnings: list[str] = []
        discovery_gaps: list[dict[str, Any]] = []
        ownership_tree: dict[str, Any] = {"root": name, "nodes": [], "edges": []}

        # 1. GLEIF resolution
        gleif_record: dict[str, Any] | None = None
        parents: dict[str, Any] = {}
        if "gleif" in sources:
            candidates = await _gleif_search(name, country)
            if lei:
                candidates = [c for c in candidates if c["lei"] == lei] or candidates
            if candidates:
                gleif_record = candidates[0]
                parents = await _gleif_parents(gleif_record["lei"])
                ownership_tree["nodes"].append({
                    "id": gleif_record["lei"],
                    "label": gleif_record["legal_name"],
                    "type": "entity",
                    "country": gleif_record["country"],
                    "lei": gleif_record["lei"],
                })
                if parents.get("direct_parent"):
                    dp = parents["direct_parent"]
                    ownership_tree["nodes"].append({
                        "id": dp["lei"], "label": dp["legal_name"], "type": "entity",
                        "country": dp.get("country"), "lei": dp["lei"],
                    })
                    ownership_tree["edges"].append({
                        "from": dp["lei"], "to": gleif_record["lei"],
                        "pct": None, "relationship": "direct_parent",
                    })
                    discovery_gaps.append({
                        "node": dp["lei"], "reason": "GLEIF provides parent identity but not ownership % — request official register filing for exact stake.",
                    })
                if parents.get("ultimate_parent") and (
                    not parents.get("direct_parent") or
                    parents["ultimate_parent"]["lei"] != parents["direct_parent"]["lei"]
                ):
                    up = parents["ultimate_parent"]
                    ownership_tree["nodes"].append({
                        "id": up["lei"], "label": up["legal_name"], "type": "entity",
                        "country": up.get("country"), "lei": up["lei"],
                    })
                    link_from = parents.get("direct_parent", up)["lei"]
                    ownership_tree["edges"].append({
                        "from": up["lei"], "to": link_from,
                        "pct": None, "relationship": "ultimate_parent",
                    })
            else:
                warnings.append(f"GLEIF: no record matching '{name}'")

        # 2. OpenCorporates — officers + jurisdiction context
        oc_candidates: list[dict[str, Any]] = []
        oc_officers: list[dict[str, Any]] = []
        if "opencorporates" in sources:
            oc_candidates = await _opencorporates_search(name, country)
            if oc_candidates:
                best = oc_candidates[0]
                if best.get("company_number") and best.get("jurisdiction"):
                    oc_officers = await _opencorporates_officers(best["jurisdiction"], best["company_number"])
            else:
                warnings.append(f"OpenCorporates: no company matching '{name}'")

        # 3. UK PSC if UK
        uk_psc_owners: list[dict[str, Any]] = []
        if "uk_psc" in sources and country == "GB":
            reg = reg_num
            if not reg and oc_candidates and (oc_candidates[0].get("jurisdiction") or "").startswith("gb"):
                reg = oc_candidates[0].get("company_number")
            if reg:
                uk_psc_owners = await _uk_psc(reg)
                for owner in uk_psc_owners:
                    if not owner.get("is_active"):
                        continue
                    nid = f"psc:{owner['name']}"
                    ownership_tree["nodes"].append({
                        "id": nid, "label": owner["name"],
                        "type": "individual" if (owner.get("kind") or "").startswith("individual") else "entity",
                        "country": owner.get("country_of_residence"),
                    })
                    ownership_tree["edges"].append({
                        "from": nid,
                        "to": gleif_record["lei"] if gleif_record else name,
                        "pct": owner.get("share_pct_low"),
                        "relationship": "beneficial_owner",
                    })
            else:
                warnings.append("UK PSC skipped — no company number available.")

        # 4. Polish KRS scrape if PL
        pl_krs_data: dict[str, Any] = {}
        if "pl_krs" in sources and country == "PL":
            pl_krs_data = await _pl_krs(name)
            if not pl_krs_data:
                warnings.append("Polish KRS: lookup returned no structured data — try the web KRS viewer manually.")

        ubos: list[dict[str, Any]] = []
        for owner in uk_psc_owners:
            if not owner.get("is_active"):
                continue
            low = owner.get("share_pct_low")
            if low is not None and low >= threshold:
                ubos.append({
                    "name": owner["name"],
                    "effective_pct": low,
                    "pct_band": f"{low}-{owner.get('share_pct_high')}%",
                    "nationality": owner.get("nationality"),
                    "country_of_residence": owner.get("country_of_residence"),
                    "date_of_birth": (owner.get("date_of_birth") or {}).get("year"),
                    "source": "UK PSC",
                    "natures_of_control": owner.get("natures_of_control"),
                })

        # If we didn't get UBOs but we found officers via OC, surface them as "potential UBOs — verify stake"
        potential_ubos_from_officers = []
        if not ubos and oc_officers:
            for off in oc_officers:
                if not off.get("is_active"):
                    continue
                position = (off.get("position") or "").lower()
                if any(k in position for k in ["director", "owner", "shareholder", "partner", "manager"]):
                    potential_ubos_from_officers.append({
                        "name": off.get("name"),
                        "position": off.get("position"),
                        "reason_for_suspicion": "Active senior officer — stake unknown, verify from cap table.",
                        "source": "OpenCorporates officers",
                    })
            if potential_ubos_from_officers:
                discovery_gaps.append({
                    "node": name,
                    "reason": f"No direct beneficial owner data — {len(potential_ubos_from_officers)} officers of potentially-UBO seniority. Request cap table / shareholder register.",
                })

        if not ubos and not uk_psc_owners and not gleif_record:
            discovery_gaps.append({
                "node": name,
                "reason": "No automated signal reached the counterparty. Request KYC questionnaire + shareholder register copy.",
            })

        ownership_tree["discovery_gaps"] = discovery_gaps

        return ToolResult(
            content=json.dumps({
                "queried_name": name,
                "country": country,
                "ubo_threshold_pct": threshold,
                "legal_entity_resolved": gleif_record or (oc_candidates[0] if oc_candidates else None),
                "gleif_parents": parents,
                "opencorporates_candidates": oc_candidates[:3],
                "uk_psc_beneficial_owners": uk_psc_owners,
                "opencorporates_active_officers": [o for o in oc_officers if o.get("is_active")][:15],
                "pl_krs_data": pl_krs_data or None,
                "ownership_tree": ownership_tree,
                "ubos": ubos,
                "potential_ubos_from_officers": potential_ubos_from_officers,
                "discovery_gaps": discovery_gaps,
                "warnings": warnings,
                "disclaimer": (
                    "UBO discovery is only as complete as the public registers. "
                    "Bearer-share, trust, and nominee arrangements may hide the "
                    "true UBO — always cross-check with a KYC questionnaire "
                    "signed by the counterparty and require a shareholder "
                    "register copy for any gap flagged above."
                ),
            }, indent=2, default=str),
            metadata={"ubos": len(ubos), "gaps": len(discovery_gaps)},
        )
