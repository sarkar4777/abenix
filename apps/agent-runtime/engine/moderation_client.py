"""OpenAI Moderation API client + in-process policy evaluator."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENAI_MODERATION_URL = "https://api.openai.com/v1/moderations"
DEFAULT_MODEL = "omni-moderation-latest"

# Maximum characters we send to the provider. OpenAI moderation accepts
# up to ~32k tokens per call; we clip at 30_000 chars (~7500 tokens) to
# keep a single call safe without splitting.
MAX_INPUT_CHARS = 30_000


# Action strings that match the ModerationAction enum values. Duplicated
# as plain strings here so this module has zero DB-layer imports.
ACTION_ALLOW = "allow"
ACTION_FLAG = "flag"
ACTION_REDACT = "redact"
ACTION_BLOCK = "block"

# Severity order — most severe wins when multiple categories trigger.
_SEVERITY = {ACTION_ALLOW: 0, ACTION_FLAG: 1, ACTION_REDACT: 2, ACTION_BLOCK: 3}


@dataclass
class ModerationDecision:
    outcome: str = "allowed"  # allowed|flagged|redacted|blocked|error
    action: str = ACTION_ALLOW
    triggered_categories: list[str] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)
    flagged: bool = False
    reason: str = ""
    redacted_content: str | None = None
    latency_ms: int = 0
    provider_response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _pick_action(
    triggered: list[str],
    category_actions: dict[str, str],
    default_action: str,
) -> tuple[str, list[str]]:
    """Return (most-severe-action, categories-that-caused-it)."""
    if not triggered:
        return ACTION_ALLOW, []
    acts: dict[str, list[str]] = {}
    for cat in triggered:
        a = category_actions.get(cat, default_action)
        acts.setdefault(a, []).append(cat)
    best = max(acts.keys(), key=lambda a: _SEVERITY.get(a, 0))
    return best, acts[best]


async def _call_openai(
    content: str, model: str, timeout_s: float = 10.0
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    payload = {"input": content[:MAX_INPUT_CHARS], "model": model}
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(
            OPENAI_MODERATION_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json()


def _redact(content: str, patterns: list[str], mask: str) -> str:
    """Mask offending spans matched by custom regex patterns."""
    out = content
    for pat in patterns:
        try:
            out = re.sub(pat, mask, out, flags=re.IGNORECASE)
        except re.error:
            continue
    return out


def _custom_pattern_hit(content: str, patterns: list[str]) -> list[str]:
    """Return the list of patterns that matched the content."""
    hits = []
    for pat in patterns:
        try:
            if re.search(pat, content, flags=re.IGNORECASE):
                hits.append(pat)
        except re.error:
            continue
    return hits


async def evaluate(
    content: str,
    *,
    thresholds: dict[str, float] | None = None,
    default_threshold: float = 0.5,
    category_actions: dict[str, str] | None = None,
    default_action: str = ACTION_BLOCK,
    custom_patterns: list[str] | None = None,
    redaction_mask: str = "█████",
    model: str = DEFAULT_MODEL,
) -> ModerationDecision:
    """Run provider + custom-pattern check and return a decision."""
    thresholds = thresholds or {}
    category_actions = category_actions or {}
    custom_patterns = custom_patterns or []

    if not content or not content.strip():
        return ModerationDecision(outcome="allowed", action=ACTION_ALLOW)

    start = time.monotonic()
    decision = ModerationDecision()

    # 1. Custom-pattern check runs FIRST and is always authoritative.
    # A pattern match triggers default_action at 1.0 confidence.
    pattern_hits = _custom_pattern_hit(content, custom_patterns)
    pattern_triggered_categories = [f"custom:{i}" for i in range(len(pattern_hits))]

    # 2. Provider check.
    provider_body: dict[str, Any] = {}
    provider_triggered: list[str] = []
    provider_scores: dict[str, float] = {}
    flagged = False
    try:
        provider_body = await _call_openai(content, model=model)
        results = provider_body.get("results", [])
        if results:
            r0 = results[0]
            flagged = bool(r0.get("flagged"))
            provider_scores = dict(r0.get("category_scores", {}))
            categories = dict(r0.get("categories", {}))
            # A category "triggers" if its score exceeds its threshold,
            # OR if `flagged=true` (provider's own classification).
            for cat, score in provider_scores.items():
                thr = thresholds.get(cat, default_threshold)
                if score >= thr or categories.get(cat):
                    provider_triggered.append(cat)
    except Exception as e:
        decision.error = str(e)[:300]
        logger.warning("moderation provider error: %s", e)
        # Provider down — continue with pattern-only eval.

    decision.category_scores = provider_scores
    decision.flagged = flagged
    decision.provider_response = provider_body

    all_triggered = list(
        dict.fromkeys(provider_triggered + pattern_triggered_categories)
    )
    decision.triggered_categories = all_triggered

    # 3. Pick the worst action across all triggered categories.
    if not all_triggered:
        decision.action = ACTION_ALLOW
        decision.outcome = "error" if decision.error else "allowed"
    else:
        # Custom-pattern hits always use default_action.
        effective_actions = dict(category_actions)
        for cat in pattern_triggered_categories:
            effective_actions.setdefault(cat, default_action)
        action, acted = _pick_action(all_triggered, effective_actions, default_action)
        decision.action = action
        decision.triggered_categories = acted
        if action == ACTION_ALLOW:
            decision.outcome = "allowed"
        elif action == ACTION_FLAG:
            decision.outcome = "flagged"
        elif action == ACTION_REDACT:
            decision.outcome = "redacted"
            decision.redacted_content = _redact(
                content, custom_patterns, redaction_mask
            )
        elif action == ACTION_BLOCK:
            decision.outcome = "blocked"
        reasons = []
        if pattern_hits:
            reasons.append(f"custom_patterns[{','.join(pattern_hits[:3])}]")
        if provider_triggered:
            reasons.append(f"provider[{','.join(provider_triggered[:3])}]")
        decision.reason = " ".join(reasons) or "policy_triggered"

    decision.latency_ms = int((time.monotonic() - start) * 1000)
    return decision


def content_hash(content: str) -> str:
    """16-char SHA-256 prefix for dedup without storing full content."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:64]
