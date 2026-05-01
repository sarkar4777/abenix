"""Data Loss Prevention (DLP) — PII detection and masking for agent I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# PII detection patterns
PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "phone_us": re.compile(r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "ip_address": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_key": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*[\w/+=]{40}"),
    "generic_api_key": re.compile(
        r"(?i)(?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[\w-]{20,}['\"]?"
    ),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*"),
}

MASK_REPLACEMENTS = {
    "email": "[EMAIL_MASKED]",
    "phone_us": "[PHONE_MASKED]",
    "ssn": "[SSN_MASKED]",
    "credit_card": "[CARD_MASKED]",
    "ip_address": "[IP_MASKED]",
    "aws_access_key": "[AWS_KEY_MASKED]",
    "aws_secret_key": "[AWS_SECRET_MASKED]",
    "generic_api_key": "[API_KEY_MASKED]",
    "bearer_token": "[TOKEN_MASKED]",
}


@dataclass
class DLPResult:
    """Result of DLP scan."""

    has_pii: bool = False
    findings: list[dict[str, Any]] = field(default_factory=list)
    masked_text: str = ""
    original_text: str = ""
    mode: str = "detect"


@dataclass
class DLPPolicy:
    """DLP configuration for a tenant/agent."""

    mode: str = "detect"  # detect, mask, block
    enabled_patterns: list[str] = field(
        default_factory=lambda: list(PII_PATTERNS.keys())
    )
    custom_patterns: dict[str, str] = field(default_factory=dict)  # name → regex
    whitelist_patterns: list[str] = field(default_factory=list)  # patterns to skip


def scan_text(text: str, policy: DLPPolicy | None = None) -> DLPResult:
    """Scan text for PII using configured patterns.

    Returns DLPResult with findings and optionally masked text.
    """
    if not text:
        return DLPResult(original_text=text, masked_text=text)

    policy = policy or DLPPolicy()
    result = DLPResult(original_text=text, mode=policy.mode)
    masked = text

    # Built-in patterns
    for pattern_name, regex in PII_PATTERNS.items():
        if pattern_name not in policy.enabled_patterns:
            continue

        matches = regex.findall(text)
        if matches:
            result.has_pii = True
            for match in matches[:10]:  # Cap at 10 findings per pattern
                result.findings.append(
                    {
                        "type": pattern_name,
                        "value": match[:4] + "..." if len(match) > 4 else match,
                        "count": len(matches),
                    }
                )
            # Mask in text
            replacement = MASK_REPLACEMENTS.get(pattern_name, "[MASKED]")
            masked = regex.sub(replacement, masked)

    # Custom patterns
    for name, pattern_str in policy.custom_patterns.items():
        try:
            custom_re = re.compile(pattern_str)
            matches = custom_re.findall(text)
            if matches:
                result.has_pii = True
                result.findings.append(
                    {
                        "type": f"custom:{name}",
                        "count": len(matches),
                    }
                )
                masked = custom_re.sub(f"[{name.upper()}_MASKED]", masked)
        except re.error:
            pass  # Invalid regex, skip

    result.masked_text = masked
    return result


def enforce_dlp(text: str, policy: DLPPolicy | None = None) -> tuple[str, DLPResult]:
    """Apply DLP policy to text. Returns (processed_text, scan_result)."""
    result = scan_text(text, policy)

    if not result.has_pii:
        return text, result

    mode = (policy or DLPPolicy()).mode

    if mode == "block":
        pii_types = [f["type"] for f in result.findings]
        raise ValueError(
            f"DLP policy violation: PII detected ({', '.join(pii_types)}). "
            f"Execution blocked. Remove sensitive data and retry."
        )

    if mode == "mask":
        return result.masked_text, result

    # detect mode: pass through but flag
    return text, result
