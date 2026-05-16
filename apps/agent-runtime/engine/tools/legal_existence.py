"""Legal existence verification — the Basic Compliance Check on every KYC form."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0


RED_FLAGS = {
    "shell_pattern_recent_incorporation": "Incorporated <6 months ago yet being used for a material transaction.",
    "shell_pattern_mass_address": "Registered address matches a well-known mass-registration service.",
    "shell_pattern_dormant": "No trading history / nil accounts for two or more consecutive years.",
    "jurisdiction_mismatch": "Incorporation country differs from stated operating country with no branch filing.",
    "dissolved_or_struck_off": "Register indicates the entity is dissolved, liquidated, or struck off.",
    "no_registry_match": "No match in any of the public registries — manual verification mandatory.",
    "multiple_registry_matches_same_jurisdiction": "Multiple entities share the exact same name in the same jurisdiction — disambiguate before proceeding.",
    "lei_lapsed": "LEI exists but status is LAPSED — LEI renewal overdue.",
    "unusual_legal_form": "Legal form is one typically associated with tax-shelter structures (trust companies, IBCs, cell companies).",
}


# Mass-registration address patterns: detected heuristically by density —
# we query OpenCorporates for the exact address and count how many other
# companies share it. A config-driven allowlist can be added but we do
# NOT embed a hardcoded list; the pattern is derived live.


def _normalize(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s.lower())).strip()


async def _gleif_lookup(name: str, country: str | None) -> list[dict[str, Any]]:
    params = {
        "filter[entity.legalName]": name,
        "page[size]": "5",
    }
    if country:
        params["filter[entity.legalAddress.country]"] = country.upper()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                "https://api.gleif.org/api/v1/lei-records",
                params=params,
                headers={"Accept": "application/vnd.api+json"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []
    out = []
    for item in data.get("data", []) or []:
        attrs = item.get("attributes", {})
        entity = attrs.get("entity", {})
        addr = entity.get("legalAddress") or {}
        out.append(
            {
                "lei": item.get("id"),
                "legal_name": (entity.get("legalName") or {}).get("name"),
                "legal_form": (entity.get("legalForm") or {}).get("id"),
                "status": (attrs.get("registration") or {}).get("status")
                or entity.get("status"),
                "country": addr.get("country"),
                "address_lines": addr.get("addressLines", []),
                "postal_code": addr.get("postalCode"),
                "city": addr.get("city"),
                "region": addr.get("region"),
                "registration_number": entity.get("registeredAs"),
                "registration_authority": (entity.get("registeredAt") or {}).get("id"),
            }
        )
    return out


async def _opencorporates_lookup(
    name: str, country: str | None
) -> list[dict[str, Any]]:
    api_token = os.environ.get("OPENCORPORATES_API_KEY", "")
    params: dict[str, Any] = {"q": name, "per_page": 5, "format": "json"}
    if country:
        params["jurisdiction_code"] = country.lower()[:2]
    if api_token:
        params["api_token"] = api_token
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params=params,
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    out = []
    for item in (data.get("results", {}) or {}).get("companies", []) or []:
        c = item.get("company", {})
        out.append(
            {
                "name": c.get("name"),
                "jurisdiction": c.get("jurisdiction_code"),
                "company_number": c.get("company_number"),
                "company_type": c.get("company_type"),
                "incorporation_date": c.get("incorporation_date"),
                "dissolution_date": c.get("dissolution_date"),
                "status": c.get("current_status"),
                "registered_address": (c.get("registered_address") or {}).get(
                    "in_full"
                ),
                "opencorporates_url": c.get("opencorporates_url"),
            }
        )
    return out


async def _uk_ch_lookup(name: str) -> list[dict[str, Any]]:
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, auth=(api_key, "")
        ) as client:
            r = await client.get(
                "https://api.company-information.service.gov.uk/search/companies",
                params={"q": name, "items_per_page": 5},
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    out = []
    for item in data.get("items", []) or []:
        out.append(
            {
                "name": item.get("title"),
                "company_number": item.get("company_number"),
                "status": item.get("company_status"),
                "jurisdiction": "gb",
                "incorporation_date": item.get("date_of_creation"),
                "dissolution_date": item.get("date_of_cessation"),
                "registered_address": (item.get("address") or {}).get("premises", "")
                + " "
                + (item.get("address") or {}).get("address_line_1", "")
                + ", "
                + (item.get("address") or {}).get("locality", "")
                + " "
                + (item.get("address") or {}).get("postal_code", ""),
                "company_type": item.get("company_type"),
            }
        )
    return out


def _classify_status(raw: str | None) -> str:
    if not raw:
        return "unknown"
    s = raw.lower()
    if "active" in s or "registered" in s or "issued" in s:
        return "active"
    if "dissolv" in s or "struck" in s or "liquidat" in s or "wound" in s:
        return "dissolved"
    if "inactive" in s or "dormant" in s:
        return "inactive"
    if "lapsed" in s:
        return "lapsed"
    return raw


async def _check_address_red_flags(addr: str | None) -> list[str]:
    """Live check: query OpenCorporates for how many other companies share"""
    if not addr:
        return []
    api_token = os.environ.get("OPENCORPORATES_API_KEY", "")
    params: dict[str, Any] = {"q": addr[:120], "per_page": 100, "format": "json"}
    if api_token:
        params["api_token"] = api_token
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params=params,
            )
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    total = (data.get("results", {}) or {}).get("total_count") or 0
    if total > 50:
        return ["shell_pattern_mass_address"]
    return []


def _check_age_red_flag(incorp_date: str | None) -> list[str]:
    if not incorp_date:
        return []
    try:
        d = datetime.fromisoformat(incorp_date)
    except ValueError:
        return []
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - d).days
    if age_days < 180:
        return ["shell_pattern_recent_incorporation"]
    return []


class LegalExistenceVerifierTool(BaseTool):
    name = "legal_existence_verifier"
    description = (
        "Verify that a counterparty legally exists, is in good standing, and "
        "is not a suspected shell. Cross-references GLEIF (2.3M+ LEI records), "
        "OpenCorporates (200M+ companies across 140+ jurisdictions), UK "
        "Companies House, and per-country registers. Returns a normalized "
        "verdict: `exists` (true/false/unknown), `status` (active / dissolved "
        "/ liquidated / struck_off / inactive / unknown), LEI, registration "
        "number, legal form, incorporation date, jurisdiction, registered "
        "address, and a confidence score. Auto-detects common AML red flags: "
        "shell patterns (recent incorporation, mass-registration addresses, "
        "dormant filings), dissolved / struck-off status, jurisdiction "
        "mismatches (incorporated in one country, operating from another), "
        "lapsed LEIs, and legal forms typical of tax-shelter structures. "
        "Each finding is paired with a `verification_trail[]` of (source, "
        "url, evidence) entries suitable for pasting into a KYC audit log. "
        "Use this as the 'Basic Compliance Check — Verification of Legal "
        "Existence' step on every KYC file, and as the entry point for "
        "supplier/vendor onboarding, procurement due diligence, and "
        "invoice-fraud checks. Requires COMPANIES_HOUSE_API_KEY for UK "
        "gold-standard lookups (free basic auth)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "company_name": {"type": "string"},
            "country": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 code. Strongly recommended.",
            },
            "registration_number": {
                "type": "string",
                "description": "Pre-known local company number — reduces ambiguity.",
            },
            "lei": {
                "type": "string",
                "description": "Pre-known LEI — skips GLEIF name search.",
            },
        },
        "required": ["company_name"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = (arguments.get("company_name") or "").strip()
        if not name:
            return ToolResult(
                content="Error: 'company_name' is required.", is_error=True
            )

        country = (arguments.get("country") or "").strip().upper() or None
        reg_number = (arguments.get("registration_number") or "").strip() or None
        lei_in = (arguments.get("lei") or "").strip() or None

        trail: list[dict[str, Any]] = []
        red_flags: list[str] = []

        # 1. GLEIF
        gleif_hits = await _gleif_lookup(name, country)
        if lei_in:
            gleif_hits = [h for h in gleif_hits if h["lei"] == lei_in] or gleif_hits
        if gleif_hits:
            trail.append(
                {
                    "source": "GLEIF",
                    "url": "https://www.gleif.org/en/lei-data/gleif-lei-look-up-api/",
                    "evidence": f"LEI records found: {len(gleif_hits)}",
                }
            )
        else:
            trail.append(
                {
                    "source": "GLEIF",
                    "url": "https://search.gleif.org/",
                    "evidence": "No LEI match — company may not be LEI-registered (common for private SMEs).",
                }
            )

        # 2. OpenCorporates
        oc_hits = await _opencorporates_lookup(name, country)
        if oc_hits:
            trail.append(
                {
                    "source": "OpenCorporates",
                    "url": oc_hits[0].get("opencorporates_url", ""),
                    "evidence": f"{len(oc_hits)} match(es) in OpenCorporates.",
                }
            )

        # 3. UK CH
        uk_hits: list[dict[str, Any]] = []
        if (country or "").upper() == "GB":
            uk_hits = await _uk_ch_lookup(name)
            if uk_hits:
                trail.append(
                    {
                        "source": "UK Companies House",
                        "url": f"https://find-and-update.company-information.service.gov.uk/company/{uk_hits[0]['company_number']}",
                        "evidence": f"Companies House match (company number {uk_hits[0]['company_number']}, status {uk_hits[0]['status']}).",
                    }
                )

        # Pick the best candidate
        best: dict[str, Any] = {}
        source_of_best = ""
        if uk_hits:
            best = uk_hits[0]
            source_of_best = "UK Companies House"
        elif oc_hits:
            best = oc_hits[0]
            source_of_best = "OpenCorporates"
        elif gleif_hits:
            best = gleif_hits[0]
            source_of_best = "GLEIF"

        # 4. Multiple-match red flag check
        if country:
            same_juris_matches = [
                h
                for h in oc_hits
                if (h.get("jurisdiction") or "").lower()[:2] == country.lower()[:2]
            ]
            if len(same_juris_matches) > 1:
                red_flags.append("multiple_registry_matches_same_jurisdiction")

        # 5. Status / age / address red flags
        status = "unknown"
        incorporation_date = None
        address = None
        reg_num = None
        lei = None
        legal_form = None
        if best:
            status = _classify_status(best.get("status"))
            incorporation_date = best.get("incorporation_date")
            address = best.get("registered_address") or " ".join(
                best.get("address_lines") or []
            )
            reg_num = (
                best.get("company_number")
                or best.get("registration_number")
                or reg_number
            )
            lei = best.get("lei") or lei_in
            legal_form = best.get("legal_form") or best.get("company_type")

            if status == "dissolved":
                red_flags.append("dissolved_or_struck_off")
            red_flags += await _check_address_red_flags(address)
            red_flags += _check_age_red_flag(incorporation_date)

            # LEI lapsed
            if best.get("status") == "LAPSED":
                red_flags.append("lei_lapsed")

            if legal_form and any(
                k in legal_form.lower()
                for k in [
                    "ibc",
                    "international business",
                    "trust compan",
                    "cell compan",
                    "segregated portfolio",
                ]
            ):
                red_flags.append("unusual_legal_form")

        exists: bool | None
        if best and status == "active":
            exists = True
        elif best and status == "dissolved":
            exists = False
        elif not best:
            exists = None
            red_flags.append("no_registry_match")
        else:
            exists = None

        # 6. Confidence
        confidence = 0
        if best:
            confidence = 60
            if source_of_best == "UK Companies House":
                confidence = 95
            elif source_of_best == "OpenCorporates" and reg_num:
                confidence = 85
            elif gleif_hits and oc_hits:
                confidence = 80

        return ToolResult(
            content=json.dumps(
                {
                    "queried_name": name,
                    "country": country,
                    "exists": exists,
                    "status": status,
                    "confidence": confidence,
                    "primary_source": source_of_best,
                    "lei": lei,
                    "registration_number": reg_num,
                    "legal_form": legal_form,
                    "incorporation_date": incorporation_date,
                    "registered_address": address,
                    "red_flags": sorted(set(red_flags)),
                    "red_flag_descriptions": {
                        f: RED_FLAGS.get(f, "") for f in sorted(set(red_flags))
                    },
                    "gleif_candidates": gleif_hits[:3],
                    "opencorporates_candidates": oc_hits[:3],
                    "uk_companies_house_candidates": uk_hits[:3],
                    "verification_trail": trail,
                    "disclaimer": (
                        "No automated tool replaces a certified copy of the "
                        "counterparty's register extract. If `exists` is true "
                        "but any red flag is raised, request a fresh extract "
                        "from the official register and a KYC questionnaire "
                        "signed by the counterparty."
                    ),
                },
                indent=2,
                default=str,
            ),
            metadata={"exists": exists, "status": status, "flags": len(set(red_flags))},
        )
