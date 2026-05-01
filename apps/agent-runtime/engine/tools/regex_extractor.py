"""Pattern matching and data extraction via regular expressions."""

from __future__ import annotations

import json
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult

PRESET_PATTERNS: dict[str, str] = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "url": r"https?://[^\s<>\"')\]]+",
    "phone_us": r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
    "phone_intl": r"\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "date_us": r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    "date_iso": r"\b\d{4}-\d{2}-\d{2}\b",
    "currency_usd": r"\$[\d,]+(?:\.\d{1,2})?",
    "percentage": r"\d+(?:\.\d+)?%",
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "zipcode_us": r"\b\d{5}(?:-\d{4})?\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "hex_color": r"#[0-9A-Fa-f]{6}\b",
    "uuid": r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    "ppa_price": r"\$\s?[\d.]+\s*/\s*(?:MWh|kWh|MW|kW)",
    "energy_capacity": r"\d+(?:\.\d+)?\s*(?:MW|GW|kW|MWh|GWh|kWh)",
    "contract_reference": r"(?:Section|Article|Clause|Schedule|Appendix|Exhibit)\s+[\d.]+(?:\([a-z]\))?",
}


class RegexExtractorTool(BaseTool):
    name = "regex_extractor"
    description = (
        "Extract data from text using regular expressions. Supports custom regex "
        "patterns and preset patterns for common data types: email, url, phone, "
        "ip_address, date_us, date_iso, currency_usd, percentage, uuid, "
        "ppa_price, energy_capacity, contract_reference. Can also search/replace, "
        "split text, and validate patterns."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to search in",
            },
            "operation": {
                "type": "string",
                "enum": ["extract", "extract_preset", "replace", "split", "validate", "list_presets"],
                "description": "Regex operation",
                "default": "extract",
            },
            "pattern": {
                "type": "string",
                "description": "Custom regex pattern",
            },
            "preset": {
                "type": "string",
                "description": "Preset pattern name (e.g. 'email', 'currency_usd', 'ppa_price')",
            },
            "presets": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Multiple preset patterns to extract at once",
            },
            "replacement": {
                "type": "string",
                "description": "Replacement string for replace operation",
            },
            "flags": {
                "type": "array",
                "items": {"type": "string", "enum": ["ignorecase", "multiline", "dotall"]},
                "description": "Regex flags",
            },
            "group": {
                "type": "integer",
                "description": "Capture group number to extract (default: 0 = full match)",
                "default": 0,
            },
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        operation = arguments.get("operation", "extract")

        if operation == "list_presets":
            return ToolResult(
                content=json.dumps(
                    {name: pattern for name, pattern in PRESET_PATTERNS.items()},
                    indent=2,
                ),
            )

        if not text:
            return ToolResult(content="Error: text is required", is_error=True)

        ops = {
            "extract": self._extract,
            "extract_preset": self._extract_preset,
            "replace": self._replace,
            "split": self._split,
            "validate": self._validate,
        }

        fn = ops.get(operation)
        if not fn:
            return ToolResult(content=f"Unknown operation: {operation}", is_error=True)

        try:
            result = fn(text, arguments)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"operation": operation})
        except re.error as e:
            return ToolResult(content=f"Invalid regex pattern: {e}", is_error=True)
        except Exception as e:
            return ToolResult(content=f"Regex error: {e}", is_error=True)

    def _get_flags(self, flags_list: list[str]) -> int:
        flags = 0
        flag_map = {
            "ignorecase": re.IGNORECASE,
            "multiline": re.MULTILINE,
            "dotall": re.DOTALL,
        }
        for f in flags_list:
            flags |= flag_map.get(f, 0)
        return flags

    def _extract(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern", "")
        preset = args.get("preset", "")

        if preset and preset in PRESET_PATTERNS:
            pattern = PRESET_PATTERNS[preset]
        elif not pattern:
            return {"error": "pattern or preset is required"}

        flags = self._get_flags(args.get("flags", []))
        group = args.get("group", 0)

        matches = []
        for m in re.finditer(pattern, text, flags):
            try:
                match_val = m.group(group)
            except IndexError:
                match_val = m.group(0)

            matches.append({
                "match": match_val,
                "start": m.start(),
                "end": m.end(),
                "groups": list(m.groups()) if m.groups() else [],
            })

        return {
            "pattern": pattern,
            "match_count": len(matches),
            "matches": matches[:100],
            "unique_values": list(set(m["match"] for m in matches))[:50],
        }

    def _extract_preset(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        presets = args.get("presets", [])
        preset = args.get("preset", "")

        if preset and not presets:
            presets = [preset]

        if not presets:
            presets = list(PRESET_PATTERNS.keys())

        results: dict[str, Any] = {}
        for name in presets:
            pattern = PRESET_PATTERNS.get(name)
            if not pattern:
                results[name] = {"error": f"Unknown preset: {name}"}
                continue

            matches = re.findall(pattern, text, re.IGNORECASE)
            unique = list(set(matches))
            if unique:
                results[name] = {"count": len(matches), "unique": unique[:30]}

        return {"extracted": results, "presets_used": presets}

    def _replace(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern", "")
        replacement = args.get("replacement", "")
        flags = self._get_flags(args.get("flags", []))

        if not pattern:
            return {"error": "pattern is required"}

        result, count = re.subn(pattern, replacement, text, flags=flags)
        return {
            "original_length": len(text),
            "result_length": len(result),
            "replacements_made": count,
            "result": result[:10000],
        }

    def _split(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern", "")
        flags = self._get_flags(args.get("flags", []))

        if not pattern:
            return {"error": "pattern is required"}

        parts = re.split(pattern, text, flags=flags)
        return {
            "pattern": pattern,
            "part_count": len(parts),
            "parts": [p.strip() for p in parts if p.strip()][:100],
        }

    def _validate(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"error": "pattern is required"}

        try:
            compiled = re.compile(pattern)
            full_match = bool(compiled.fullmatch(text))
            partial_match = bool(compiled.search(text))
            return {
                "pattern": pattern,
                "full_match": full_match,
                "partial_match": partial_match,
                "pattern_groups": compiled.groups,
            }
        except re.error as e:
            return {"error": f"Invalid pattern: {e}"}
