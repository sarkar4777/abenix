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


DLP_MODES = ("detect", "mask", "block")

_LABELS = {
    "email": "an email address",
    "phone_us": "a phone number",
    "ssn": "a social security number",
    "credit_card": "a card number",
    "ip_address": "an IP address",
    "aws_access_key": "an AWS key",
    "aws_secret_key": "an AWS secret",
    "generic_api_key": "an API key",
    "bearer_token": "a bearer token",
}


def policy_from_settings(raw: Any) -> DLPPolicy | None:
    """The tenant's settings.dlp as a policy, None when scanning is off."""
    if not isinstance(raw, dict) or raw.get("enabled") is False:
        return None
    mode = str(raw.get("mode") or "detect").lower()
    if mode not in DLP_MODES:
        mode = "detect"
    custom = raw.get("custom_patterns")
    return DLPPolicy(
        mode=mode, custom_patterns=custom if isinstance(custom, dict) else {}
    )


def describe_findings(result: DLPResult) -> str:
    kinds = list(dict.fromkeys(f["type"] for f in result.findings))
    words = [
        _LABELS.get(k, "a custom pattern" if k.startswith("custom:") else k)
        for k in kinds
    ]
    return ", ".join(words[:4]) or "personal data"


def input_blocked_message(result: DLPResult) -> str:
    return (
        f"This message was not sent because it contains {describe_findings(result)}. "
        "Your workspace's data protection setting blocks personal data. "
        "Remove it and try again."
    )


def output_blocked_message(result: DLPResult) -> str:
    return (
        f"The reply was withheld because it contained {describe_findings(result)}. "
        "Your workspace's data protection setting blocks personal data in answers."
    )


def apply(
    text: str, policy: DLPPolicy | None, *, source: str
) -> tuple[str, str, DLPResult]:
    """Apply the tenant mode. Returns (text, block message or "", scan)."""
    if policy is None or not text:
        return text, "", DLPResult(original_text=text, masked_text=text)
    result = scan_text(text, policy)
    if not result.has_pii or policy.mode == "detect":
        return text, "", result
    if policy.mode == "mask":
        return result.masked_text, "", result
    msg = (
        input_blocked_message(result)
        if source == "pre_llm"
        else output_blocked_message(result)
    )
    return text, msg, result


async def load_tenant_policy(db: Any, tenant_id: Any) -> DLPPolicy | None:
    """Read tenants.settings.dlp fresh, so a change applies to the next run."""
    import json

    from sqlalchemy import text

    raw = (
        await db.execute(
            text("SELECT settings->'dlp' FROM tenants WHERE id = CAST(:t AS uuid)"),
            {"t": str(tenant_id)},
        )
    ).scalar()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    return policy_from_settings(raw)


def apply_to_value(
    value: Any, policy: DLPPolicy | None, *, source: str = "post_llm"
) -> tuple[Any, str]:
    """Every string inside a dict or list gets the mode. Returns (value, block message)."""
    if policy is None or policy.mode not in ("mask", "block"):
        return value, ""
    if isinstance(value, str):
        out, blocked, _ = apply(value, policy, source=source)
        return out, blocked
    if isinstance(value, dict):
        res: dict[Any, Any] = {}
        for k, v in value.items():
            res[k], blocked = apply_to_value(v, policy, source=source)
            if blocked:
                return value, blocked
        return res, ""
    if isinstance(value, (list, tuple)):
        items = []
        for v in value:
            nv, blocked = apply_to_value(v, policy, source=source)
            if blocked:
                return value, blocked
            items.append(nv)
        return items, ""
    return value, ""


async def apply_to_pipeline_result(db: Any, tenant_id: Any, result: Any) -> None:
    """Mask or withhold a pipeline's final output per the tenant DLP mode."""
    if result is None or getattr(result, "final_output", None) is None or not tenant_id:
        return
    try:
        policy = await load_tenant_policy(db, tenant_id)
    except Exception:  # noqa: BLE001
        return
    out, blocked = apply_to_value(result.final_output, policy)
    result.final_output = blocked or out
