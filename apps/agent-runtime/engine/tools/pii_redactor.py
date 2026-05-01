"""PII Redactor — detect and redact personally identifiable information."""
from __future__ import annotations
import json
import re
from typing import Any
from engine.tools.base import BaseTool, ToolResult

PII_PATTERNS = {
    "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "***-**-****"),
    "credit_card": (r"\b(?:\d[ -]*?){13,19}\b", "****-****-****-****"),
    "email": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL REDACTED]"),
    "phone": (r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b", "[PHONE REDACTED]"),
    "ip_address": (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[IP REDACTED]"),
    "date_of_birth": (r"\b(?:0[1-9]|1[0-2])[/-](?:0[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b", "[DOB REDACTED]"),
}

class PIIRedactorTool(BaseTool):
    name = "pii_redactor"
    description = "Detect and redact PII (SSN, credit cards, emails, phone numbers, IPs, dates of birth) from text. Supports mask, hash, and remove strategies."
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to scan for PII"},
            "strategy": {"type": "string", "enum": ["mask", "remove", "detect_only"], "default": "mask"},
            "entity_types": {"type": "array", "items": {"type": "string"}, "description": "PII types to detect. Default: all types."},
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        raw_text = arguments.get("text")
        text = str(raw_text) if raw_text is not None else ""
        if not text:
            return ToolResult(content=json.dumps(
                {"redacted_text": "", "detections": [], "detection_count": 0, "strategy_applied": "mask"}
            ))

        strategy = arguments.get("strategy", "mask")
        entity_types = arguments.get("entity_types") or list(PII_PATTERNS.keys())

        detections = []
        redacted = text

        for pii_type in entity_types:
            if pii_type not in PII_PATTERNS:
                continue
            pattern, mask_str = PII_PATTERNS[pii_type]
            for match in re.finditer(pattern, text):
                matched = match.group()
                preview = matched[:2] + "***" + matched[-2:] if len(matched) > 4 else "***"
                detections.append({
                    "type": pii_type,
                    "value": preview,
                    "start": match.start(),
                    "end": match.end(),
                })
                if strategy == "mask":
                    redacted = redacted.replace(matched, mask_str)
                elif strategy == "remove":
                    redacted = redacted.replace(matched, "")

        return ToolResult(content=json.dumps({
            "redacted_text": redacted if strategy != "detect_only" else text,
            "detections": detections,
            "detection_count": len(detections),
            "strategy_applied": strategy,
        }))
