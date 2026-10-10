"""Map an exception to a structured failure_code."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

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
    # Configuration, before the provider rules. An unrecognised model id used
    # to fall through to the degradation chain and answer from whichever
    # provider had a credential, so a typo in an agent's model returned a
    # perfectly good reply from a model nobody asked for.
    (
        r"unknown\s+model|unrecognised\s+model|unrecognized\s+model",
        "CONFIG_UNKNOWN_MODEL",
    ),
    # Our own limits come before the provider rule, whose bare "rate limit" also matches them
    (
        r"\brate_limited\b|by its rate limit|rate.?limit\s*\(per-|rate.?limit.*\buser\b"
        r"|too\s*many\s*requests\s*from|over its limits",
        "RATE_LIMITED",
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
    (r"stopped by a kill switch", "KILL_SWITCH"),
    (r"not on the allowed list for .* risk", "MODEL_NOT_ALLOWED"),
    # Tool layer
    (r"tool.*not.*found|unknown\s+tool", "TOOL_NOT_FOUND"),
    (r"toolerror|tool.*error|tool.*exception", "TOOL_ERROR"),
    # Budget / quota
    (r"budget|quota|insufficient.*credit|spending\s+limit", "BUDGET_EXCEEDED"),
    # Infra
    (r"connection\s*(refused|reset)|broken.*pipe|server\s*disconnect", "INFRA_CRASH"),
    # a rejected LLM credential is a configuration problem, not a cluster one
    (
        r"authentication_error|oauth access token|invalid.*api[ _-]?key|incorrect api key|api key.*(invalid|revoked|expired)",
        "LLM_AUTH_ERROR",
    ),
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
    tenant_id: str = "",
) -> None:
    # Counter inc and gauge dec are split into independent try blocks so a
    # failure in one never silently nukes the other. Earlier the whole
    # thing was wrapped in `try/except: pass`, which is what put both
    # counters at zero for weeks.
    try:
        from app.core.telemetry import (
            execution_outcomes_total,
            executions_completed_total,
            executions_failed_total,
        )

        execution_outcomes_total.labels(
            outcome=outcome,
            failure_code=failure_code,
            agent_type=agent_type,
        ).inc()
        status_label = "success" if outcome == "SUCCESS" else "failed"
        executions_completed_total.labels(status=status_label).inc()
        if outcome != "SUCCESS":
            executions_failed_total.labels(failure_code=failure_code or "UNKNOWN").inc()
    except Exception as e:
        logger.warning("emit_outcome_metric counter inc failed: %s", e)

    if tenant_id:
        try:
            from app.core.telemetry import active_executions

            active_executions.labels(tenant_id=tenant_id).dec()
        except Exception as e:
            logger.warning("emit_outcome_metric active_executions.dec failed: %s", e)


def emit_started_metric(agent_type: str = "agent") -> None:
    try:
        from app.core.telemetry import executions_started_total

        executions_started_total.labels(agent_type=agent_type).inc()
    except Exception as e:
        logger.warning("emit_started_metric failed: %s", e)
