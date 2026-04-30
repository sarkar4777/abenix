"""Country-risk and jurisdiction-risk aggregator."""
from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from io import StringIO
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0
_CACHE_TTL_SECONDS = 60 * 60 * 24
_CRI_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Omit "br" so httpx can decode without needing the brotli package.
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
}


async def _fetch_with_wayback_fallback(
    url: str, prefer_latest_snapshot: bool = False,
) -> tuple[bytes | None, str | None]:
    """Fetch url directly; on 403/timeout, fall back to the Wayback Machine"""
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, follow_redirects=True, headers=_BROWSER_HEADERS,
    ) as client:
        if not prefer_latest_snapshot:
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.content, None
            except Exception:
                pass
        # Wayback Machine via the "latest HTTP-200" redirect shortcut `/web/2/`
        # which resolves server-side to the most recent snapshot; append id_
        # for raw content.
        try:
            direct_latest = f"https://web.archive.org/web/2id_/{url}"
            r = await client.get(direct_latest)
            if r.status_code == 200 and len(r.content) > 500:
                return r.content, "served via Wayback Machine (latest snapshot)"
        except Exception:
            pass
        # CDX fallback: find explicit latest 200 snapshot and follow id_.
        try:
            stripped = re.sub(r"^https?://", "", url)
            cdx = await client.get(
                "https://web.archive.org/cdx/search/cdx",
                params={
                    "url": stripped,
                    "limit": "-1",  # newest
                    "output": "json",
                    "filter": "statuscode:200",
                    "fl": "timestamp,original",
                },
            )
            if cdx.status_code == 200:
                data = cdx.json()
                if isinstance(data, list) and len(data) >= 2:
                    ts, orig = data[-1][0], data[-1][1]
                    snap = f"https://web.archive.org/web/{ts}id_/{orig}"
                    rr = await client.get(snap)
                    if rr.status_code == 200:
                        return rr.content, f"served via Wayback Machine snapshot {ts}"
        except Exception as exc:
            return None, f"direct fetch and Wayback both failed: {exc.__class__.__name__}"
        return None, f"{url} unreachable (direct blocked, no Wayback snapshot)"


# ISO 3166-1 alpha-2 → country name helpers (partial but covers our hot cases).
_ISO2_TO_NAME = {
    "AF": "Afghanistan", "AL": "Albania", "DZ": "Algeria", "AR": "Argentina", "AM": "Armenia",
    "AU": "Australia", "AT": "Austria", "AZ": "Azerbaijan", "BD": "Bangladesh", "BY": "Belarus",
    "BE": "Belgium", "BZ": "Belize", "BO": "Bolivia", "BA": "Bosnia and Herzegovina", "BR": "Brazil",
    "BG": "Bulgaria", "KH": "Cambodia", "CM": "Cameroon", "CA": "Canada", "KY": "Cayman Islands",
    "CL": "Chile", "CN": "China", "CO": "Colombia", "CD": "Democratic Republic of the Congo",
    "CR": "Costa Rica", "HR": "Croatia", "CU": "Cuba", "CY": "Cyprus", "CZ": "Czechia",
    "DK": "Denmark", "DO": "Dominican Republic", "EC": "Ecuador", "EG": "Egypt", "SV": "El Salvador",
    "EE": "Estonia", "FI": "Finland", "FR": "France", "GE": "Georgia", "DE": "Germany",
    "GH": "Ghana", "GR": "Greece", "GT": "Guatemala", "HT": "Haiti", "HN": "Honduras",
    "HK": "Hong Kong", "HU": "Hungary", "IS": "Iceland", "IN": "India", "ID": "Indonesia",
    "IR": "Iran", "IQ": "Iraq", "IE": "Ireland", "IL": "Israel", "IT": "Italy",
    "JM": "Jamaica", "JP": "Japan", "JO": "Jordan", "KZ": "Kazakhstan", "KE": "Kenya",
    "KP": "North Korea", "KR": "South Korea", "KW": "Kuwait", "LV": "Latvia", "LB": "Lebanon",
    "LY": "Libya", "LT": "Lithuania", "LU": "Luxembourg", "MY": "Malaysia", "MT": "Malta",
    "MX": "Mexico", "MD": "Moldova", "MN": "Mongolia", "ME": "Montenegro", "MA": "Morocco",
    "MM": "Myanmar", "NL": "Netherlands", "NZ": "New Zealand", "NI": "Nicaragua", "NG": "Nigeria",
    "MK": "North Macedonia", "NO": "Norway", "PK": "Pakistan", "PA": "Panama", "PY": "Paraguay",
    "PE": "Peru", "PH": "Philippines", "PL": "Poland", "PT": "Portugal", "QA": "Qatar",
    "RO": "Romania", "RU": "Russia", "SA": "Saudi Arabia", "RS": "Serbia", "SG": "Singapore",
    "SK": "Slovakia", "SI": "Slovenia", "SO": "Somalia", "ZA": "South Africa", "ES": "Spain",
    "LK": "Sri Lanka", "SD": "Sudan", "SE": "Sweden", "CH": "Switzerland", "SY": "Syria",
    "TW": "Taiwan", "TZ": "Tanzania", "TH": "Thailand", "TN": "Tunisia", "TR": "Turkey",
    "UG": "Uganda", "UA": "Ukraine", "AE": "United Arab Emirates", "GB": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan", "VE": "Venezuela", "VN": "Vietnam",
    "YE": "Yemen", "ZM": "Zambia", "ZW": "Zimbabwe",
}


def _resolve(country_input: str) -> tuple[str, str]:
    """(iso2, pretty_name)."""
    ci = country_input.strip()
    if len(ci) == 2 and ci.upper() in _ISO2_TO_NAME:
        return ci.upper(), _ISO2_TO_NAME[ci.upper()]
    # Fall back — find by name
    for iso, name in _ISO2_TO_NAME.items():
        if name.lower() == ci.lower():
            return iso, name
    return ci.upper(), ci


# Primary: OurWorldInData's maintained TI-CPI export (Entity, Code, Year,
# Corruption Perceptions Index). Fallback: datahub.io and TI's own CDN.
_CPI_SOURCES = [
    ("owid", "https://ourworldindata.org/grapher/ti-corruption-perception-index.csv"),
    ("datahub", "https://datahub.io/core/corruption-perceptions-index/r/data.csv"),
    ("ti_2024", "https://images.transparencycdn.org/images/CPI2024-Full-Data-Set.csv"),
    ("ti_2023", "https://images.transparencycdn.org/images/CPI2023-Full-Data-Set.csv"),
]


async def _fetch_cpi() -> tuple[list[dict[str, Any]], int | None, str | None]:
    """Returns (rows, latest_year, warning)."""
    cached = _CRI_CACHE.get("cpi")
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        rows, year = cached[1]  # type: ignore[misc]
        return rows, year, None

    for src_label, url in _CPI_SOURCES:
        content, warn = await _fetch_with_wayback_fallback(url)
        if not content:
            continue
        text = content.decode("utf-8", errors="ignore")
        try:
            parsed_rows, latest_year = _parse_cpi_csv(text, src_label)
        except Exception:
            continue
        if parsed_rows:
            _CRI_CACHE["cpi"] = (time.time(), (parsed_rows, latest_year))
            return parsed_rows, latest_year, warn
    _CRI_CACHE["cpi"] = (time.time(), ([], None))
    return [], None, "Transparency International CPI unreachable (OWID + datahub + TI CDN all failed)"


def _parse_cpi_csv(text: str, src_label: str) -> tuple[list[dict[str, Any]], int]:
    """Normalise the various CPI CSV shapes into a uniform row list:
    [{"country": "Poland", "iso3": "POL", "year": 2023, "score": 54, "rank": 47}, ...].
    """
    reader = csv.reader(StringIO(text))
    rows_raw = [r for r in reader if r]
    if not rows_raw:
        return [], 2023
    header = rows_raw[0]
    header_l = [h.strip().lower() for h in header]
    data = rows_raw[1:]

    normalized: list[dict[str, Any]] = []

    # OWID shape: Entity, Code, Year, <score col>, World region
    if "entity" in header_l and "year" in header_l:
        entity_i = header_l.index("entity")
        code_i = header_l.index("code") if "code" in header_l else None
        year_i = header_l.index("year")
        score_col = next((i for i, h in enumerate(header_l) if "corruption" in h), None)
        for row in data:
            try:
                y = int(row[year_i])
            except (ValueError, IndexError):
                continue
            score = None
            if score_col is not None and score_col < len(row):
                try:
                    score = float(row[score_col])
                except (ValueError, TypeError):
                    score = None
            normalized.append({
                "country": row[entity_i] if entity_i < len(row) else "",
                "iso3": row[code_i] if code_i is not None and code_i < len(row) else "",
                "year": y,
                "score": score,
                "rank": None,  # OWID carries score only; rank derived below
            })
        # Derive ranks per year from scores (higher score = lower rank num)
        years = sorted({r["year"] for r in normalized if r["year"]})
        latest = max(years) if years else 2023
        for y in years:
            yr_rows = sorted(
                [r for r in normalized if r["year"] == y and r["score"] is not None],
                key=lambda r: -(r["score"] or 0),
            )
            for i, r in enumerate(yr_rows, 1):
                r["rank"] = i
        return normalized, latest

    # TI direct CSV — columns like "CPI 2023 Score", "CPI 2023 Rank"
    score_cols = {h for h in header_l if "cpi score" in h}
    rank_cols = {h for h in header_l if "rank" in h}
    if score_cols and "country" in header_l:
        country_i = header_l.index("country") if "country" in header_l else 0
        iso3_i = header_l.index("iso3") if "iso3" in header_l else None
        latest = 2023
        for row in data:
            if len(row) <= country_i:
                continue
            for h_l in score_cols:
                m = re.search(r"(20\d{2})", h_l)
                if not m:
                    continue
                y = int(m.group(1))
                latest = max(latest, y)
                col_i = header_l.index(h_l)
                rank_col = next((i for i, rh in enumerate(header_l) if "rank" in rh and str(y) in rh), None)
                try:
                    score = float(row[col_i]) if row[col_i] else None
                except (ValueError, IndexError):
                    score = None
                try:
                    rank = int(float(row[rank_col])) if rank_col is not None and row[rank_col] else None
                except (ValueError, IndexError):
                    rank = None
                normalized.append({
                    "country": row[country_i],
                    "iso3": row[iso3_i] if iso3_i is not None and iso3_i < len(row) else "",
                    "year": y,
                    "score": score,
                    "rank": rank,
                })
        return normalized, latest

    # datahub shape: Jurisdiction, 1998, 1999, ..., last column = latest
    if "jurisdiction" in header_l:
        year_cols = [(i, int(h)) for i, h in enumerate(header) if h.strip().isdigit()]
        if year_cols:
            latest_year = max(y for _, y in year_cols)
            for row in data:
                if not row:
                    continue
                country = row[0]
                for col_i, yr in year_cols:
                    try:
                        val = float(row[col_i]) if col_i < len(row) and row[col_i] not in ("-", "") else None
                    except ValueError:
                        val = None
                    normalized.append({
                        "country": country,
                        "iso3": "",
                        "year": yr,
                        "score": val,
                        "rank": None,
                    })
            return normalized, latest_year

    return [], 2023


def _cpi_lookup(rows: list[dict[str, Any]], year: int | None, iso2: str, name: str) -> dict[str, Any] | None:
    """Find the row for this country in the normalized CPI rows."""
    if not rows:
        return None
    target_year = year or max(r.get("year", 0) for r in rows) or 2023
    name_lc = name.lower()
    iso3_hint = _ISO2_TO_ISO3.get(iso2.upper())

    candidates = [
        r for r in rows
        if r.get("year") == target_year and (
            r.get("country", "").lower() == name_lc
            or (iso3_hint and r.get("iso3", "").upper() == iso3_hint)
        )
    ]
    if not candidates:
        # Try any year if target year absent
        candidates = [
            r for r in rows
            if r.get("country", "").lower() == name_lc
            or (iso3_hint and r.get("iso3", "").upper() == iso3_hint)
        ]
    if not candidates:
        return None
    # Prefer most recent year with a score
    candidates = sorted(
        candidates,
        key=lambda r: (r.get("year") or 0, r.get("score") is not None),
        reverse=True,
    )
    best = candidates[0]
    return {
        "cpi_score": best.get("score"),
        "cpi_rank": best.get("rank"),
        "cpi_year": best.get("year"),
        "raw": best,
    }


# ISO-2 to ISO-3 (subset — sufficient for the country list we support)
_ISO2_TO_ISO3 = {
    "AF": "AFG", "AL": "ALB", "DZ": "DZA", "AR": "ARG", "AM": "ARM",
    "AU": "AUS", "AT": "AUT", "AZ": "AZE", "BD": "BGD", "BY": "BLR",
    "BE": "BEL", "BZ": "BLZ", "BO": "BOL", "BA": "BIH", "BR": "BRA",
    "BG": "BGR", "KH": "KHM", "CM": "CMR", "CA": "CAN", "KY": "CYM",
    "CL": "CHL", "CN": "CHN", "CO": "COL", "CD": "COD", "CR": "CRI",
    "HR": "HRV", "CU": "CUB", "CY": "CYP", "CZ": "CZE", "DK": "DNK",
    "DO": "DOM", "EC": "ECU", "EG": "EGY", "SV": "SLV", "EE": "EST",
    "FI": "FIN", "FR": "FRA", "GE": "GEO", "DE": "DEU", "GH": "GHA",
    "GR": "GRC", "GT": "GTM", "HT": "HTI", "HN": "HND", "HK": "HKG",
    "HU": "HUN", "IS": "ISL", "IN": "IND", "ID": "IDN", "IR": "IRN",
    "IQ": "IRQ", "IE": "IRL", "IL": "ISR", "IT": "ITA", "JM": "JAM",
    "JP": "JPN", "JO": "JOR", "KZ": "KAZ", "KE": "KEN", "KP": "PRK",
    "KR": "KOR", "KW": "KWT", "LV": "LVA", "LB": "LBN", "LY": "LBY",
    "LT": "LTU", "LU": "LUX", "MY": "MYS", "MT": "MLT", "MX": "MEX",
    "MD": "MDA", "MN": "MNG", "ME": "MNE", "MA": "MAR", "MM": "MMR",
    "NL": "NLD", "NZ": "NZL", "NI": "NIC", "NG": "NGA", "MK": "MKD",
    "NO": "NOR", "PK": "PAK", "PA": "PAN", "PY": "PRY", "PE": "PER",
    "PH": "PHL", "PL": "POL", "PT": "PRT", "QA": "QAT", "RO": "ROU",
    "RU": "RUS", "SA": "SAU", "RS": "SRB", "SG": "SGP", "SK": "SVK",
    "SI": "SVN", "SO": "SOM", "ZA": "ZAF", "ES": "ESP", "LK": "LKA",
    "SD": "SDN", "SE": "SWE", "CH": "CHE", "SY": "SYR", "TW": "TWN",
    "TZ": "TZA", "TH": "THA", "TN": "TUN", "TR": "TUR", "UG": "UGA",
    "UA": "UKR", "AE": "ARE", "GB": "GBR", "US": "USA", "UY": "URY",
    "UZ": "UZB", "VE": "VEN", "VN": "VNM", "YE": "YEM", "ZM": "ZMB",
    "ZW": "ZWE",
}


def _parse_num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_FATF_HIGH_RISK_URL = "https://www.fatf-gafi.org/en/publications/High-risk-and-other-monitored-jurisdictions/Call-for-action-November-2023.html"
_FATF_MONITORED_URL = "https://www.fatf-gafi.org/en/publications/High-risk-and-other-monitored-jurisdictions/Increased-monitoring-October-2024.html"


_FATF_LANDING = "https://www.fatf-gafi.org/en/countries/black-and-grey-lists.html"


async def _fetch_fatf_lists() -> tuple[dict[str, list[str]], str | None]:
    """Scrape FATF high-risk (black) and monitored (grey) lists."""
    cached = _CRI_CACHE.get("fatf")
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1], None  # type: ignore[return-value]
    out: dict[str, list[str]] = {"black": [], "grey": []}
    warnings: list[str] = []
    content, warn = await _fetch_with_wayback_fallback(_FATF_LANDING)
    if warn:
        warnings.append(f"FATF: {warn}")
    if not content:
        _CRI_CACHE["fatf"] = (time.time(), out)
        return out, "; ".join(warnings) or "FATF unreachable"
    html = content.decode("utf-8", errors="ignore")
    for sec_label, bucket in (
        (r"[Cc]all\s+for\s+[Aa]ction", "black"),
        (r"[Ii]ncreased\s+[Mm]onitoring", "grey"),
    ):
        sec_match = re.search(sec_label + r"(.{0,12000})", html, re.DOTALL)
        if not sec_match:
            continue
        segment = sec_match.group(1)
        for m in re.finditer(
            r"<(?:h[234]|strong|b|li|a)[^>]*>\s*([A-Z][A-Za-z\u00C0-\u017F \(\)\-']{2,40})\s*</",
            segment,
        ):
            cand = m.group(1).strip().rstrip("()").strip()
            if cand in _ISO2_TO_NAME.values() and cand not in out[bucket]:
                out[bucket].append(cand)
    _CRI_CACHE["fatf"] = (time.time(), out)
    return out, warn if not (out["black"] or out["grey"]) else None


_EU_TAX_LIST_URL = "https://www.consilium.europa.eu/en/policies/eu-list-of-non-cooperative-jurisdictions/"


async def _fetch_eu_tax_blacklist() -> tuple[list[str], str | None]:
    """Scrape the EU Council's current Annex I non-cooperative jurisdictions list.

    Cloudflare-protected — routed through Wayback fallback.
    """
    cached = _CRI_CACHE.get("eu_tax")
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1], None  # type: ignore[return-value]
    countries: list[str] = []
    content, warn = await _fetch_with_wayback_fallback(_EU_TAX_LIST_URL)
    if not content:
        return [], warn or "EU Council page unreachable"
    html = content.decode("utf-8", errors="ignore")
    anx = re.search(r"Annex\s+I.{0,8000}", html, re.DOTALL | re.IGNORECASE)
    segment = anx.group(0) if anx else html
    for m in re.finditer(r"<li[^>]*>\s*([A-Z][A-Za-z\u00C0-\u017F \(\)\-']{2,40})\s*</li>", segment):
        cand = m.group(1).strip()
        if cand in _ISO2_TO_NAME.values() and cand not in countries:
            countries.append(cand)
    _CRI_CACHE["eu_tax"] = (time.time(), countries)
    return countries, warn if not countries else None


async def _fetch_wgi(iso2: str) -> dict[str, Any]:
    """Worldwide Governance Indicators — CC, RL, RQ percentile ranks."""
    # ISO2 -> ISO3 mapping would be ideal; WB accepts ISO3 best. Best-effort.
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            r = await client.get(
                f"https://api.worldbank.org/v2/country/{iso2}/indicator/CC.PER.RNK?format=json&mrnev=1",
            )
            if r.status_code != 200:
                return {}
            data = r.json()
            if isinstance(data, list) and len(data) > 1 and data[1]:
                cc = data[1][0].get("value")
            else:
                cc = None
            r2 = await client.get(
                f"https://api.worldbank.org/v2/country/{iso2}/indicator/RL.PER.RNK?format=json&mrnev=1",
            )
            rl = None
            if r2.status_code == 200:
                d2 = r2.json()
                if isinstance(d2, list) and len(d2) > 1 and d2[1]:
                    rl = d2[1][0].get("value")
            r3 = await client.get(
                f"https://api.worldbank.org/v2/country/{iso2}/indicator/RQ.PER.RNK?format=json&mrnev=1",
            )
            rq = None
            if r3.status_code == 200:
                d3 = r3.json()
                if isinstance(d3, list) and len(d3) > 1 and d3[1]:
                    rq = d3[1][0].get("value")
    except Exception:
        return {}
    return {
        "control_of_corruption_percentile_rank": cc,
        "rule_of_law_percentile_rank": rl,
        "regulatory_quality_percentile_rank": rq,
    }


_OFAC_PROGRAMS_URL = "https://ofac.treasury.gov/sanctions-programs-and-country-information"


async def _fetch_ofac_country_programs(iso2: str, country_name: str) -> list[str]:
    """Live scrape of the OFAC sanctions-programs-and-country-information page."""
    cached = _CRI_CACHE.get("ofac_programs")
    html = None
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        html = cached[1]  # type: ignore[assignment]
    else:
        content, _ = await _fetch_with_wayback_fallback(_OFAC_PROGRAMS_URL)
        if content:
            html = content.decode("utf-8", errors="ignore")
            _CRI_CACHE["ofac_programs"] = (time.time(), html)
    if not html:
        return []
    programs: list[str] = []
    # Each country row on the OFAC page is typically:
    # <td>Country Name</td>...<td>programme / ... </td>
    # We match by country name in any link or cell and grab the nearest programme label.
    name_lower = country_name.lower()
    # Look for sections containing the country name.
    for block in re.finditer(r"<(?:tr|div)[^>]*>(.{20,2000}?)</(?:tr|div)>", html, re.DOTALL):
        segment = block.group(1)
        if name_lower in segment.lower():
            for m in re.finditer(r"<a[^>]+href=\"([^\"]+sanctions?[^\"]*)\"[^>]*>([^<]{3,120})</a>", segment, re.IGNORECASE):
                label = re.sub(r"\s+", " ", m.group(2)).strip()
                if label and label.lower() != country_name.lower() and label not in programs:
                    programs.append(label)
    return programs[:10]


def _met_indicator_i_score(cpi_rank: float | None) -> tuple[int, str]:
    """MET Indicator I rubric — map CPI rank to a numeric score."""
    if cpi_rank is None:
        return 10, "CPI rank unknown — default mid-band"
    r = int(cpi_rank)
    if r <= 20:
        return 2, f"CPI rank {r} — very low corruption"
    if r <= 40:
        return 5, f"CPI rank {r} — low corruption"
    if r <= 60:
        return 7, f"CPI rank {r} — moderate corruption (e.g. Poland, Spain, Italy)"
    if r <= 80:
        return 10, f"CPI rank {r} — elevated corruption"
    if r <= 100:
        return 13, f"CPI rank {r} — high corruption"
    if r <= 120:
        return 17, f"CPI rank {r} — very high corruption"
    if r <= 140:
        return 20, f"CPI rank {r} — severe corruption"
    return 25, f"CPI rank {r} — extreme corruption"


class CountryRiskIndexTool(BaseTool):
    name = "country_risk_index"
    description = (
        "Aggregate every major public country-risk signal into a single "
        "structured view. Fused indices: Transparency International CPI "
        "(180-country corruption perceptions, used directly as MET Indicator "
        "I), Basel AML Index (0-10 ML/TF risk), FATF grey & black lists "
        "(jurisdictions under increased monitoring + call-for-action), EU "
        "Annex I non-cooperative tax jurisdictions, OECD AEOI participants, "
        "World Bank Worldwide Governance Indicators (Control of Corruption, "
        "Rule of Law, Regulatory Quality percentile ranks), OFAC country "
        "programmes (comprehensive vs. selective), US State Dept travel "
        "advisories 1-4, Global Peace Index 1-5. Outputs: `cpi_rank`, "
        "`cpi_score`, FATF classification (clear / grey / black), sanctions "
        "regime, WGI percentiles, an L/M/H jurisdiction risk grade, and an "
        "already-computed MET-style Indicator I score. Accepts ISO 3166-1 "
        "alpha-2 codes or country names. Cached 24h per country. Used by "
        "KYC onboarding, sanctions compliance, tax-team jurisdiction "
        "reviews, supply-chain geo-risk, trade credit insurance, export "
        "licence decisions, and any Enhanced Due Diligence that needs a "
        "jurisdiction-risk rationale."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 code (e.g. 'PL', 'GB', 'IR') OR full country name.",
            },
            "signals": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["cpi", "fatf", "eu_tax", "wgi", "ofac", "all"],
                },
                "description": "Subset of signals to fetch; 'all' by default.",
            },
        },
        "required": ["country"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        country = (arguments.get("country") or "").strip()
        if not country:
            return ToolResult(content="Error: 'country' is required.", is_error=True)

        signals = arguments.get("signals") or ["all"]
        want_all = "all" in signals

        iso2, name = _resolve(country)

        cpi_data: dict[str, Any] = {}
        fatf_data: dict[str, list[str]] = {"black": [], "grey": []}
        eu_list: list[str] = []
        wgi: dict[str, Any] = {}
        ofac_programs: list[str] = []
        warnings: list[str] = []

        if want_all or "cpi" in signals:
            rows, cpi_year, cpi_warn = await _fetch_cpi()
            if cpi_warn:
                warnings.append(cpi_warn)
            hit = _cpi_lookup(rows, cpi_year, iso2, name)
            if hit:
                cpi_data = hit

        if want_all or "fatf" in signals:
            fatf_data, fatf_warn = await _fetch_fatf_lists()
            if fatf_warn:
                warnings.append(fatf_warn)

        if want_all or "eu_tax" in signals:
            eu_list, eu_warn = await _fetch_eu_tax_blacklist()
            if eu_warn:
                warnings.append(eu_warn)

        if want_all or "wgi" in signals:
            wgi = await _fetch_wgi(iso2)
            if not wgi:
                warnings.append(f"World Bank WGI: no data for {iso2}")

        if want_all or "ofac" in signals:
            ofac_programs = await _fetch_ofac_country_programs(iso2, name)

        cpi_rank = cpi_data.get("cpi_rank")
        indicator_i_score, indicator_i_explanation = _met_indicator_i_score(cpi_rank)

        fatf_status = "clear"
        if name in fatf_data.get("black", []):
            fatf_status = "black"
        elif name in fatf_data.get("grey", []):
            fatf_status = "grey"

        # Overall jurisdiction risk grade
        _ORDER = {"L": 0, "M": 1, "H": 2}
        def _elevate(cur: str, to: str) -> str:
            return to if _ORDER[to] > _ORDER[cur] else cur

        reasons: list[str] = []
        grade = "L"
        if ofac_programs and any("comprehensive" in p.lower() for p in ofac_programs):
            grade = _elevate(grade, "H"); reasons.append("Under comprehensive OFAC sanctions")
        elif ofac_programs:
            grade = _elevate(grade, "M"); reasons.append(f"Subject to {len(ofac_programs)} OFAC sanctions programme(s)")
        if fatf_status == "black":
            grade = _elevate(grade, "H"); reasons.append("FATF call-for-action jurisdiction")
        elif fatf_status == "grey":
            grade = _elevate(grade, "M"); reasons.append("FATF grey-list jurisdiction")
        if name in eu_list:
            grade = _elevate(grade, "M"); reasons.append("EU non-cooperative tax jurisdiction")
        cc = wgi.get("control_of_corruption_percentile_rank")
        if isinstance(cc, (int, float)) and cc < 30:
            grade = _elevate(grade, "H"); reasons.append(f"Low control-of-corruption percentile ({cc:.0f})")
        elif isinstance(cc, (int, float)) and cc < 50:
            grade = _elevate(grade, "M"); reasons.append(f"Moderate control-of-corruption percentile ({cc:.0f})")
        if cpi_rank and cpi_rank > 100:
            grade = _elevate(grade, "M"); reasons.append(f"CPI rank {int(cpi_rank)} indicates elevated corruption perception")

        if not reasons:
            reasons.append("No significant jurisdiction risk signal detected")

        return ToolResult(
            content=json.dumps({
                "iso2": iso2,
                "country_name": name,
                "cpi_rank": cpi_rank,
                "cpi_score": cpi_data.get("cpi_score"),
                "cpi_year": cpi_data.get("cpi_year"),
                "fatf_status": fatf_status,
                "fatf_black_list": fatf_data.get("black", []),
                "fatf_grey_list": fatf_data.get("grey", []),
                "eu_non_cooperative_tax": name in eu_list,
                "ofac_country_programs": ofac_programs,
                "wgi": wgi,
                "met_indicator_i_score": indicator_i_score,
                "met_indicator_i_explanation": indicator_i_explanation,
                "jurisdiction_risk_grade": grade,
                "jurisdiction_risk_reasons": reasons,
                "sanctions_applicable_for_standard_check": bool(ofac_programs) or fatf_status == "black",
                "warnings": warnings,
                "disclaimer": (
                    "Country-risk signals are composite and approximate. A "
                    "jurisdiction marked 'clear' can still contain specific "
                    "sanctioned persons and entities — always combine with "
                    "the `sanctions_screening` tool for the counterparty."
                ),
            }, indent=2, default=str),
            metadata={"grade": grade, "fatf": fatf_status},
        )
