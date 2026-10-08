"""Glue between the API layer and the agent-runtime's moderation gate."""

from __future__ import annotations

import logging
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from app.core.telemetry import moderation_provider_errors_total
except Exception:  # pragma: no cover — agent-runtime side import path
    moderation_provider_errors_total = None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "packages" / "db"))

from models.moderation_policy import (  # noqa: E402
    ModerationAction,
    ModerationEvent,
    ModerationEventOutcome,
    ModerationPolicy,
)

# Import the GateConfig dataclass from the runtime. Python lets a single
# dataclass cross the module boundary since both processes run the same
# codebase.
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "apps" / "agent-runtime"))
from engine.moderation_client import mask_spans, pattern_spans  # noqa: E402
from engine.moderation_gate import GateConfig  # noqa: E402

logger = logging.getLogger(__name__)


# Built-in PII regex set for the auto-seeded default policy. New
# tenants get these out of the box so common PII (SSN, credit cards,
# AWS keys, bearer tokens) is blocked at /api/agents/{id}/execute
# without any admin configuration. Tenants can edit the list at
# /moderation; this is just the safe default. Mirrors engine.dlp's
# pattern set so the two surfaces stay aligned.
DEFAULT_PII_PATTERNS: list[str] = [
    r"\b\d{3}-\d{2}-\d{4}\b",  # US SSN
    r"\b(?:\d{4}[-\s]?){3}\d{4}\b",  # 16-digit card
    r"\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b",  # AWS access key
    r"(?i)aws_secret_access_key\s*[=:]\s*[\w/+=]{40}",  # AWS secret
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",  # bearer token
    r"(?i)(?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[\w-]{20,}['\"]?",
]


def _mask_patterns(text: str, patterns: list[Any], mask: str) -> str:
    return mask_spans(text, pattern_spans(text, patterns), mask)


@dataclass
class ModerationGateContext:
    """Wraps a GateConfig + its collected events for post-hoc persistence."""

    gate: GateConfig | None = None
    policy_id: uuid.UUID | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    redaction_mask: str = "█████"


async def load_active_policy(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> ModerationPolicy | None:
    q = (
        select(ModerationPolicy)
        .where(ModerationPolicy.tenant_id == tenant_id)
        .where(ModerationPolicy.is_active.is_(True))
        .order_by(desc(ModerationPolicy.updated_at))
        .limit(1)
    )
    return (await db.execute(q)).scalars().first()


async def build_gate_context(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    conversation_id: Any = None,
    agent_id: Any = None,
) -> ModerationGateContext:
    """Load the active policy and return a ready-to-use gate context."""
    ctx = ModerationGateContext()
    policy = await load_active_policy(db, tenant_id)
    if policy is None:
        return ctx
    released: dict[str, str] = {}
    try:
        from engine.moderation_hold import load_released

        released = await load_released(db, tenant_id, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("released reviews not loaded: %s", exc)

    def _sink(**kw: Any) -> None:
        """Capture an event record. Persisted by `persist_events()` after the run."""
        decision = kw.get("decision")
        if decision is None:
            return
        # Surface provider failures as a Prometheus signal so operators
        # spot quota / outage windows immediately — without this, a 429
        # storm only shows up after a customer complaint.
        if (
            getattr(decision, "error", None)
            and moderation_provider_errors_total is not None
        ):
            try:
                moderation_provider_errors_total.labels(
                    provider="openai",
                    model=policy.provider_model,
                ).inc()
            except Exception:
                logger.exception("failed to increment moderation_provider_errors_total")
        ctx.events.append(
            {
                "source": kw.get("source", ""),
                "outcome": decision.outcome,
                # the gate masks what matched, the patterns are masked again in case a caller did not
                "content_preview": _mask_patterns(
                    kw.get("content_preview") or "",
                    list(policy.custom_patterns or []),
                    policy.redaction_mask or "█████",
                )[:500],
                "content_sha256": kw.get("content_sha256"),
                "execution_id": kw.get("execution_id") or None,
                "acted_categories": decision.triggered_categories,
                "category_scores": dict(
                    getattr(decision, "category_scores", None) or {}
                ),
                "provider_response": decision.provider_response,
                "latency_ms": decision.latency_ms,
                "hold": kw.get("hold"),
                "consumed_review_id": kw.get("consumed_review_id"),
            }
        )

    ctx.policy_id = policy.id
    ctx.gate = GateConfig(
        policy_id=str(policy.id),
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        pre_llm=policy.pre_llm,
        post_llm=policy.post_llm,
        on_tool_output=policy.on_tool_output,
        provider_model=policy.provider_model,
        thresholds=dict(policy.thresholds or {}),
        default_threshold=float(policy.default_threshold),
        category_actions=dict(policy.category_actions or {}),
        default_action=(
            policy.default_action.value
            if isinstance(policy.default_action, ModerationAction)
            else str(policy.default_action)
        ),
        custom_patterns=list(policy.custom_patterns or []),
        redaction_mask=policy.redaction_mask or "█████",
        fail_closed=bool(getattr(policy, "fail_closed", False)),
        event_sink=_sink,
        hold_timeout_minutes=int(getattr(policy, "hold_timeout_minutes", 60) or 60),
        hold_timeout_action=str(getattr(policy, "hold_timeout_action", "reject")),
        conversation_id=str(conversation_id or ""),
        agent_id=str(agent_id or ""),
        released=released,
    )
    ctx.redaction_mask = policy.redaction_mask or "█████"
    return ctx


async def persist_events(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: ModerationGateContext,
) -> list[uuid.UUID]:
    """Write all captured events to the moderation_events table, and any held content to the review inbox."""
    from engine.moderation_hold import persist_gate_event

    ids: list[uuid.UUID] = []
    if not ctx or not ctx.events:
        return ids
    held = False
    pending = list(ctx.events)
    # a second call with the same context must not write the events twice
    ctx.events = []
    for e in pending:
        try:
            outcome_raw = e.get("outcome") or "allowed"
            try:
                outcome_enum = ModerationEventOutcome(outcome_raw)
            except ValueError:
                outcome_enum = ModerationEventOutcome.ERROR
            exec_id_raw = e.get("execution_id")
            exec_uuid: uuid.UUID | None = None
            if exec_id_raw:
                try:
                    exec_uuid = (
                        uuid.UUID(exec_id_raw)
                        if isinstance(exec_id_raw, str)
                        else exec_id_raw
                    )
                except ValueError:
                    exec_uuid = None
            ev = ModerationEvent(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                policy_id=ctx.policy_id,
                user_id=user_id,
                execution_id=exec_uuid,
                source=e.get("source") or "pre_llm",
                outcome=outcome_enum,
                content_sha256=e.get("content_sha256"),
                content_preview=e.get("content_preview"),
                provider_response=e.get("provider_response") or {},
                acted_categories=e.get("acted_categories") or [],
                latency_ms=int(e.get("latency_ms") or 0),
            )
            db.add(ev)
            ids.append(ev.id)
            review = await persist_gate_event(
                db,
                event=ev,
                payload=e,
                tenant_id=tenant_id,
                user_id=user_id,
                policy_id=ctx.policy_id,
                execution_id=exec_uuid,
                redaction_mask=ctx.redaction_mask,
            )
            held = held or review is not None
        except Exception as exc:
            logger.warning("moderation event persist failed: %s", exc)
    try:
        await db.flush()
    except Exception as exc:
        logger.warning("moderation event flush failed: %s", exc)
    if held:
        try:
            from app.services.moderation_review import announce_soon

            announce_soon(tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("review announce not scheduled: %s", exc)
    return ids
