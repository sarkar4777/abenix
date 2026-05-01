"""Map an exception to a structured failure_code."""

from __future__ import annotations

import re

# Order matters — first match wins. Regexes are case-insensitive on the
# exception's message + class name combined.
_RULES: list[tuple[str, str]] = [
    # Stale-sweeper messages — match FIRST because the message shape
    # ("stuck in RUNNING for >N minutes") would otherwise hit the
    # timeout rule below.
    (
        r"stuck\s+in\s+running|sweep.*backfill|owning\s+process\s+likely\s+crashed",
        "STALE_SWEEP",
    ),
    # LLM provider errors
    (r"rate.?limit|429|too\s*many", "LLM_RATE_LIMIT"),
    (
        r"anthropic.*(error|exception)|openai.*(error|exception)|gemini.*(error|exception)",
        "LLM_PROVIDER_ERROR",
    ),
    (r"json.*decode|invalid.*response|expecting\s+value", "LLM_INVALID_RESPONSE"),
    # Sandbox / k8s
    (r"oom\s*kill|memory\s*limit\s*exceeded", "SANDBOX_OOM"),
    (r"deadline\s*exceeded|timeout|timed\s*out", "SANDBOX_TIMEOUT"),
    (r"exit\s*code\s*[1-9]|non.?zero.*exit", "SANDBOX_NONZERO_EXIT"),
    (r"image.*not.*allow|allow.?list", "SANDBOX_IMAGE_BLOCKED"),
    # Moderation — match BEFORE the generic tool-error rule so a
    # ModerationBlocked exception is classified by policy, not by the
    # fact that it raised from a tool context.
    (
        r"moderation\s*blocked|policy\s*triggered|content\s*violation",
        "MODERATION_BLOCKED",
    ),
    # Tool layer
    (r"tool.*not.*found|unknown\s+tool", "TOOL_NOT_FOUND"),
    (r"toolerror|tool.*error|tool.*exception", "TOOL_ERROR"),
    # Budget / quota
    (r"budget|quota|insufficient.*credit", "BUDGET_EXCEEDED"),
    (r"rate.?limit.*user|too.*many.*requests", "RATE_LIMITED"),
    # Infra
    (r"connection\s*(refused|reset)|broken.*pipe|server\s*disconnect", "INFRA_CRASH"),
    (r"unauthorized|forbidden|401|403", "INFRA_AUTH_ERROR"),
]


def classify_exception(exc: BaseException | str | None) -> str:
    """Return a stable failure code for the given exception or message."""
    if exc is None:
        return "UNKNOWN_ERROR"
    text = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    text_l = (text or "").lower()
    for pattern, code in _RULES:
        if re.search(pattern, text_l):
            return code
    return "UNKNOWN_ERROR"


def emit_outcome_metric(
    *,
    outcome: str,
    failure_code: str = "",
    agent_type: str = "agent",
) -> None:
    """Push an outcome to Prometheus. Centralizes the label contract so
    every catch site emits identical labels."""
    try:
        from app.core.telemetry import execution_outcomes_total

        execution_outcomes_total.labels(
            outcome=outcome,
            failure_code=failure_code,
            agent_type=agent_type,
        ).inc()
    except Exception:
        pass
