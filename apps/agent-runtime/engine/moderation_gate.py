"""Policy gate — non-bypassable content moderation wired into AgentExecutor."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable

from engine.moderation_client import (
    ACTION_ALLOW,
    ACTION_BLOCK,
    ACTION_HOLD,
    ACTION_REDACT,
    ModerationDecision,
    content_hash,
    evaluate,
    mask_spans,
    pattern_spans,
)

logger = logging.getLogger(__name__)

HOLD_TIMEOUT_ACTIONS = ("reject", "release")


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
    hold_timeout_minutes: int = 60
    hold_timeout_action: str = "reject"
    # where a held message lives, so a decision can update it
    conversation_id: str = ""
    agent_id: str = ""
    # content hash -> review id, messages a reviewer already released, each usable once
    released: dict = field(default_factory=dict)


class ModerationBlocked(Exception):
    """Raised by the gate when a BLOCK action is returned."""

    def __init__(self, decision: ModerationDecision, source: str, content_preview: str):
        self.decision = decision
        self.source = source
        self.content_preview = content_preview
        super().__init__(
            f"Moderation blocked ({source}): {decision.reason or 'policy_triggered'}"
        )


class ModerationHeld(ModerationBlocked):
    """A HOLD action. Code that only knows blocks still refuses the content."""

    def __init__(
        self,
        decision: ModerationDecision,
        source: str,
        content_preview: str,
        review_id: str,
        timeout_minutes: int,
        timeout_action: str,
    ):
        super().__init__(decision, source, content_preview)
        self.review_id = review_id
        self.timeout_minutes = timeout_minutes
        self.timeout_action = timeout_action


# actions that make a streamed reply unsafe to show before the gate has seen it
_WITHHOLDING = (ACTION_HOLD, ACTION_BLOCK, ACTION_REDACT)


def guards_output(config: GateConfig | None) -> bool:
    """True when the reply must be buffered until the post-LLM check decides."""
    if config is None or not config.post_llm:
        return False
    if config.fail_closed or config.default_action in _WITHHOLDING:
        return True
    return any(v in _WITHHOLDING for v in (config.category_actions or {}).values())


def held_message(source: str, timeout_minutes: int, timeout_action: str) -> str:
    """What the person sees while their message or the reply waits for a reviewer."""
    what = "Your message" if source == "pre_llm" else "The reply"
    after = "be sent anyway" if timeout_action == "release" else "not be sent"
    return (
        f"{what} is waiting for review. Your organisation's moderation policy asks a "
        f"person to check content like this first. If nobody decides within "
        f"{timeout_minutes} minutes it will {after}."
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

    digest = content_hash(content)
    # a reviewer already released this exact message, it goes through once
    if source == "pre_llm" and digest in (config.released or {}):
        review_id = config.released.pop(digest)
        decision = ModerationDecision(
            outcome="allowed", action=ACTION_ALLOW, reason="released_by_reviewer"
        )
        _emit(
            config, source, decision, content, digest, execution_id, consumed=review_id
        )
        return content, decision

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

    review_id = str(uuid.uuid4()) if decision.action == ACTION_HOLD else ""
    _emit(config, source, decision, content, digest, execution_id, review_id=review_id)

    if decision.action == ACTION_HOLD:
        raise ModerationHeld(
            decision,
            source=source,
            content_preview=content[:500],
            review_id=review_id,
            timeout_minutes=int(config.hold_timeout_minutes or 60),
            timeout_action=(
                config.hold_timeout_action
                if config.hold_timeout_action in HOLD_TIMEOUT_ACTIONS
                else "reject"
            ),
        )
    if decision.action == ACTION_BLOCK:
        raise ModerationBlocked(decision, source=source, content_preview=content[:500])
    if decision.action == ACTION_REDACT and decision.redacted_content is not None:
        return decision.redacted_content, decision
    # FLAG passes through unchanged; sink + dashboards do the rest.
    return content, decision


def _emit(
    config: GateConfig,
    source: str,
    decision: ModerationDecision,
    content: str,
    digest: str,
    execution_id: str,
    *,
    review_id: str = "",
    consumed: str = "",
) -> None:
    # Persist the event via the caller-supplied sink. Non-fatal — we
    # never let a logging failure crash the agent.
    if config.event_sink is None:
        return
    extra: dict = {}
    if review_id:
        extra["hold"] = {
            "review_id": review_id,
            "content": content,
            "spans": list(decision.spans or []),
            "timeout_minutes": int(config.hold_timeout_minutes or 60),
            "timeout_action": config.hold_timeout_action or "reject",
            "conversation_id": config.conversation_id or "",
            "agent_id": config.agent_id or "",
        }
    if consumed:
        extra["consumed_review_id"] = consumed
    try:
        config.event_sink(
            source=source,
            decision=decision,
            # what the policy matched stays out of the event log, provider hits included
            content_preview=mask_spans(
                content,
                list(decision.spans or [])
                + pattern_spans(content, config.custom_patterns),
                config.redaction_mask,
            )[:500],
            content_sha256=digest,
            execution_id=execution_id,
            policy_id=config.policy_id,
            tenant_id=config.tenant_id,
            user_id=config.user_id,
            **extra,
        )
    except Exception as e:
        logger.warning("moderation event_sink failed: %s", e)
