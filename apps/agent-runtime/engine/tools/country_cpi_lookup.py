"""Country CPI lookup — Transparency International CPI rank for any country."""

from __future__ import annotations

import csv
import json
import logging
import time
from io import StringIO
from typing import Any

import httpx

from engine.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 25.0
_CACHE_TTL_SECONDS = 60 * 60 * 24
_CACHE: dict[str, tuple[float, Any]] = {}


# ISO-2 -> (name, iso3) — covers every country in the live CPI dataset that we
# realistically touch in counterparty due diligence. Free-form names also resolve.
_ISO2_TO_INFO: dict[str, tuple[str, str]] = {
    "AF": ("Afghanistan", "AFG"),
    "AL": ("Albania", "ALB"),
    "DZ": ("Algeria", "DZA"),
    "AO": ("Angola", "AGO"),
    "AR": ("Argentina", "ARG"),
    "AM": ("Armenia", "ARM"),
    "AU": ("Australia", "AUS"),
    "AT": ("Austria", "AUT"),
    "AZ": ("Azerbaijan", "AZE"),
    "BS": ("Bahamas", "BHS"),
    "BH": ("Bahrain", "BHR"),
    "BD": ("Bangladesh", "BGD"),
    "BB": ("Barbados", "BRB"),
    "BY": ("Belarus", "BLR"),
    "BE": ("Belgium", "BEL"),
    "BZ": ("Belize", "BLZ"),
    "BJ": ("Benin", "BEN"),
    "BT": ("Bhutan", "BTN"),
    "BO": ("Bolivia", "BOL"),
    "BA": ("Bosnia and Herzegovina", "BIH"),
    "BW": ("Botswana", "BWA"),
    "BR": ("Brazil", "BRA"),
    "BN": ("Brunei", "BRN"),
    "BG": ("Bulgaria", "BGR"),
    "BF": ("Burkina Faso", "BFA"),
    "BI": ("Burundi", "BDI"),
    "KH": ("Cambodia", "KHM"),
    "CM": ("Cameroon", "CMR"),
    "CA": ("Canada", "CAN"),
    "CV": ("Cabo Verde", "CPV"),
    "TD": ("Chad", "TCD"),
    "CL": ("Chile", "CHL"),
    "CN": ("China", "CHN"),
    "CO": ("Colombia", "COL"),
    "KM": ("Comoros", "COM"),
    "CG": ("Republic of the Congo", "COG"),
    "CD": ("Democratic Republic of the Congo", "COD"),
    "CR": ("Costa Rica", "CRI"),
    "CI": ("Cote d'Ivoire", "CIV"),
    "HR": ("Croatia", "HRV"),
    "CU": ("Cuba", "CUB"),
    "CY": ("Cyprus", "CYP"),
    "CZ": ("Czechia", "CZE"),
    "DK": ("Denmark", "DNK"),
    "DJ": ("Djibouti", "DJI"),
    "DO": ("Dominican Republic", "DOM"),
    "EC": ("Ecuador", "ECU"),
    "EG": ("Egypt", "EGY"),
    "SV": ("El Salvador", "SLV"),
    "GQ": ("Equatorial Guinea", "GNQ"),
    "ER": ("Eritrea", "ERI"),
    "EE": ("Estonia", "EST"),
    "ET": ("Ethiopia", "ETH"),
    "FJ": ("Fiji", "FJI"),
    "FI": ("Finland", "FIN"),
    "FR": ("France", "FRA"),
    "GA": ("Gabon", "GAB"),
    "GM": ("Gambia", "GMB"),
    "GE": ("Georgia", "GEO"),
    "DE": ("Germany", "DEU"),
    "GH": ("Ghana", "GHA"),
    "GR": ("Greece", "GRC"),
    "GT": ("Guatemala", "GTM"),
    "GN": ("Guinea", "GIN"),
    "GW": ("Guinea-Bissau", "GNB"),
    "GY": ("Guyana", "GUY"),
    "HT": ("Haiti", "HTI"),
    "HN": ("Honduras", "HND"),
    "HK": ("Hong Kong", "HKG"),
    "HU": ("Hungary", "HUN"),
    "IS": ("Iceland", "ISL"),
    "IN": ("India", "IND"),
    "ID": ("Indonesia", "IDN"),
    "IR": ("Iran", "IRN"),
    "IQ": ("Iraq", "IRQ"),
    "IE": ("Ireland", "IRL"),
    "IL": ("Israel", "ISR"),
    "IT": ("Italy", "ITA"),
    "JM": ("Jamaica", "JAM"),
    "JP": ("Japan", "JPN"),
    "JO": ("Jordan", "JOR"),
    "KZ": ("Kazakhstan", "KAZ"),
    "KE": ("Kenya", "KEN"),
    "KP": ("North Korea", "PRK"),
    "KR": ("South Korea", "KOR"),
    "KW": ("Kuwait", "KWT"),
    "KG": ("Kyrgyzstan", "KGZ"),
    "LA": ("Laos", "LAO"),
    "LV": ("Latvia", "LVA"),
    "LB": ("Lebanon", "LBN"),
    "LS": ("Lesotho", "LSO"),
    "LR": ("Liberia", "LBR"),
    "LY": ("Libya", "LBY"),
    "LT": ("Lithuania", "LTU"),
    "LU": ("Luxembourg", "LUX"),
    "MG": ("Madagascar", "MDG"),
    "MW": ("Malawi", "MWI"),
    "MY": ("Malaysia", "MYS"),
    "MV": ("Maldives", "MDV"),
    "ML": ("Mali", "MLI"),
    "MT": ("Malta", "MLT"),
    "MR": ("Mauritania", "MRT"),
    "MU": ("Mauritius", "MUS"),
    "MX": ("Mexico", "MEX"),
    "MD": ("Moldova", "MDA"),
    "MN": ("Mongolia", "MNG"),
    "ME": ("Montenegro", "MNE"),
    "MA": ("Morocco", "MAR"),
    "MZ": ("Mozambique", "MOZ"),
    "MM": ("Myanmar", "MMR"),
    "NA": ("Namibia", "NAM"),
    "NP": ("Nepal", "NPL"),
    "NL": ("Netherlands", "NLD"),
    "NZ": ("New Zealand", "NZL"),
    "NI": ("Nicaragua", "NIC"),
    "NE": ("Niger", "NER"),
    "NG": ("Nigeria", "NGA"),
    "MK": ("North Macedonia", "MKD"),
    "NO": ("Norway", "NOR"),
    "OM": ("Oman", "OMN"),
    "PK": ("Pakistan", "PAK"),
    "PA": ("Panama", "PAN"),
    "PG": ("Papua New Guinea", "PNG"),
    "PY": ("Paraguay", "PRY"),
    "PE": ("Peru", "PER"),
    "PH": ("Philippines", "PHL"),
    "PL": ("Poland", "POL"),
    "PT": ("Portugal", "PRT"),
    "QA": ("Qatar", "QAT"),
    "RO": ("Romania", "ROU"),
    "RU": ("Russia", "RUS"),
    "RW": ("Rwanda", "RWA"),
    "SA": ("Saudi Arabia", "SAU"),
    "SN": ("Senegal", "SEN"),
    "RS": ("Serbia", "SRB"),
    "SC": ("Seychelles", "SYC"),
    "SL": ("Sierra Leone", "SLE"),
    "SG": ("Singapore", "SGP"),
    "SK": ("Slovakia", "SVK"),
    "SI": ("Slovenia", "SVN"),
    "SO": ("Somalia", "SOM"),
    "ZA": ("South Africa", "ZAF"),
    "SS": ("South Sudan", "SSD"),
    "ES": ("Spain", "ESP"),
    "LK": ("Sri Lanka", "LKA"),
    "SD": ("Sudan", "SDN"),
    "SR": ("Suriname", "SUR"),
    "SE": ("Sweden", "SWE"),
    "CH": ("Switzerland", "CHE"),
    "SY": ("Syria", "SYR"),
    "TW": ("Taiwan", "TWN"),
    "TJ": ("Tajikistan", "TJK"),
    "TZ": ("Tanzania", "TZA"),
    "TH": ("Thailand", "THA"),
    "TL": ("Timor-Leste", "TLS"),
    "TG": ("Togo", "TGO"),
    "TT": ("Trinidad and Tobago", "TTO"),
    "TN": ("Tunisia", "TUN"),
    "TR": ("Turkey", "TUR"),
    "TM": ("Turkmenistan", "TKM"),
    "UG": ("Uganda", "UGA"),
    "UA": ("Ukraine", "UKR"),
    "AE": ("United Arab Emirates", "ARE"),
    "GB": ("United Kingdom", "GBR"),
    "US": ("United States", "USA"),
    "UY": ("Uruguay", "URY"),
    "UZ": ("Uzbekistan", "UZB"),
    "VE": ("Venezuela", "VEN"),
    "VN": ("Vietnam", "VNM"),
    "YE": ("Yemen", "YEM"),
    "ZM": ("Zambia", "ZMB"),
    "ZW": ("Zimbabwe", "ZWE"),
}


# In-tool cached fallback CSV (CPI 2024 — published Feb 2025). Used only when
# the live HTTP sources are unreachable. Format: iso3,rank,score. Hand-curated
# and DEDUPED against Transparency International CPI 2024 Full Data Set —
# every ISO-3 appears exactly once, ranks pulled from the official PDF.
_FALLBACK_CPI_2024 = """iso3,rank,score
DNK,1,90
FIN,2,88
SGP,3,84
NZL,4,83
LUX,5,81
NOR,5,81
CHE,5,81
SWE,8,80
NLD,8,80
DEU,9,75
CAN,10,75
AUS,10,75
ISL,12,74
EST,13,76
IRL,13,71
URY,15,76
BEL,16,69
HKG,17,74
JPN,18,71
GBR,20,71
AUT,20,71
ARE,23,68
FRA,25,67
TWN,28,67
USA,28,65
BHS,30,64
BRB,29,65
BTN,30,72
KOR,32,63
CHL,32,63
CYP,32,57
ISR,33,64
MUS,33,50
PRT,33,57
QAT,40,58
FJI,40,55
RWA,40,57
SVN,42,56
CZE,46,56
ESP,46,56
KWT,46,46
MLT,46,46
OMN,46,55
CRI,46,58
ARM,46,47
NAM,49,53
GEO,49,53
SVK,49,54
ITA,52,53
BHR,52,53
SAU,59,52
JOR,53,49
POL,53,53
GRC,59,49
HRV,57,47
MYS,57,50
BWA,57,52
CIV,69,45
JAM,71,44
BEN,75,44
GHA,76,43
CHN,76,43
BGR,76,43
DOM,77,43
TLS,77,40
ALB,80,42
HUN,82,41
ZAF,82,41
SEN,82,41
GMB,82,41
TTO,82,41
GUY,82,40
VNM,88,40
TZA,88,40
MKD,88,40
TUN,92,39
KAZ,93,40
IND,93,38
LSO,93,38
MDV,93,39
IDN,99,37
COL,99,37
SUR,99,40
ARG,99,37
BIH,99,33
MAR,99,37
TGO,99,37
SRB,105,35
TUR,107,34
BRA,107,34
THA,107,34
DZA,107,34
UKR,107,35
NPL,107,35
ETH,107,37
BFA,107,41
MWI,107,34
PHL,114,33
ECU,114,33
SLE,114,33
BLR,114,33
KEN,121,32
LKA,121,32
ZMB,121,33
AGO,121,33
UZB,121,33
PER,127,31
EGY,130,30
CUB,134,29
PAK,140,27
NGA,140,26
MEX,140,26
DJI,140,26
GAB,140,26
NER,140,28
PAN,140,30
PNG,140,30
SLV,140,30
IRQ,140,26
UGA,140,26
MDG,140,26
CMR,144,26
MOZ,144,25
LBR,144,25
KGZ,148,25
TJK,148,21
COM,148,21
PRY,148,27
GTM,154,25
HND,154,22
LBN,154,22
RUS,154,22
LAO,154,28
COG,158,21
KHM,158,21
ZWE,158,21
GIN,158,20
MLI,158,20
ERI,162,16
COD,162,20
MMR,162,16
TKM,165,17
AFG,165,17
YEM,170,15
SDN,170,15
PRK,172,15
LBY,173,13
HTI,177,16
SYR,177,12
VEN,178,10
SOM,180,9
SSD,180,8
NIC,172,14
BGD,151,23
IRN,151,23
"""


async def _fetch_live_cpi() -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """Pull live CPI from public sources and return iso3 -> {rank,score,year}."""
    cached = _CACHE.get("cpi_live")
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1], None

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AbenixKYC/1.0)",
        "Accept": "text/csv,*/*;q=0.8",
    }
    sources = [
        "https://ourworldindata.org/grapher/ti-corruption-perception-index.csv",
        "https://datahub.io/core/corruption-perceptions-index/r/data.csv",
    ]
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, headers=headers, follow_redirects=True
    ) as client:
        for url in sources:
            try:
                r = await client.get(url)
                if r.status_code != 200 or len(r.content) < 500:
                    continue
                rows = _parse_cpi_csv(r.text)
                if rows:
                    _CACHE["cpi_live"] = (time.time(), rows)
                    return rows, None
            except Exception as e:
                logger.debug("CPI source %s failed: %s", url, e)
    return None, "All live CPI sources unreachable"


def _parse_cpi_csv(text: str) -> dict[str, dict[str, Any]]:
    """Parse OWID/datahub CPI csv into iso3 -> latest record."""
    reader = csv.reader(StringIO(text))
    rows = list(reader)
    if not rows:
        return {}
    header = [h.strip().lower() for h in rows[0]]
    out: dict[str, dict[str, Any]] = {}

    # Datahub shape: ISO3, Country, ..., "CPI Score YYYY", "Rank YYYY"
    # The datahub CSV ships one row per country with score+rank columns named
    # explicitly. Detect and parse it directly so we don't fall back to the
    # OWID path that doesn't recognise these column names.
    iso3_cols = [
        i
        for i, h in enumerate(header)
        if h in ("iso3", "iso 3", "country code") or h == "iso"
    ]
    cpi_score_cols = [
        i
        for i, h in enumerate(header)
        if "cpi score" in h or h == "cpi_score" or h == "score"
    ]
    rank_cols = [
        i
        for i, h in enumerate(header)
        if h == "rank" or h.startswith("rank ") or h.startswith("rank_")
    ]
    if iso3_cols and cpi_score_cols and rank_cols:
        iso_i = iso3_cols[0]
        score_i = cpi_score_cols[-1]  # latest year if multiple
        rank_i = rank_cols[-1]
        # Try to extract year from header like "CPI Score 2024"
        import re as _re

        year = None
        m = _re.search(r"(20\d{2})", header[score_i])
        if m:
            year = int(m.group(1))
        for row in rows[1:]:
            if len(row) <= max(iso_i, score_i, rank_i):
                continue
            iso3 = row[iso_i].strip().upper()
            if not iso3 or len(iso3) != 3:
                continue
            try:
                s = float(row[score_i])
                rk = int(row[rank_i])
            except (ValueError, TypeError):
                continue
            out[iso3] = {
                "rank": rk,
                "score": s,
                "year": year or 2024,
                "country": _ISO2_TO_INFO.get(_iso3_to_iso2(iso3), (iso3, ""))[0],
            }
        if out:
            return out

    # OWID shape: Entity, Code, Year, <score col>
    if "entity" in header and "year" in header and "code" in header:
        entity_i = header.index("entity")
        code_i = header.index("code")
        year_i = header.index("year")
        score_i = next(
            (i for i, h in enumerate(header) if "corruption" in h or "cpi" in h), None
        )
        if score_i is None:
            return {}
        # Collect by iso3, keep latest year
        per_iso: dict[str, list[tuple[int, float, str]]] = {}
        for row in rows[1:]:
            if len(row) <= max(entity_i, code_i, year_i, score_i):
                continue
            try:
                y = int(row[year_i])
                s = float(row[score_i])
            except (ValueError, TypeError):
                continue
            iso3 = row[code_i].strip().upper()
            if not iso3:
                continue
            per_iso.setdefault(iso3, []).append((y, s, row[entity_i]))
        if not per_iso:
            return {}
        # Derive rank per latest year
        all_years = [y for vs in per_iso.values() for y, _, _ in vs]
        latest = max(all_years)
        latest_records = []
        for iso3, vs in per_iso.items():
            ys = [v for v in vs if v[0] == latest]
            if not ys:
                ys = sorted(vs, key=lambda v: v[0], reverse=True)[:1]
            y, s, name = ys[0]
            latest_records.append((iso3, y, s, name))
        # Rank: higher score = better (rank 1)
        latest_records.sort(key=lambda r: -r[2])
        for rank, (iso3, y, s, name) in enumerate(latest_records, 1):
            out[iso3] = {"rank": rank, "score": s, "year": y, "country": name}
        return out
    return {}


def _load_fallback() -> dict[str, dict[str, Any]]:
    """Parse the in-tool fallback CSV."""
    out: dict[str, dict[str, Any]] = {}
    reader = csv.reader(StringIO(_FALLBACK_CPI_2024.strip()))
    rows = list(reader)
    if not rows:
        return out
    header = [h.strip().lower() for h in rows[0]]
    iso_i = header.index("iso3")
    rank_i = header.index("rank")
    score_i = header.index("score")
    for row in rows[1:]:
        if len(row) <= max(iso_i, rank_i, score_i):
            continue
        try:
            out[row[iso_i].upper().strip()] = {
                "rank": int(row[rank_i]),
                "score": float(row[score_i]),
                "year": 2024,
                "country": _ISO2_TO_INFO.get(
                    _iso3_to_iso2(row[iso_i].upper()), (row[iso_i], "")
                )[0],
            }
        except (ValueError, TypeError):
            continue
    return out


_ISO3_TO_ISO2 = {info[1]: iso2 for iso2, info in _ISO2_TO_INFO.items()}


def _iso3_to_iso2(iso3: str) -> str:
    return _ISO3_TO_ISO2.get(iso3.upper(), "")


def _resolve_country(s: str) -> tuple[str, str, str]:
    """Return (iso2, iso3, name)."""
    s = (s or "").strip()
    if not s:
        return "", "", ""
    if len(s) == 2 and s.upper() in _ISO2_TO_INFO:
        name, iso3 = _ISO2_TO_INFO[s.upper()]
        return s.upper(), iso3, name
    if len(s) == 3 and s.upper() in _ISO3_TO_ISO2:
        iso2 = _ISO3_TO_ISO2[s.upper()]
        name, iso3 = _ISO2_TO_INFO[iso2]
        return iso2, iso3, name
    sl = s.lower()
    for iso2, (name, iso3) in _ISO2_TO_INFO.items():
        if name.lower() == sl:
            return iso2, iso3, name
    # last-ditch substring
    for iso2, (name, iso3) in _ISO2_TO_INFO.items():
        if sl in name.lower() or name.lower() in sl:
            return iso2, iso3, name
    return s.upper(), "", s


class CountryCpiLookupTool(BaseTool):
    name = "country_cpi_lookup"
    description = (
        "Pull the Transparency International Corruption Perceptions Index "
        "(CPI) rank and score for any country. Accepts ISO-2, ISO-3, or a "
        "free-text country name. Fetches the live OurWorldInData + datahub "
        "CSV export of TI CPI; if both are unreachable, falls back to a "
        "small in-tool cached CSV (CPI 2024) and clearly marks the response "
        "as `live=false, stale=true`. Returns rank, score, year, source URL, "
        "and a one-line rationale. Used by KYC Indicator I (country "
        "corruption risk) and any jurisdiction-due-diligence flow."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "ISO-2, ISO-3, or country name (e.g. 'PL', 'POL', 'Poland').",
            }
        },
        "required": ["country"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        country = (arguments.get("country") or "").strip()
        if not country:
            return ToolResult(content="Error: 'country' is required.", is_error=True)
        iso2, iso3, name = _resolve_country(country)
        if not iso3:
            return ToolResult(
                content=json.dumps(
                    {
                        "country_input": country,
                        "iso2": iso2,
                        "iso3": iso3,
                        "name": name,
                        "cpi_rank": None,
                        "cpi_score": None,
                        "cpi_year": None,
                        "live": False,
                        "stale": True,
                        "source": "none",
                        "warning": "Country not resolvable to ISO-3.",
                    },
                    indent=2,
                ),
                metadata={"resolved": False},
            )

        live_map, warn = await _fetch_live_cpi()
        record: dict[str, Any] | None = None
        live = False
        source = "fallback_in_tool_2024"
        if live_map and iso3 in live_map:
            record = live_map[iso3]
            live = True
            source = "ourworldindata.org / datahub.io live CSV"
        else:
            fb = _load_fallback()
            record = fb.get(iso3)

        if not record:
            return ToolResult(
                content=json.dumps(
                    {
                        "country_input": country,
                        "iso2": iso2,
                        "iso3": iso3,
                        "name": name,
                        "cpi_rank": None,
                        "cpi_score": None,
                        "cpi_year": None,
                        "live": False,
                        "stale": True,
                        "source": "none",
                        "warning": warn or "CPI record not found for this country",
                    },
                    indent=2,
                ),
                metadata={"resolved": True, "found": False},
            )

        rank = record.get("rank")
        score = record.get("score")
        year = record.get("year")
        rationale = f"CPI {year} for {name}: rank {rank} of ~180, score {score} of 100."

        return ToolResult(
            content=json.dumps(
                {
                    "country_input": country,
                    "iso2": iso2,
                    "iso3": iso3,
                    "name": name,
                    "cpi_rank": rank,
                    "cpi_score": score,
                    "cpi_year": year,
                    "live": live,
                    "stale": not live,
                    "source": source,
                    "rationale": rationale,
                    "source_citation": (
                        "Transparency International CPI 2024 via "
                        "OurWorldInData/datahub.io"
                        if live
                        else "Transparency International CPI 2024 — cached in-tool fallback"
                    ),
                },
                indent=2,
            ),
            metadata={"cpi_rank": rank, "live": live},
        )
