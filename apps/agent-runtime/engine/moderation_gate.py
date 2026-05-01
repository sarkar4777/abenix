"""Policy gate — non-bypassable content moderation wired into AgentExecutor."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from engine.moderation_client import (
    ACTION_ALLOW,
    ACTION_BLOCK,
    ACTION_REDACT,
    ModerationDecision,
    content_hash,
    evaluate,
)

logger = logging.getLogger(__name__)


@dataclass
class GateConfig:
    """Snapshot of a tenant's ModerationPolicy — passed to the executor."""

    policy_id: str = ""
    tenant_id: str = ""
    user_id: str = ""
    pre_llm: bool = True
    post_llm: bool = True
    on_tool_output: bool = False
    provider_model: str = "omni-moderation-latest"
    thresholds: dict = field(default_factory=dict)
    default_threshold: float = 0.5
    category_actions: dict = field(default_factory=dict)
    default_action: str = ACTION_BLOCK
    custom_patterns: list = field(default_factory=list)
    redaction_mask: str = "█████"
    fail_closed: bool = False  # Block on provider error
    # Optional sink: called with (source, decision, content_preview).
    # The api-side caller wires this to persist ModerationEvent rows.
    event_sink: Callable[..., None] | None = None


class ModerationBlocked(Exception):
    """Raised by the gate when a BLOCK action is returned."""

    def __init__(self, decision: ModerationDecision, source: str, content_preview: str):
        self.decision = decision
        self.source = source
        self.content_preview = content_preview
        super().__init__(
            f"Moderation blocked ({source}): {decision.reason or 'policy_triggered'}"
        )


async def check(
    content: str,
    *,
    source: str,
    config: GateConfig | None,
    execution_id: str = "",
) -> tuple[str, ModerationDecision]:
    """Run the gate. Return (possibly-redacted-content, decision)."""
    if config is None:
        return content, ModerationDecision(outcome="allowed", action=ACTION_ALLOW)

    # Skip this hook if the policy says "don't check here".
    if source == "pre_llm" and not config.pre_llm:
        return content, ModerationDecision(outcome="allowed", action=ACTION_ALLOW)
    if source == "post_llm" and not config.post_llm:
        return content, ModerationDecision(outcome="allowed", action=ACTION_ALLOW)
    if source == "tool_output" and not config.on_tool_output:
        return content, ModerationDecision(outcome="allowed", action=ACTION_ALLOW)

    decision = await evaluate(
        content,
        thresholds=config.thresholds,
        default_threshold=config.default_threshold,
        category_actions=config.category_actions,
        default_action=config.default_action,
        custom_patterns=config.custom_patterns,
        redaction_mask=config.redaction_mask,
        model=config.provider_model,
    )

    # Fail-closed override: if the provider errored AND the tenant
    # insists on strict mode, escalate to a block.
    if decision.outcome == "error" and config.fail_closed:
        decision.outcome = "blocked"
        decision.action = ACTION_BLOCK
        decision.reason = "provider_error_fail_closed"

    # Persist the event via the caller-supplied sink. Non-fatal — we
    # never let a logging failure crash the agent.
    if config.event_sink is not None:
        try:
            config.event_sink(
                source=source,
                decision=decision,
                content_preview=content[:500],
                content_sha256=content_hash(content),
                execution_id=execution_id,
                policy_id=config.policy_id,
                tenant_id=config.tenant_id,
                user_id=config.user_id,
            )
        except Exception as e:
            logger.warning("moderation event_sink failed: %s", e)

    if decision.action == ACTION_BLOCK:
        raise ModerationBlocked(decision, source=source, content_preview=content[:500])
    if decision.action == ACTION_REDACT and decision.redacted_content is not None:
        return decision.redacted_content, decision
    # FLAG passes through unchanged; sink + dashboards do the rest.
    return content, decision
