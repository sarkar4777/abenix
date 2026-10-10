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
ACTION_HOLD = "hold"
ACTION_BLOCK = "block"

# Severity order — most severe wins when multiple categories trigger.
_SEVERITY = {
    ACTION_ALLOW: 0,
    ACTION_FLAG: 1,
    ACTION_REDACT: 2,
    ACTION_HOLD: 3,
    ACTION_BLOCK: 4,
}

# provider categories carry no offsets, a hold asks the provider about each sentence
MAX_LOCATE_SENTENCES = 40


@dataclass
class ModerationDecision:
    outcome: str = "allowed"  # allowed|flagged|redacted|held|blocked|error
    action: str = ACTION_ALLOW
    triggered_categories: list[str] = field(default_factory=list)
    category_scores: dict[str, float] = field(default_factory=dict)
    flagged: bool = False
    reason: str = ""
    redacted_content: str | None = None
    latency_ms: int = 0
    provider_response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # [{"start", "end", "category"}] over the evaluated text
    spans: list[dict[str, Any]] = field(default_factory=list)


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
    content: str | list[str], model: str, timeout_s: float = 10.0
) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    clipped: Any
    if isinstance(content, list):
        each = MAX_INPUT_CHARS // max(1, len(content))
        clipped = [c[:each] for c in content]
    else:
        clipped = content[:MAX_INPUT_CHARS]
    payload = {"input": clipped, "model": model}
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


_CARD_SHAPE = r"\d{4}[-\s]?){3}\d{4}"


def _luhn_ok(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _real_matches(pat: str, content: str) -> list[re.Match]:
    # a card-number pattern only counts when the digits pass the Luhn check, ids and counts rarely do
    found = list(re.finditer(pat, content, flags=re.IGNORECASE))
    if _CARD_SHAPE in pat:
        found = [m for m in found if _luhn_ok(m.group())]
    return found


def _redact(content: str, patterns: list[Any], mask: str) -> str:
    """Mask offending spans matched by custom regex patterns."""
    out = content
    for pat in patterns:
        # Back-compat: legacy DB rows may hold `{"pattern": "X", ...}` dicts.
        # The router now rejects this shape at the edge but rows created
        # during the bug window must still evaluate cleanly.
        pat = pat.get("pattern") if isinstance(pat, dict) else pat
        if not isinstance(pat, str):
            continue
        try:
            for m in reversed(_real_matches(pat, out)):
                out = out[: m.start()] + mask + out[m.end() :]
        except re.error:
            continue
    return out


def pattern_spans(content: str, patterns: list[Any]) -> list[dict[str, Any]]:
    """Where each custom pattern matched, labelled custom:<pattern index>."""
    out: list[dict[str, Any]] = []
    for i, pat in enumerate(patterns or []):
        pat = pat.get("pattern") if isinstance(pat, dict) else pat
        if not isinstance(pat, str):
            continue
        try:
            for m in _real_matches(pat, content):
                if m.end() > m.start():
                    out.append(
                        {"start": m.start(), "end": m.end(), "category": f"custom:{i}"}
                    )
        except re.error:
            continue
    return out


def merge_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorted spans with overlaps joined, categories kept."""
    ordered = sorted(
        (s for s in spans if int(s.get("end", 0)) > int(s.get("start", 0))),
        key=lambda s: (int(s["start"]), int(s["end"])),
    )
    merged: list[dict[str, Any]] = []
    for s in ordered:
        start, end = int(s["start"]), int(s["end"])
        cats = [c for c in str(s.get("category") or "").split(",") if c]
        if merged and start <= merged[-1]["end"]:
            last = merged[-1]
            last["end"] = max(last["end"], end)
            last["cats"].extend(c for c in cats if c not in last["cats"])
            continue
        merged.append({"start": start, "end": end, "cats": list(cats)})
    return [
        {"start": m["start"], "end": m["end"], "category": ",".join(m["cats"])}
        for m in merged
    ]


def mask_spans(content: str, spans: list[dict[str, Any]], mask: str) -> str:
    """The text with every span replaced by the mask."""
    if not content or not spans:
        return content or ""
    out = content
    for s in reversed(merge_spans(spans)):
        start = max(0, min(len(out), int(s["start"])))
        end = max(start, min(len(out), int(s["end"])))
        out = out[:start] + mask + out[end:]
    return out


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*\s*")


def _sentences(content: str) -> list[tuple[int, int]]:
    found = [
        (m.start(), m.end())
        for m in _SENTENCE.finditer(content)
        if content[m.start() : m.end()].strip()
    ]
    return found or [(0, len(content))]


async def locate_provider_spans(
    content: str,
    categories: list[str],
    *,
    thresholds: dict[str, float],
    default_threshold: float,
    model: str,
    localize: bool,
) -> list[dict[str, Any]]:
    """Spans for provider categories, the whole text unless a per-sentence check narrows it."""
    if not categories:
        return []
    whole = [{"start": 0, "end": len(content), "category": ",".join(categories)}]
    if not localize:
        return whole
    parts = _sentences(content)
    if len(parts) < 2 or len(parts) > MAX_LOCATE_SENTENCES:
        return whole
    try:
        body = await _call_openai([content[a:b] for a, b in parts], model=model)
        results = body.get("results") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("moderation span lookup failed: %s", type(e).__name__)
        return whole
    if len(results) != len(parts):
        return whole
    found: list[dict[str, Any]] = []
    for (a, b), r in zip(parts, results):
        scores = r.get("category_scores") or {}
        flags = r.get("categories") or {}
        hit = [
            c
            for c in categories
            if flags.get(c)
            or float(scores.get(c, 0.0)) >= thresholds.get(c, default_threshold)
        ]
        if hit:
            found.append({"start": a, "end": b, "category": ",".join(hit)})
    return found or whole


def _custom_pattern_hit(content: str, patterns: list[Any]) -> list[str]:
    """Return the list of patterns that matched the content."""
    hits = []
    for pat in patterns:
        # Back-compat: legacy DB rows may hold `{"pattern": "X", ...}` dicts.
        # The router now rejects this shape at the edge but rows created
        # during the bug window must still evaluate cleanly.
        pat = pat.get("pattern") if isinstance(pat, dict) else pat
        if not isinstance(pat, str):
            continue
        try:
            if _real_matches(pat, content):
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
    found_spans = pattern_spans(content, custom_patterns)
    # custom:N is the policy's Nth pattern, the index /moderation labels it by
    pattern_triggered_categories = list(
        dict.fromkeys(s["category"] for s in found_spans)
    )

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
        elif action == ACTION_HOLD:
            decision.outcome = "held"
        elif action == ACTION_BLOCK:
            decision.outcome = "blocked"
        reasons = []
        if pattern_hits:
            reasons.append(f"custom_patterns[{','.join(pattern_hits[:3])}]")
        if provider_triggered:
            reasons.append(f"provider[{','.join(provider_triggered[:3])}]")
        decision.reason = " ".join(reasons) or "policy_triggered"
        if action != ACTION_ALLOW:
            provider_acted = [c for c in acted if not c.startswith("custom:")]
            decision.spans = merge_spans(
                [s for s in found_spans if s["category"] in acted]
                + await locate_provider_spans(
                    content,
                    provider_acted,
                    thresholds=thresholds,
                    default_threshold=default_threshold,
                    model=model,
                    localize=action in (ACTION_HOLD, ACTION_REDACT),
                )
            )
        if action == ACTION_REDACT:
            # provider categories are masked like pattern matches, by span
            decision.redacted_content = mask_spans(
                content,
                list(decision.spans) + pattern_spans(content, custom_patterns),
                redaction_mask,
            )

    decision.latency_ms = int((time.monotonic() - start) * 1000)
    return decision


def event_provider_response(decision: ModerationDecision) -> dict[str, Any]:
    """What an event row keeps, plus where a redact masked the text."""
    out = dict(decision.provider_response or {})
    if decision.outcome == "redacted" and decision.spans:
        out["_masked_spans"] = [
            {
                "start": int(s["start"]),
                "end": int(s["end"]),
                "category": str(s.get("category") or ""),
            }
            for s in decision.spans
        ]
    return out


def content_hash(content: str) -> str:
    """16-char SHA-256 prefix for dedup without storing full content."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:64]
