"""Address normalisation — split a free-text address into a structured"""

from __future__ import annotations

import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

_US_STATES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}
_COUNTRY_HINTS = {
    "USA": "US",
    "UNITED STATES": "US",
    "U.S.": "US",
    "U.S.A.": "US",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "ENGLAND": "GB",
    "SCOTLAND": "GB",
    "WALES": "GB",
    "GERMANY": "DE",
    "DEUTSCHLAND": "DE",
    "FRANCE": "FR",
    "ITALY": "IT",
    "SPAIN": "ES",
    "NETHERLANDS": "NL",
    "CANADA": "CA",
    "AUSTRALIA": "AU",
    "JAPAN": "JP",
    "INDIA": "IN",
    "UAE": "AE",
    "U.A.E.": "AE",
    "EMIRATES": "AE",
}

_US_ZIP = re.compile(r"\b(\d{5})(?:-?\d{4})?\b")
_UK_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.IGNORECASE)
_CA_POSTCODE = re.compile(r"\b([A-Z]\d[A-Z][\s-]?\d[A-Z]\d)\b", re.IGNORECASE)
_NUMERIC_POSTCODE = re.compile(r"\b(\d{4,6})\b")


def _normalize(raw: str) -> dict[str, Any]:
    address = raw.strip()
    if not address:
        return {"input": raw, "valid": False, "reason": "empty"}

    # Split on commas first; that handles 80% of pasted addresses.
    parts = [p.strip() for p in address.split(",") if p.strip()]
    parsed: dict[str, Any] = {
        "input": raw,
        "country": None,
        "postal_code": None,
        "state": None,
        "city": None,
        "street": None,
    }

    # Country detection — last comma-segment OR any all-caps country word.
    if parts:
        tail = parts[-1].upper().strip(".")
        for k, v in _COUNTRY_HINTS.items():
            if k in tail or tail == v:
                parsed["country"] = v
                parts.pop()
                break

    # Postal code — try US, UK, Canada, then any 4-6 digit run.
    pc_match = _UK_POSTCODE.search(address)
    if pc_match and (parsed["country"] in (None, "GB")):
        parsed["postal_code"] = pc_match.group(1).upper().replace("  ", " ")
        if parsed["country"] is None:
            parsed["country"] = "GB"
    if not parsed["postal_code"]:
        ca = _CA_POSTCODE.search(address)
        if ca and (parsed["country"] in (None, "CA")):
            parsed["postal_code"] = (
                ca.group(1).upper().replace("-", " ").replace("  ", " ")
            )
            if parsed["country"] is None:
                parsed["country"] = "CA"
    if not parsed["postal_code"]:
        us = _US_ZIP.search(address)
        if us and (parsed["country"] in (None, "US")):
            parsed["postal_code"] = us.group(1)
            if parsed["country"] is None:
                parsed["country"] = "US"
    if not parsed["postal_code"]:
        m = _NUMERIC_POSTCODE.search(address)
        if m:
            parsed["postal_code"] = m.group(1)

    # State (US only, last segment word like "CA", "NY", possibly with zip).
    for p in reversed(parts):
        for token in p.split():
            tok = token.strip(",.").upper()
            if tok in _US_STATES:
                parsed["state"] = tok
                if parsed["country"] is None:
                    parsed["country"] = "US"
                break
        if parsed["state"]:
            break

    # City: the comma-segment before the state/postal block.
    if len(parts) >= 2:
        # Strip postal/state tokens from the candidate city
        city_candidate = parts[-1]
        if parsed["state"] and parsed["state"] in city_candidate.upper():
            # state lives at the end — city is the segment before
            city_candidate = parts[-2] if len(parts) >= 2 else ""
        else:
            city_candidate = parts[-1]
        # Strip trailing postal code from city
        city_clean = re.sub(r"\b\d{4,5}(-\d{4})?\b", "", city_candidate).strip(", ")
        # also strip US state code
        city_clean = re.sub(
            rf"\b({'|'.join(_US_STATES)})\b", "", city_clean, flags=re.IGNORECASE
        ).strip(", ")
        parsed["city"] = city_clean or None

    # Street: everything before the city
    street_parts = parts[:-1] if parsed["city"] else parts
    if street_parts:
        parsed["street"] = ", ".join(street_parts).strip()

    # Canonical line
    canonical_parts = [
        parsed.get("street"),
        parsed.get("city"),
        " ".join(filter(None, [parsed.get("state"), parsed.get("postal_code")])),
        parsed.get("country"),
    ]
    parsed["canonical"] = ", ".join(p for p in canonical_parts if p)
    parsed["valid"] = bool(parsed["street"] or parsed["city"] or parsed["postal_code"])
    return parsed


class AddressNormalizeTool(BaseTool):
    name = "address_normalize"
    description = (
        "Parse a free-text address into structured fields (street, city, "
        "state, postal_code, country) and emit a canonical single-line "
        "form. US/UK/CA/EU heuristics. Useful as a pre-step to geocoding "
        "or for deduplication."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "address": {
                "type": ["string", "array"],
                "description": "A single address string OR an array of address strings (batch mode).",
            },
        },
        "required": ["address"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        a = arguments.get("address")
        if isinstance(a, list):
            results = [_normalize(s if isinstance(s, str) else "") for s in a]
            lines = [f"Address normalize — {len(results)} input(s)"]
            for r in results[:20]:
                lines.append(f"  {r.get('canonical') or '(unparsed)'}")
            return ToolResult(content="\n".join(lines), metadata={"results": results})
        if not isinstance(a, str):
            return ToolResult(
                content="address must be a string or array of strings", is_error=True
            )
        r = _normalize(a)
        lines = [
            f"Address normalize — {a}",
            f"  Canonical: {r.get('canonical')}",
            f"  Street:    {r.get('street')}",
            f"  City:      {r.get('city')}",
            f"  State:     {r.get('state')}",
            f"  Postal:    {r.get('postal_code')}",
            f"  Country:   {r.get('country')}",
        ]
        return ToolResult(content="\n".join(lines), metadata=r)
