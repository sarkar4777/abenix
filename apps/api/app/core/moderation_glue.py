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
from engine.moderation_gate import GateConfig  # noqa: E402

logger = logging.getLogger(__name__)


@dataclass
class ModerationGateContext:
    """Wraps a GateConfig + its collected events for post-hoc persistence."""

    gate: GateConfig | None = None
    policy_id: uuid.UUID | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


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
) -> ModerationGateContext:
    """Load the active policy and return a ready-to-use gate context."""
    ctx = ModerationGateContext()
    policy = await load_active_policy(db, tenant_id)
    if policy is None:
        return ctx

    def _sink(**kw: Any) -> None:
        """Capture an event record. Persisted by `persist_events()` after the run."""
        decision = kw.get("decision")
        if decision is None:
            return
        ctx.events.append(
            {
                "source": kw.get("source", ""),
                "outcome": decision.outcome,
                "content_preview": (kw.get("content_preview") or "")[:500],
                "content_sha256": kw.get("content_sha256"),
                "execution_id": kw.get("execution_id") or None,
                "acted_categories": decision.triggered_categories,
                "provider_response": decision.provider_response,
                "latency_ms": decision.latency_ms,
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
        fail_closed=False,
        event_sink=_sink,
    )
    return ctx


async def persist_events(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    ctx: ModerationGateContext,
) -> list[uuid.UUID]:
    """Write all captured events to the moderation_events table."""
    ids: list[uuid.UUID] = []
    if not ctx or not ctx.events:
        return ids
    for e in ctx.events:
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
        except Exception as exc:
            logger.warning("moderation event persist failed: %s", exc)
    try:
        await db.flush()
    except Exception as exc:
        logger.warning("moderation event flush failed: %s", exc)
    return ids
