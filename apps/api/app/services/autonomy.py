"""Earned autonomy service: grants, the action ledger, reviews, outcomes, promotions and demotions."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import notifications as notif
from app.services import autonomy_ladder as L
from app.services import events
from models.agent import Agent
from models.approval import Approval, ApprovalStatus
from models.autonomy import ActionType, AgentAction, AutonomyChange, AutonomyGrant
from models.user import User

logger = logging.getLogger(__name__)

WORLD_MODEL_KINDS = ("agent_stated", "decision", "ml_model", "none")
PROBE_KINDS = ("tool", "manual", "api", "none")
GRANT_STATES = ("active", "paused")
UNKNOWN_AFTER = timedelta(hours=24)
MAX_PROBE_ATTEMPTS = 3
ACTION_GATE_PREFIX = "action:"
PROMOTE_GATE = "autonomy.promote"
DEFAULT_APPROVAL_SECONDS = 1800
STATS_ROWS = 1000

SAMPLE_AGENT_SLUG = "sample-plant-operator"
SAMPLE_AGENT_NAME = "Plant operator (sample)"
SAMPLE_ACTION_KEY = "sample_plant.set_setpoint"
SAMPLE_LIMITS_KEY = "sample_plant_limits"
SAMPLE_RUN_MESSAGE = "Check the plant and act if needed."
SAMPLE_POLICY = {
    "to_asks_first": {"min_reviews": 5, "min_agreement_lb": 0.3},
    "to_within_limits": {
        "min_executed": 8,
        "min_accuracy_lb": 0.5,
        "min_no_edit_rate": 0.5,
        "harm_free_days": 0,
        "min_days_at_level": 0,
    },
    "to_acts_reports": {
        "min_executed": 8,
        "min_accuracy_lb": 0.5,
        "harm_free_days": 0,
        "min_days_at_level": 0,
    },
    # judged on its recent actions, so a session of tries is enough to learn it
    "window": 20,
}
SAMPLE_PROMPT = (
    "You operate a small sample plant through the sample_plant tool. The goal is a pressure "
    "of 4.5 bar.\n"
    "1. Call sample_plant with operation read. It returns pressure_bar, setpoint_bar, demand "
    "and a note on how the plant responds: pressure settles to about setpoint_bar x demand "
    "within 30 seconds, give or take 0.1 bar.\n"
    "2. Work out the right setpoint, 4.5 / demand rounded to 2 decimals. If setpoint_bar "
    "already equals it, change nothing and say the plant is fine.\n"
    "3. Otherwise call sample_plant with operation set_setpoint and that setpoint_bar.\n"
    "Always pass _intent, one sentence on why, and _prediction for pressure_bar 30 seconds "
    'later as {"metric": "pressure_bar", "value": v, "low": v - 0.25, "high": v + 0.25, '
    '"horizon_s": 30}, where v is the setpoint_bar you send times demand, rounded to 2 '
    "decimals.\n"
    "4. If the tool says the action was recorded in watching mode, is waiting for approval or "
    "was blocked, say so plainly. Never claim the setpoint changed unless the tool confirms it."
)


class AutonomyError(Exception):
    def __init__(
        self,
        message: str,
        status: int = 400,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def _uuid(v: Any) -> uuid.UUID | None:
    if v is None or v == "":
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except (ValueError, TypeError):
        return None


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


def scope_hash(scope: dict[str, Any] | None) -> str:
    if not scope:
        return ""
    raw = json.dumps(scope, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _role(user: Any) -> str:
    r = getattr(user, "role", None)
    return str(getattr(r, "value", r) or "user").lower()


def _user_name(u: Any) -> str:
    return (getattr(u, "full_name", None) or getattr(u, "email", None) or "").strip()


# queries, kept small so tests can swap them


async def get_grant(db: AsyncSession, tenant_id: Any, grant_id: Any) -> Any:
    gid = _uuid(grant_id)
    if gid is None:
        return None
    return (
        await db.execute(
            select(AutonomyGrant).where(
                AutonomyGrant.id == gid,
                AutonomyGrant.tenant_id == tenant_id,
                AutonomyGrant.state != "removed",
            )
        )
    ).scalar_one_or_none()


async def get_action(db: AsyncSession, tenant_id: Any, action_id: Any) -> Any:
    aid = _uuid(action_id)
    if aid is None:
        return None
    return (
        await db.execute(
            select(AgentAction).where(
                AgentAction.id == aid, AgentAction.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def get_action_type(db: AsyncSession, tenant_id: Any, type_id: Any) -> Any:
    tid = _uuid(type_id)
    if tid is None:
        return None
    return (
        await db.execute(
            select(ActionType).where(
                ActionType.id == tid, ActionType.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def get_action_type_by_key(db: AsyncSession, tenant_id: Any, key: str) -> Any:
    return (
        await db.execute(
            select(ActionType).where(
                ActionType.tenant_id == tenant_id, ActionType.key == key
            )
        )
    ).scalar_one_or_none()


async def list_action_types(db: AsyncSession, tenant_id: Any) -> list[Any]:
    return list(
        (
            await db.execute(
                select(ActionType)
                .where(ActionType.tenant_id == tenant_id)
                .order_by(ActionType.label.asc())
            )
        )
        .scalars()
        .all()
    )


async def get_agent(db: AsyncSession, tenant_id: Any, agent_id: Any) -> Any:
    aid = _uuid(agent_id)
    if aid is None:
        return None
    return (
        await db.execute(
            select(Agent).where(Agent.id == aid, Agent.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def agents_by_id(db: AsyncSession, ids: list[Any]) -> dict[str, Any]:
    ids = [i for i in {_uuid(x) for x in ids} if i]
    if not ids:
        return {}
    rows = (await db.execute(select(Agent).where(Agent.id.in_(ids)))).scalars().all()
    return {str(a.id): a for a in rows}


async def types_by_id(db: AsyncSession, ids: list[Any]) -> dict[str, Any]:
    ids = [i for i in {_uuid(x) for x in ids} if i]
    if not ids:
        return {}
    rows = (
        (await db.execute(select(ActionType).where(ActionType.id.in_(ids))))
        .scalars()
        .all()
    )
    return {str(t.id): t for t in rows}


async def users_by_id(db: AsyncSession, ids: list[Any]) -> dict[str, str]:
    ids = [i for i in {_uuid(x) for x in ids} if i]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(User.id, User.full_name, User.email).where(User.id.in_(ids))
        )
    ).all()
    return {str(r[0]): (r[1] or r[2] or "") for r in rows}


async def list_grants(
    db: AsyncSession,
    tenant_id: Any,
    *,
    agent_id: Any = None,
    action_type_id: Any = None,
) -> list[Any]:
    stmt = select(AutonomyGrant).where(
        AutonomyGrant.tenant_id == tenant_id, AutonomyGrant.state != "removed"
    )
    if agent_id is not None:
        stmt = stmt.where(AutonomyGrant.agent_id == _uuid(agent_id))
    if action_type_id is not None:
        stmt = stmt.where(AutonomyGrant.action_type_id == _uuid(action_type_id))
    stmt = stmt.order_by(AutonomyGrant.created_at.asc()).limit(1000)
    return list((await db.execute(stmt)).scalars().all())


async def find_grant(
    db: AsyncSession,
    tenant_id: Any,
    agent_id: Any,
    action_type_id: Any,
    shash: str,
) -> Any:
    return (
        await db.execute(
            select(AutonomyGrant).where(
                AutonomyGrant.tenant_id == tenant_id,
                AutonomyGrant.agent_id == _uuid(agent_id),
                AutonomyGrant.action_type_id == _uuid(action_type_id),
                AutonomyGrant.scope_hash == shash,
            )
        )
    ).scalar_one_or_none()


async def grant_actions(
    db: AsyncSession, tenant_id: Any, grant_id: Any, limit: int = STATS_ROWS
) -> list[Any]:
    return list(
        (
            await db.execute(
                select(AgentAction)
                .where(
                    AgentAction.tenant_id == tenant_id,
                    AgentAction.grant_id == _uuid(grant_id),
                )
                .order_by(AgentAction.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def action_page(
    db: AsyncSession,
    tenant_id: Any,
    grant_id: Any,
    status: str | None,
    limit: int,
    before: datetime | None,
) -> list[Any]:
    stmt = select(AgentAction).where(
        AgentAction.tenant_id == tenant_id, AgentAction.grant_id == _uuid(grant_id)
    )
    if status:
        stmt = stmt.where(AgentAction.status.in_(status.split(",")))
    if before is not None:
        stmt = stmt.where(AgentAction.created_at < before)
    stmt = stmt.order_by(AgentAction.created_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


async def list_changes(db: AsyncSession, grant_id: Any, limit: int = 200) -> list[Any]:
    return list(
        (
            await db.execute(
                select(AutonomyChange)
                .where(AutonomyChange.grant_id == _uuid(grant_id))
                .order_by(AutonomyChange.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def recent_demotions(
    db: AsyncSession, tenant_id: Any, days: int = 14
) -> list[Any]:
    return list(
        (
            await db.execute(
                select(AutonomyChange)
                .where(
                    AutonomyChange.tenant_id == tenant_id,
                    AutonomyChange.to_level < AutonomyChange.from_level,
                    AutonomyChange.created_at >= _now() - timedelta(days=days),
                )
                .order_by(AutonomyChange.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )


async def overview_counts(db: AsyncSession, tenant_id: Any) -> dict[str, int]:
    since = _now() - timedelta(days=7)
    row = (
        await db.execute(
            select(
                func.count().filter(AgentAction.created_at >= since),
                func.count().filter(
                    AgentAction.created_at >= since,
                    AgentAction.mode.in_(("auto", "reported")),
                    AgentAction.status == "executed",
                ),
                func.count().filter(
                    AgentAction.created_at >= since, AgentAction.harm.is_(True)
                ),
                func.count().filter(
                    AgentAction.status == "watching",
                    AgentAction.reviewer_answer.is_(None),
                ),
                func.count().filter(AgentAction.status == "pending"),
            ).where(AgentAction.tenant_id == tenant_id)
        )
    ).one()
    return {
        "actions_7d": int(row[0] or 0),
        "auto_7d": int(row[1] or 0),
        "harm_7d": int(row[2] or 0),
        "pending_reviews": int(row[3] or 0),
        "pending_approvals": int(row[4] or 0),
    }


async def unmanaged_rows(db: AsyncSession, tenant_id: Any) -> list[tuple]:
    since = _now() - timedelta(days=7)
    return list(
        (
            await db.execute(
                select(
                    AgentAction.agent_id,
                    func.max(AgentAction.agent_name),
                    AgentAction.tool_name,
                    func.count(),
                )
                .where(
                    AgentAction.tenant_id == tenant_id,
                    AgentAction.mode == "unmanaged",
                    AgentAction.created_at >= since,
                )
                .group_by(AgentAction.agent_id, AgentAction.tool_name)
                .order_by(func.count().desc())
                .limit(50)
            )
        ).all()
    )


async def pending_reviews(db: AsyncSession, tenant_id: Any, limit: int) -> list[Any]:
    return list(
        (
            await db.execute(
                select(AgentAction)
                .where(
                    AgentAction.tenant_id == tenant_id,
                    AgentAction.status == "watching",
                    AgentAction.reviewer_answer.is_(None),
                )
                .order_by(AgentAction.created_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def execution_inputs(db: AsyncSession, ids: list[Any]) -> dict[str, str]:
    from models.execution import Execution

    ids = [i for i in {_uuid(x) for x in ids} if i]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Execution.id, Execution.input_message).where(Execution.id.in_(ids))
        )
    ).all()
    return {str(r[0]): r[1] or "" for r in rows}


async def config_hash(db: AsyncSession, agent_id: Any) -> str | None:
    # same expression as the executions_provenance trigger, so runs and grants agree
    if _uuid(agent_id) is None:
        return None
    try:
        return (
            await db.execute(
                text(
                    "SELECT encode(sha256(convert_to(coalesce(system_prompt, '') || '|' || "
                    "coalesce(model_config::text, ''), 'UTF8')), 'hex') FROM agents WHERE id = :id"
                ),
                {"id": str(agent_id)},
            )
        ).scalar()
    except Exception as e:  # noqa: BLE001
        logger.debug("config hash lookup failed: %s", e)
        return None


async def eval_passing(
    db: AsyncSession, agent_id: Any, current_hash: str | None = None
) -> bool | None:
    """Whether the suites pass for the agent as it is now, judged like the publish gate.

    Only completed runs on the agent's own model against the current config hash count.
    Gating suites decide when the agent has any. False when the suites ran only on an
    older version, None when they never ran.
    """
    from models.evals import EvalRun, EvalSuite

    aid = _uuid(agent_id)
    if aid is None:
        return None
    chash = current_hash or await config_hash(db, aid)
    if not chash:
        return None
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(EvalRun.suite_id, EvalRun.threshold_met, EvalSuite.gating)
                    .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
                    .where(
                        EvalSuite.agent_id == aid,
                        EvalRun.status == "completed",
                        EvalRun.model_override.is_(False),
                        EvalRun.config_hash == chash,
                        EvalRun.threshold_met.isnot(None),
                    )
                    .order_by(EvalRun.completed_at.desc().nulls_last())
                )
            ).all()
            verdict = latest_verdict(rows)
            if verdict is None:
                older = (
                    await db.execute(
                        select(EvalRun.id)
                        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
                        .where(
                            EvalSuite.agent_id == aid,
                            EvalRun.status == "completed",
                            EvalRun.model_override.is_(False),
                        )
                        .limit(1)
                    )
                ).first()
                # an edit since the last run means the suites must run again
                verdict = False if older is not None else None
    except Exception as e:  # noqa: BLE001
        logger.debug("eval lookup skipped: %s", e)
        return None
    return verdict


def latest_verdict(rows: list[Any]) -> bool | None:
    """rows are (suite_id, threshold_met, gating), newest first."""
    latest: dict[Any, tuple[bool, bool]] = {}
    for suite_id, met, gating in rows:
        latest.setdefault(suite_id, (bool(met), bool(gating)))
    if not latest:
        return None
    gating = [met for met, g in latest.values() if g]
    return all(gating if gating else [met for met, _ in latest.values()])


async def tenant_settings(db: AsyncSession, tenant_id: Any) -> dict[str, Any]:
    from models.tenant import Tenant

    t = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return dict(getattr(t, "settings", None) or {}) if t else {}


# policy, ceilings and stats


def agent_tier(agent: Any) -> str:
    return str(
        ((getattr(agent, "model_config_", None) or {}).get("risk_tier")) or "low"
    )


def policy_for(tenant_id: Any, tier: str, action_type: Any) -> dict[str, Any]:
    tier_layer = None
    try:
        from engine import governance

        tier_layer = governance.policy(str(tenant_id), tier).get("autonomy")
    except Exception:  # noqa: BLE001
        tier_layer = None
    return L.merge_policy(tier_layer, getattr(action_type, "policy", None))


def ceiling_for(agent: Any, action_type: Any, grant: Any) -> int:
    return L.effective_ceiling(
        agent_tier(agent),
        getattr(action_type, "ceiling", None),
        getattr(grant, "ceiling", None),
    )


async def limits_problem(db: AsyncSession, tenant_id: Any, at: Any) -> str | None:
    """A limits model with nothing published blocks every action, say so up front."""
    key = getattr(at, "limits_decision_key", None)
    if not key:
        return None
    try:
        from models.decision import DecisionModel, DecisionVersion

        m = (
            await db.execute(
                select(DecisionModel).where(
                    DecisionModel.tenant_id == tenant_id, DecisionModel.key == key
                )
            )
        ).scalar_one_or_none()
        if m is None:
            return f"The hard limits {key} do not exist, so every action is blocked."
        live = (
            await db.execute(
                select(func.count())
                .select_from(DecisionVersion)
                .where(
                    DecisionVersion.model_id == m.id,
                    DecisionVersion.state == "published",
                    DecisionVersion.superseded_at.is_(None),
                )
            )
        ).scalar()
        if not live:
            return f"The hard limits {key} have no published version, so every action is blocked. Publish it under Decisions."
    except Exception as e:  # noqa: BLE001
        logger.debug("limits status check failed: %s", e)
    return None


async def grant_bundle(db: AsyncSession, grant: Any) -> dict[str, Any]:
    """Everything the ladder needs about one grant."""
    agent = await get_agent(db, grant.tenant_id, grant.agent_id)
    at = await get_action_type(db, grant.tenant_id, grant.action_type_id)
    rows = await grant_actions(db, grant.tenant_id, grant.id)
    current = await config_hash(db, grant.agent_id)
    tier = agent_tier(agent)
    policy = policy_for(grant.tenant_id, tier, at)
    stats = L.compute_stats(
        rows,
        now=_now(),
        window=int(policy.get("window") or 50),
        level_since=grant.level_since,
        created_at=grant.created_at,
        current_config_hash=current,
        eval_passing=(
            await eval_passing(db, grant.agent_id, current) if agent else None
        ),
    )
    cap = ceiling_for(agent, at, grant)
    result = L.evaluate(grant, stats, policy, _now(), ceiling=cap)
    return {
        "grant": grant,
        "agent": agent,
        "action_type": at,
        "actions": rows,
        "stats": stats,
        "policy": policy,
        "ceiling": cap,
        "next": result,
        "tier": tier,
        "limits_problem": await limits_problem(db, grant.tenant_id, at),
    }


# serializers


def action_type_brief(at: Any) -> dict[str, Any] | None:
    if at is None:
        return None
    return {
        "id": str(at.id),
        "key": at.key,
        "label": at.label,
        "is_sample": bool(getattr(at, "is_sample", False)),
    }


def action_type_json(at: Any) -> dict[str, Any]:
    return {
        "id": str(at.id),
        "key": at.key,
        "label": at.label,
        "description": at.description or "",
        "tool_name": at.tool_name,
        "match": at.match,
        "effect": at.effect,
        "world_model": at.world_model,
        "outcome_probe": at.outcome_probe,
        "limits_decision_key": at.limits_decision_key,
        "max_band_width": at.max_band_width,
        "reversible": bool(at.reversible),
        "ceiling": at.ceiling,
        "policy": at.policy,
        "effective_policy": L.merge_policy(at.policy),
        "is_sample": bool(at.is_sample),
        "created_by": _s(at.created_by),
        "created_at": _iso(getattr(at, "created_at", None)),
        "updated_at": _iso(getattr(at, "updated_at", None)),
    }


GRANT_STAT_KEYS = (
    "scored",
    "held",
    "accuracy_pct",
    "accuracy_lb_pct",
    "reviews",
    "agreement_pct",
    "executed",
    "rejected",
    "unknown",
    "harm_30d",
    "harm_free_days",
    "days_at_level",
)


def grant_row(bundle: dict[str, Any]) -> dict[str, Any]:
    g = bundle["grant"]
    agent = bundle["agent"]
    stats = bundle["stats"]
    nxt = bundle["next"]
    attention = (
        bundle.get("limits_problem")
        or L.attention_for(g, nxt, stats)
        or getattr(g, "attention", None)
    )
    if not attention and stats.get("pending_reviews"):
        attention = f"{stats['pending_reviews']} waiting for review"
    return {
        "id": str(g.id),
        "agent": {
            "id": str(g.agent_id),
            "name": getattr(agent, "name", None) or "Deleted agent",
        },
        "action_type": action_type_brief(bundle["action_type"]),
        "scope": g.scope,
        "level": int(g.level),
        "level_label": L.level_label(g.level),
        "ceiling": bundle["ceiling"],
        "ceiling_label": L.level_label(bundle["ceiling"]),
        "state": g.state,
        "level_since": _iso(g.level_since),
        "stats": {k: stats.get(k) for k in GRANT_STAT_KEYS},
        "next": nxt,
        "spark": stats.get("spark") or [],
        "attention": attention,
        "limits_problem": bundle.get("limits_problem"),
    }


def record_of(stats: dict[str, Any] | None) -> dict[str, Any]:
    stats = stats or {}
    held_n, scored = int(stats.get("held") or 0), int(stats.get("scored") or 0)
    agreement = stats.get("agreement_pct")
    if scored:
        txt = f"Held {held_n} of {scored} times"
    elif stats.get("reviews"):
        txt = f"People agreed {agreement}% of {stats['reviews']} reviews"
    else:
        txt = "No track record yet"
    return {
        "held": held_n,
        "scored": scored,
        "agreement_pct": agreement,
        "text": txt,
    }


def card_for(
    action: Any,
    at: Any,
    agent_name: str,
    stats: dict[str, Any] | None,
    level: int | None = None,
) -> dict[str, Any]:
    lvl = action.level_at_time if level is None else level
    limits = action.limits_result or None
    return {
        "action_id": str(action.id),
        "action_type": (
            {"key": at.key, "label": at.label, "reversible": bool(at.reversible)}
            if at is not None
            else None
        ),
        "agent": {"id": _s(action.agent_id), "name": agent_name or action.agent_name},
        "level": lvl,
        "level_label": L.level_label(lvl) if lvl is not None else "Not enrolled",
        "target": action.target,
        "arguments": action.arguments or {},
        "intent": action.intent,
        "prediction": action.prediction,
        "limits": limits,
        "fallback_reason": (limits or {}).get("fallback_reason"),
        "record": record_of(stats),
        "editable_arguments": bool(action.status in ("pending",)),
    }


def action_row(
    action: Any,
    *,
    at: Any = None,
    agent_name: str = "",
    decided_by_name: str | None = None,
    stats: dict[str, Any] | None = None,
    with_card: bool = True,
) -> dict[str, Any]:
    lvl = action.level_at_time
    return {
        "id": str(action.id),
        "created_at": _iso(action.created_at),
        "agent": {"id": _s(action.agent_id), "name": agent_name or action.agent_name},
        "action_type": {"key": at.key, "label": at.label} if at is not None else None,
        "tool_name": action.tool_name,
        "mode": action.mode,
        "status": action.status,
        "level_at_time": lvl,
        "level_label": L.level_label(lvl) if lvl is not None else "Not enrolled",
        "target": action.target,
        "arguments": action.arguments or {},
        "intent": action.intent,
        "prediction": action.prediction,
        "outcome": action.outcome,
        "outcome_status": action.outcome_status,
        "outcome_due_at": _iso(action.outcome_due_at),
        "score": action.score,
        "harm": bool(action.harm),
        "harm_note": action.harm_note,
        "reviewer_answer": action.reviewer_answer,
        "reviewer_alternative": action.reviewer_alternative,
        "decided_by_name": decided_by_name,
        "decision_note": action.decision_note,
        "execution_id": _s(action.execution_id),
        "approval_id": _s(action.approval_id),
        "result_preview": action.result_preview,
        "executed_at": _iso(action.executed_at),
        "card": (card_for(action, at, agent_name, stats, None) if with_card else None),
    }


async def action_rows(
    db: AsyncSession,
    actions: list[Any],
    *,
    stats_by_grant: dict[str, dict] | None = None,
    hide_cards: set[str] | None = None,
) -> list[dict[str, Any]]:
    agents = await agents_by_id(db, [a.agent_id for a in actions])
    types = await types_by_id(db, [a.action_type_id for a in actions])
    names = await users_by_id(db, [a.decided_by for a in actions])
    out = []
    for a in actions:
        ag = agents.get(str(a.agent_id))
        out.append(
            action_row(
                a,
                at=types.get(str(a.action_type_id)),
                agent_name=getattr(ag, "name", "") or a.agent_name,
                decided_by_name=names.get(str(a.decided_by)) if a.decided_by else None,
                stats=(stats_by_grant or {}).get(str(a.grant_id)),
                with_card=str(a.id) not in (hide_cards or set()),
            )
        )
    return out


# level changes


async def record_change(
    db: AsyncSession,
    grant: Any,
    to_level: int,
    *,
    actor_type: str,
    actor_id: Any = None,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> Any:
    change = AutonomyChange(
        id=uuid.uuid4(),
        grant_id=grant.id,
        tenant_id=grant.tenant_id,
        from_level=int(grant.level),
        to_level=int(to_level),
        actor_type=actor_type,
        actor_id=_uuid(actor_id),
        reason=reason,
        evidence=evidence,
        created_at=_now(),
    )
    db.add(change)
    if actor_type == "user" and _uuid(actor_id):
        from app.core.audit import log_action

        await log_action(
            db,
            grant.tenant_id,
            _uuid(actor_id),
            "autonomy.level_changed",
            {"reason": reason},
            resource_type="autonomy_grant",
            resource_id=str(grant.id),
            old_value={"level": int(grant.level)},
            new_value={"level": int(to_level)},
        )
    if int(to_level) != int(grant.level):
        grant.level = int(to_level)
        grant.level_since = _now()
        grant.recommended_level = None
        grant.attention = None
    return change


def _evidence(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bundle:
        return None
    s = bundle["stats"]
    return {
        k: s.get(k)
        for k in (
            "scored",
            "held",
            "accuracy_pct",
            "accuracy_lb_pct",
            "reviews",
            "agreement_pct",
            "executed",
            "rejected",
            "unknown",
            "unknown_rate",
            "harm_30d",
            "harm_free_days",
            "days_at_level",
            "current_config_hash",
        )
    }


async def owners_of(grant: Any, agent: Any) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for uid in (getattr(grant, "granted_by", None), getattr(agent, "creator_id", None)):
        u = _uuid(uid)
        if u and u not in out:
            out.append(u)
    return out


async def notify_owners(
    db: AsyncSession,
    grant: Any,
    agent: Any,
    *,
    type: str,
    title: str,
    message: str,
    exclude: Any = None,
) -> None:
    for uid in await owners_of(grant, agent):
        if exclude is not None and str(uid) == str(exclude):
            continue
        try:
            await notif.create_notification(
                db,
                tenant_id=grant.tenant_id,
                user_id=uid,
                type=type,
                title=title[:255],
                message=message,
                link=f"/autonomy/{grant.id}",
                metadata={"grant_id": str(grant.id), "agent_id": str(grant.agent_id)},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("autonomy notification failed: %s", e)


async def demote(
    db: AsyncSession,
    grant: Any,
    to_level: int,
    *,
    reason: str,
    actor: Any = None,
    bundle: dict[str, Any] | None = None,
) -> Any:
    """Drop a grant now and tell its owners. Never needs an approval."""
    from_level = int(grant.level)
    to_level = max(0, min(int(to_level), from_level))
    agent = (bundle or {}).get("agent") or await get_agent(
        db, grant.tenant_id, grant.agent_id
    )
    at = (bundle or {}).get("action_type") or await get_action_type(
        db, grant.tenant_id, grant.action_type_id
    )
    change = await record_change(
        db,
        grant,
        to_level,
        actor_type="user" if actor is not None else "system",
        actor_id=getattr(actor, "id", None),
        reason=reason,
        evidence=_evidence(bundle),
    )
    await events.emit(
        db,
        grant.tenant_id,
        "autonomy.demoted",
        {
            "grant_id": str(grant.id),
            "agent_id": str(grant.agent_id),
            "action_key": getattr(at, "key", None),
            "from_level": from_level,
            "to_level": to_level,
            "reason": reason,
            "actor": "user" if actor is not None else "system",
        },
    )
    label = getattr(at, "label", None) or "an action"
    name = getattr(agent, "name", None) or "An agent"
    await notify_owners(
        db,
        grant,
        agent,
        type="autonomy_demoted",
        title=f"{name} moved down to {L.level_label(to_level)} for {label}",
        message=f"{reason}. It was {L.level_label(from_level)}.",
        exclude=getattr(actor, "id", None),
    )
    return change


async def reevaluate(db: AsyncSession, grant: Any) -> dict[str, Any]:
    """Apply automatic demotions and send a recommendation once per level."""
    bundle = await grant_bundle(db, grant)
    nxt, stats = bundle["next"], bundle["stats"]
    if nxt.get("demote_to") is not None and grant.state != "removed":
        await demote(
            db, grant, nxt["demote_to"], reason=nxt["demote_reason"], bundle=bundle
        )
        return await grant_bundle(db, grant)
    # the new revision has proven itself, so it becomes the baseline
    if (
        L.revision_changed(grant, stats)
        and int(stats.get("revision_correct") or 0)
        >= int(bundle["policy"].get("revision_recheck", 10))
    ) or (not grant.agent_config_hash and stats.get("current_config_hash")):
        grant.agent_config_hash = stats.get("current_config_hash")
    attention = L.attention_for(grant, nxt, stats)
    grant.attention = attention
    if (
        nxt.get("ready")
        and int(grant.level) >= 1
        and grant.recommended_level != nxt.get("next_level")
    ):
        grant.recommended_level = nxt["next_level"]
        await events.emit(
            db,
            grant.tenant_id,
            "autonomy.recommended",
            {
                "grant_id": str(grant.id),
                "agent_id": str(grant.agent_id),
                "action_key": getattr(bundle["action_type"], "key", None),
                "from_level": int(grant.level),
                "to_level": nxt["next_level"],
                "evidence": _evidence(bundle),
            },
        )
        name = getattr(bundle["agent"], "name", None) or "An agent"
        label = getattr(bundle["action_type"], "label", None) or "an action"
        await notify_owners(
            db,
            grant,
            bundle["agent"],
            type="autonomy_recommended",
            title=f"{name} is ready for {nxt['next_label']} on {label}",
            message=record_of(stats)["text"]
            + ". Someone who did not build the agent can approve the promotion.",
        )
    return bundle


# overview and grant pages


async def overview(db: AsyncSession, user: Any) -> dict[str, Any]:
    tid = user.tenant_id
    grants = await list_grants(db, tid)
    rows = []
    for g in grants:
        rows.append(grant_row(await grant_bundle(db, g)))
    by_id = {r["id"]: r for r in rows}
    demoted = []
    for c in await recent_demotions(db, tid):
        g = by_id.get(str(c.grant_id))
        if g is None:
            continue
        demoted.append({"grant": g, "change": change_json(c, {})})
    unmanaged = []
    types = await list_action_types(db, tid)
    by_tool: dict[str, Any] = {}
    for t in types:
        by_tool.setdefault(t.tool_name, t)
    for agent_id, agent_name, tool_name, count in await unmanaged_rows(db, tid):
        existing = by_tool.get(tool_name)
        unmanaged.append(
            {
                "agent_id": _s(agent_id),
                "agent_name": agent_name or "",
                "tool_name": tool_name,
                "count_7d": int(count or 0),
                "suggested_action_type": (
                    action_type_brief(existing)
                    if existing is not None
                    else {"key": tool_name, "label": _tool_label(tool_name)}
                ),
            }
        )
    return {
        "counts": await overview_counts(db, tid),
        "grants": rows,
        "ready_to_promote": [
            r for r in rows if r["level"] >= 1 and (r["next"] or {}).get("ready")
        ],
        "recently_demoted": demoted,
        "unmanaged": unmanaged,
    }


def change_json(c: Any, names: dict[str, str]) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "from_level": c.from_level,
        "from_label": L.level_label(c.from_level),
        "to_level": c.to_level,
        "to_label": L.level_label(c.to_level),
        "actor_type": c.actor_type,
        "actor_id": _s(c.actor_id),
        "actor_name": (names.get(str(c.actor_id)) if c.actor_id else "Abenix") or "",
        "reason": c.reason,
        "evidence": c.evidence,
        "created_at": _iso(c.created_at),
    }


def chart_points(actions: list[Any], changes: list[Any]) -> list[dict[str, Any]]:
    marks = sorted(
        (c for c in changes if c.from_level == c.to_level), key=lambda c: c.created_at
    )
    pts = []
    prev_hash = None
    prev_source = None
    rows = sorted(
        (a for a in actions if a.prediction or a.outcome),
        key=lambda a: a.created_at or _now(),
    )[-100:]
    mi = 0
    for a in rows:
        p = a.prediction or {}
        o = a.outcome or {}
        source = (p.get("source"), p.get("source_ref"))
        wm_mark = prev_source is not None and source != prev_source
        while mi < len(marks) and a.created_at and marks[mi].created_at <= a.created_at:
            wm_mark = True
            mi += 1
        pts.append(
            {
                "id": str(a.id),
                "created_at": _iso(a.created_at),
                "value": p.get("value"),
                "low": p.get("low"),
                "high": p.get("high"),
                "actual": o.get("value"),
                "within_band": (a.score or {}).get("within_band"),
                "revision_marker": bool(
                    prev_hash is not None
                    and a.agent_config_hash
                    and a.agent_config_hash != prev_hash
                ),
                "world_model_marker": bool(wm_mark),
            }
        )
        prev_hash = a.agent_config_hash or prev_hash
        prev_source = source
    return pts


async def grant_detail(db: AsyncSession, user: Any, grant_id: Any) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    bundle = await grant_bundle(db, g)
    row = grant_row(bundle)
    changes = await list_changes(db, g.id)
    names = await users_by_id(db, [c.actor_id for c in changes])
    if bundle["action_type"] is not None:
        row["action_type"] = action_type_json(bundle["action_type"])
    row["changes"] = [change_json(c, names) for c in changes]
    row["chart"] = chart_points(bundle["actions"], changes)
    row["policy"] = bundle["policy"]
    row["record"] = record_of(bundle["stats"])
    row["agent_creator_id"] = _s(getattr(bundle["agent"], "creator_id", None))
    return row


async def grant_actions_page(
    db: AsyncSession,
    user: Any,
    grant_id: Any,
    status: str | None,
    limit: int,
    before: str | None,
) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    before_dt = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise AutonomyError(
                "before must be a time like 2026-01-01T00:00:00Z.", 400, "BAD_REQUEST"
            ) from None
    rows = await action_page(db, user.tenant_id, g.id, status, limit + 1, before_dt)
    more = len(rows) > limit
    rows = rows[:limit]
    bundle = await grant_bundle(db, g)
    items = await action_rows(db, rows, stats_by_grant={str(g.id): bundle["stats"]})
    return {
        "items": items,
        "next_before": _iso(rows[-1].created_at) if more and rows else None,
    }


SAMPLE_SELF_APPROVAL = (
    "This is the sample, so you can approve it yourself. "
    "In real use someone else approves promotions."
)
SOLO_SELF_APPROVAL = (
    "You are the only person in this workspace who can approve promotions, "
    "so you can approve it yourself. It is recorded as self-approved."
)


async def someone_else_can_grant(db: AsyncSession, user: Any) -> bool:
    from app.core import capabilities as caps

    others = (
        await db.execute(
            select(User)
            .where(
                User.tenant_id == user.tenant_id,
                User.is_active.is_(True),
                User.id != user.id,
            )
            .limit(500)
        )
    ).scalars()
    for other in others:
        if await caps.has_capability(db, other, "autonomy.grant"):
            return True
    return False


async def self_approval_reason(
    db: AsyncSession, user: Any, action_type: Any
) -> str | None:
    """Why the author may approve their own promotion, None when someone else must."""
    if getattr(action_type, "is_sample", False):
        return SAMPLE_SELF_APPROVAL
    if await someone_else_can_grant(db, user):
        return None
    return SOLO_SELF_APPROVAL


async def _agent_creator_check(
    db: AsyncSession, user: Any, agent: Any, action_type: Any
) -> str | None:
    if agent is None or str(getattr(agent, "creator_id", "")) != str(user.id):
        return None
    reason = await self_approval_reason(db, user, action_type)
    if reason is None:
        raise AutonomyError(
            "You built this agent, so someone else has to approve its promotion.",
            403,
            "AUTHOR_CANNOT_GRANT",
        )
    return reason


async def promote(db: AsyncSession, user: Any, grant_id: Any) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    bundle = await grant_bundle(db, g)
    self_reason = await _agent_creator_check(
        db, user, bundle["agent"], bundle.get("action_type")
    )
    nxt = bundle["next"]
    if not nxt.get("ready"):
        missing = [r["label"] for r in nxt.get("requirements") or [] if not r["met"]]
        msg = "Not ready to move up yet."
        if nxt.get("next_level") is None:
            msg = "This is already the highest level."
        elif missing:
            msg = "Not ready to move up yet. Still needed: " + "; ".join(missing) + "."
        raise AutonomyError(
            msg,
            409,
            "NOT_READY",
            {"requirements": nxt.get("requirements") or [], "next": nxt},
        )
    if int(g.level) == 0:
        # back on to watching runs nothing, so it needs no sign-off
        await record_change(
            db,
            g,
            1,
            actor_type="user",
            actor_id=user.id,
            reason=f"Turned back on to watching by {_user_name(user) or 'an owner'}",
        )
        await db.commit()
        return {"applied": True, "grant": grant_row(await grant_bundle(db, g))}
    existing = (
        await db.execute(
            select(Approval).where(
                Approval.tenant_id == user.tenant_id,
                Approval.gate_kind == PROMOTE_GATE,
                Approval.status == ApprovalStatus.pending,
                Approval.payload["grant_id"].astext == str(g.id),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return approval_json(existing)
    agent = bundle["agent"]
    at = bundle["action_type"]
    to_level = int(nxt["next_level"])
    payload = {
        "kind": PROMOTE_GATE,
        "grant_id": str(g.id),
        "agent": {"id": str(g.agent_id), "name": getattr(agent, "name", "")},
        "agent_creator_id": _s(getattr(agent, "creator_id", None)),
        "action_type": action_type_brief(at),
        "self_approval": self_reason,
        "from": int(g.level),
        "from_label": L.level_label(g.level),
        "to": to_level,
        "to_label": L.level_label(to_level),
        "evidence": _evidence(bundle),
        "requirements": nxt.get("requirements") or [],
        "record": record_of(bundle["stats"]),
        "link": f"/autonomy/{g.id}",
    }
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=g.agent_id,
        title=f"Let {getattr(agent, 'name', 'the agent')} move to {L.level_label(to_level)} for {getattr(at, 'label', 'an action')}",
        payload=payload,
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=_now() + timedelta(days=7),
        gate_kind=PROMOTE_GATE,
        policy={"exclude_requester": False, "capability": "autonomy.grant"},
    )
    db.add(a)
    await db.flush()
    g.approval_id = a.id
    await events.emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": PROMOTE_GATE,
            "required_signoffs": 1,
        },
    )
    await db.commit()
    await _announce_approval(db, a, user)
    return approval_json(a)


async def _announce_approval(db: AsyncSession, approval: Any, requester: Any) -> None:
    """Same bell, Slack and webhook as an approval made through POST /api/approvals."""
    try:
        from app.routers.approvals import _notify_pending

        await _notify_pending(db, approval, requester=requester)
    except Exception as e:  # noqa: BLE001
        logger.warning("approval notification failed: %s", e)


def approval_json(a: Any) -> dict[str, Any]:
    st = getattr(a, "status", None)
    return {
        "id": str(a.id),
        "title": a.title,
        "gate_kind": a.gate_kind,
        "status": getattr(st, "value", st),
        "payload": a.payload or {},
        "required_signoffs": a.required_signoffs,
        "signoffs": a.signoffs or [],
        "expires_at": _iso(a.expires_at),
        "created_at": _iso(getattr(a, "created_at", None)),
        "link": "/approvals",
    }


async def promotion_denial(db: AsyncSession, user: Any, approval: Any) -> str | None:
    """Separation of duties for promotions: never the agent's author."""
    payload = approval.payload or {}
    creator = payload.get("agent_creator_id")
    if creator is None:
        g = await get_grant(db, approval.tenant_id, payload.get("grant_id"))
        agent = await get_agent(db, approval.tenant_id, g.agent_id) if g else None
        creator = _s(getattr(agent, "creator_id", None))
    if creator and str(creator) == str(user.id):
        g = await get_grant(db, approval.tenant_id, payload.get("grant_id"))
        at = await db.get(ActionType, g.action_type_id) if g else None
        # rechecked at sign time, a teammate may have joined since
        if await self_approval_reason(db, user, at) is None:
            return "You built this agent, so someone else has to approve its promotion."
    return None


async def on_promotion_resolved(db: AsyncSession, approval: Any, decider: Any) -> None:
    payload = approval.payload or {}
    g = await get_grant(db, approval.tenant_id, payload.get("grant_id"))
    if g is None:
        return
    status = getattr(approval.status, "value", approval.status)
    if status != "approved" or decider is None:
        if g.approval_id == approval.id:
            g.approval_id = None
        await db.commit()
        return
    to_level = int(payload.get("to") or 0)
    if int(g.level) != int(payload.get("from", -1)):
        logger.info("promotion %s skipped, grant moved since", approval.id)
        await db.commit()
        return
    bundle = await grant_bundle(db, g)
    if to_level > bundle["ceiling"]:
        await db.commit()
        return
    from_level = int(g.level)
    await record_change(
        db,
        g,
        to_level,
        actor_type="user",
        actor_id=decider.id,
        reason=(
            f"Self-approved by {_user_name(decider) or 'the author'}"
            if str(decider.id) == str(getattr(bundle.get("agent"), "creator_id", ""))
            else f"Promotion approved by {_user_name(decider) or 'a reviewer'}"
        ),
        evidence={
            **(payload.get("evidence") or _evidence(bundle)),
            "self_approved": str(decider.id)
            == str(getattr(bundle.get("agent"), "creator_id", "")),
        },
    )
    g.granted_by = decider.id
    g.approval_id = approval.id
    g.agent_config_hash = bundle["stats"].get("current_config_hash")
    await events.emit(
        db,
        g.tenant_id,
        "autonomy.promoted",
        {
            "grant_id": str(g.id),
            "agent_id": str(g.agent_id),
            "action_key": getattr(bundle["action_type"], "key", None),
            "from_level": from_level,
            "to_level": to_level,
            "approval_id": str(approval.id),
            "approved_by": str(decider.id),
        },
    )
    await db.commit()


async def on_action_gate_resolved(
    db: AsyncSession, approval: Any, decider: Any = None
) -> None:
    """Mirror an action:* approval onto its ledger row."""
    payload = approval.payload or {}
    action = await get_action(db, approval.tenant_id, payload.get("action_id"))
    if action is None:
        return
    status = getattr(approval.status, "value", approval.status)
    edited = payload.get("edited_arguments")
    note = ""
    for s in reversed(approval.signoffs or []):
        if s.get("reason"):
            note = s["reason"]
            break
    if status == "approved":
        action.status = "edited" if isinstance(edited, dict) else "approved"
    elif status in ("denied", "returned"):
        action.status = "rejected"
    elif status == "expired":
        action.status = "expired"
    else:
        return
    action.decided_by = getattr(decider, "id", None)
    action.decided_at = approval.decided_at or _now()
    action.decision_note = note or None
    await _gate_lesson(action, edited, note, decider, db)
    score = dict(action.score or {})
    score["agreement"] = L.agreement_for(action.status, None)
    action.score = score
    if action.grant_id:
        g = await get_grant(db, approval.tenant_id, action.grant_id)
        if g is not None:
            await reevaluate(db, g)
    await db.commit()


async def _gate_lesson(
    action: Any, edited: Any, note: str, decider: Any, db: AsyncSession
) -> None:
    from app.services import lessons

    by = getattr(decider, "id", None)
    if action.status == "rejected" and note:
        await lessons.capture_action(db, action, "autonomy_reject", note=note, by=by)
    elif action.status == "edited":
        await lessons.capture_action(
            db,
            action,
            "autonomy_edit",
            expected=json.dumps(edited, default=str),
            note=note or None,
            by=by,
        )
    elif action.status == "approved":
        await lessons.capture_action(db, action, "positive", by=by)


def validate_edited_arguments(
    payload: dict[str, Any], edited: Any
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(edited, dict):
        return None, "edited_arguments must be an object of argument names to values."
    original = payload.get("arguments") or {}
    extra = sorted(set(edited) - set(original))
    if extra:
        return None, (
            "You can only change arguments the agent sent. Not allowed: "
            + ", ".join(extra)
            + "."
        )
    if payload.get("editable_arguments") is False:
        return None, "This action does not allow edits. Approve or reject it."
    return {**original, **edited}, None


# grant management


async def demote_by_user(
    db: AsyncSession, user: Any, grant_id: Any, to_level: int, reason: str
) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    if to_level < 0 or to_level >= int(g.level):
        raise AutonomyError(
            f"Pick a level below {L.level_label(g.level)}. To move up, use Promote.",
            400,
            "BAD_LEVEL",
        )
    reason = (
        reason or ""
    ).strip() or f"Turned down by {_user_name(user) or 'an owner'}"
    bundle = await grant_bundle(db, g)
    await demote(db, g, to_level, reason=reason, actor=user, bundle=bundle)
    await db.commit()
    return grant_row(await grant_bundle(db, g))


async def patch_grant(
    db: AsyncSession, user: Any, grant_id: Any, body: dict[str, Any]
) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    if "state" in body and body["state"] is not None:
        if body["state"] not in GRANT_STATES:
            raise AutonomyError("state must be active or paused.", 400, "BAD_STATE")
        g.state = body["state"]
    if "scope" in body:
        scope = body["scope"]
        if scope is not None and not _valid_scope(scope):
            raise AutonomyError(
                'scope must look like {"param": "site", "equals": "A"} or {"param": "topic", "glob": "plant.*"}.',
                400,
                "BAD_SCOPE",
            )
        shash = scope_hash(scope)
        clash = await find_grant(
            db, user.tenant_id, g.agent_id, g.action_type_id, shash
        )
        if clash is not None and clash.id != g.id:
            raise AutonomyError(
                "This agent already has a grant for that scope.", 409, "SCOPE_TAKEN"
            )
        g.scope = scope
        g.scope_hash = shash
    if body.get("ceiling") is not None:
        bundle = await grant_bundle(db, g)
        new_cap = int(body["ceiling"])
        if new_cap < 0 or new_cap > bundle["ceiling"]:
            raise AutonomyError(
                f"A ceiling can only be lowered here. It is {L.level_label(bundle['ceiling'])} now. "
                "Raising it is an admin change on the risk page.",
                400,
                "CEILING_RAISE",
            )
        g.ceiling = new_cap
        if int(g.level) > new_cap:
            await demote(
                db,
                g,
                new_cap,
                reason=f"Ceiling lowered to {L.level_label(new_cap)}",
                actor=user,
                bundle=bundle,
            )
    await db.commit()
    return grant_row(await grant_bundle(db, g))


def _valid_scope(scope: Any) -> bool:
    return (
        isinstance(scope, dict)
        and isinstance(scope.get("param"), str)
        and bool(scope.get("param"))
        and ("equals" in scope or "glob" in scope or "in" in scope)
    )


async def remove_grant(db: AsyncSession, user: Any, grant_id: Any) -> dict[str, Any]:
    g = await get_grant(db, user.tenant_id, grant_id)
    if g is None:
        raise AutonomyError("This grant was not found.", 404, "NOT_FOUND")
    if int(g.level) != 0:
        await record_change(
            db, g, 0, actor_type="user", actor_id=user.id, reason="Unenrolled"
        )
    g.state = "removed"
    await db.commit()
    return {"id": str(g.id), "removed": True}


# action types


def _tool_label(tool_name: str) -> str:
    return (tool_name or "").replace("_", " ").strip().capitalize() or "Action"


def validate_world_model(wm: Any) -> str | None:
    if wm is None:
        return None
    if not isinstance(wm, dict) or wm.get("kind") not in WORLD_MODEL_KINDS:
        return "How we predict needs a kind: agent_stated, decision, ml_model or none."
    if wm["kind"] in ("decision", "ml_model") and not wm.get("ref"):
        return "Name the decision or model that makes the prediction."
    t = wm.get("timeout_s")
    if t is not None and (not isinstance(t, (int, float)) or t <= 0 or t > 120):
        return "The prediction timeout must be between 1 and 120 seconds."
    return None


def validate_probe(probe: Any) -> str | None:
    if probe is None:
        return None
    if not isinstance(probe, dict) or probe.get("kind") not in PROBE_KINDS:
        return "How we judge success needs a kind: tool, manual, api or none."
    after = probe.get("after_s", 0)
    if not isinstance(after, (int, float)) or after < 0 or after > 90 * 86400:
        return "Check the outcome between 0 seconds and 90 days after the action."
    if probe["kind"] == "tool" and not probe.get("tool"):
        return "Pick the tool that reads the outcome."
    return None


def validate_match(match: Any) -> str | None:
    if match is None:
        return None
    if not _valid_scope(match):
        return 'match must look like {"param": "topic", "glob": "controls.*"}.'
    return None


async def validate_limits_key(db: AsyncSession, tenant_id: Any, key: Any) -> str | None:
    if not key:
        return None
    from models.decision import DecisionModel

    found = (
        await db.execute(
            select(DecisionModel.id).where(
                DecisionModel.tenant_id == tenant_id,
                DecisionModel.key == str(key),
                DecisionModel.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if found is None:
        return (
            f"There is no decision called {key}. Build the limits in Decisions first."
        )
    return None


POLICY_COUNTS = {
    "min_reviews": (1, 10000),
    "min_executed": (1, 100000),
    "harm_free_days": (0, 3650),
    "min_days_at_level": (0, 3650),
}
POLICY_RATES = (
    "min_agreement_lb",
    "min_accuracy_lb",
    "min_no_edit_rate",
    "max_unknown_rate",
    "max_reject_rate",
)
POLICY_TOP = {
    "window": (5, 1000),
    "revision_recheck": (1, 1000),
    "approval_expires_s": (60, 30 * 86400),
}


def _bad_number(v: Any, lo: float, hi: float, whole: bool) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return True
    if whole and int(v) != v:
        return True
    return not lo <= v <= hi


def validate_policy(policy: Any) -> str | None:
    if not isinstance(policy, dict):
        return "policy must be an object of threshold overrides."
    for name, value in policy.items():
        if name in L.STEP_FOR_LEVEL.values():
            if not isinstance(value, dict):
                return f"{name} must be an object of thresholds."
            for k, v in value.items():
                if k in POLICY_COUNTS:
                    lo, hi = POLICY_COUNTS[k]
                    if _bad_number(v, lo, hi, True):
                        return f"{k} must be a whole number from {lo} to {hi}."
                elif k in POLICY_RATES and _bad_number(v, 0, 1, False):
                    return f"{k} must be a share between 0 and 1, such as 0.7 for 70%."
        elif name in POLICY_TOP:
            lo, hi = POLICY_TOP[name]
            if _bad_number(value, lo, hi, True):
                return f"{name} must be a whole number from {lo} to {hi}."
        elif name == "demote_margin" and _bad_number(value, 0, 1, False):
            return "demote_margin must be a share between 0 and 1."
    return None


async def action_type_spec_problem(
    db: AsyncSession, tenant_id: Any, spec: dict[str, Any]
) -> str | None:
    for check in (
        validate_world_model(spec.get("world_model")),
        validate_probe(spec.get("outcome_probe")),
        validate_match(spec.get("match")),
    ):
        if check:
            return check
    mbw = spec.get("max_band_width")
    if mbw is not None and (not isinstance(mbw, (int, float)) or mbw <= 0 or mbw > 10):
        return "The widest allowed band must be a number above 0, such as 0.5 for 50%."
    if spec.get("policy") is not None:
        problem = validate_policy(spec["policy"])
        if problem:
            return problem
    return await validate_limits_key(db, tenant_id, spec.get("limits_decision_key"))


PATCHABLE = (
    "label",
    "description",
    "world_model",
    "outcome_probe",
    "limits_decision_key",
    "max_band_width",
    "match",
    "policy",
    "reversible",
    "ceiling",
)


async def patch_action_type(
    db: AsyncSession, user: Any, type_id: Any, body: dict[str, Any]
) -> dict[str, Any]:
    at = await get_action_type(db, user.tenant_id, type_id)
    if at is None:
        raise AutonomyError("This action type was not found.", 404, "NOT_FOUND")
    problem = await action_type_spec_problem(db, user.tenant_id, body)
    if problem:
        raise AutonomyError(problem, 400, "BAD_ACTION_TYPE")
    if "label" in body and not str(body.get("label") or "").strip():
        raise AutonomyError("Give the action a name.", 400, "BAD_ACTION_TYPE")
    if body.get("ceiling") is not None:
        cap = int(body["ceiling"])
        if cap < 0 or (at.ceiling is not None and cap > at.ceiling) or cap > 4:
            raise AutonomyError(
                "A ceiling can only be lowered here. Raising it is an admin change on the risk page.",
                400,
                "CEILING_RAISE",
            )
    wm_changed = "world_model" in body and body["world_model"] != at.world_model
    policy_changed = "policy" in body and (body["policy"] or None) != (
        at.policy or None
    )
    for k in PATCHABLE:
        if k in body:
            setattr(at, k, body[k])
    if wm_changed:
        # no demotion, the chart shows the break
        for g in await list_grants(db, user.tenant_id, action_type_id=at.id):
            await record_change(
                db,
                g,
                int(g.level),
                actor_type="user",
                actor_id=user.id,
                reason="How we predict changed",
                evidence={"world_model": body["world_model"]},
            )
    if policy_changed:
        # on the record so a lowered bar is never silent
        for g in await list_grants(db, user.tenant_id, action_type_id=at.id):
            await record_change(
                db,
                g,
                int(g.level),
                actor_type="user",
                actor_id=user.id,
                reason=f"Thresholds changed by {_user_name(user) or 'an owner'}",
                evidence={"policy": body["policy"]},
            )
    if body.get("ceiling") is not None:
        for g in await list_grants(db, user.tenant_id, action_type_id=at.id):
            if int(g.level) > int(body["ceiling"]):
                await demote(
                    db,
                    g,
                    int(body["ceiling"]),
                    reason=f"Ceiling lowered to {L.level_label(body['ceiling'])}",
                    actor=user,
                )
    await db.commit()
    # updated_at is set by the database, read it back before serialising
    await db.refresh(at)
    return action_type_json(at)


def render(template: Any, ctx: dict[str, Any]) -> Any:
    """Fill {{args.x}} style placeholders, keeping the value's type when it is the whole string."""
    if isinstance(template, dict):
        return {k: render(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [render(v, ctx) for v in template]
    if not isinstance(template, str):
        return template
    whole = re.fullmatch(r"\s*\{\{\s*([^}]+?)\s*\}\}\s*", template)
    if whole:
        return extract_path(ctx, whole.group(1))
    return re.sub(
        r"\{\{\s*([^}]+?)\s*\}\}",
        lambda m: str(extract_path(ctx, m.group(1)) or ""),
        template,
    )


def extract_path(obj: Any, path: str | None) -> Any:
    """a.b[0].c or $.a.b, enough for reading one number out of a tool result."""
    if not path:
        return obj
    p = path.strip()
    if p.startswith("$"):
        p = p[1:].lstrip(".")
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", p):
        if part.startswith("["):
            i = int(part[1:-1])
            if isinstance(obj, list) and -len(obj) <= i < len(obj):
                obj = obj[i]
            else:
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None
    return obj


def parse_content(content: Any) -> Any:
    if isinstance(content, (dict, list)):
        return content
    if isinstance(content, str):
        try:
            return json.loads(content)
        except ValueError:
            m = re.search(r"\{.*\}", content, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except ValueError:
                    return content
    return content


async def run_tool(
    db: AsyncSession, user: Any, tool: str, arguments: dict[str, Any]
) -> tuple[bool, Any, str]:
    """Through the same direct invocation path as POST /api/tools/{slug}/execute."""
    from app.routers.tools import execute_tool

    resp = await execute_tool(tool, {"arguments": arguments or {}}, None, user, db)
    try:
        body = json.loads(bytes(resp.body))
    except Exception:  # noqa: BLE001
        return False, None, f"The tool answered {getattr(resp, 'status_code', '?')}"
    if body.get("error"):
        return False, None, str((body["error"] or {}).get("message") or "Tool failed")
    data = body.get("data") or {}
    if data.get("is_error"):
        return (
            False,
            data.get("content"),
            str(data.get("content") or "Tool failed")[:300],
        )
    return True, parse_content(data.get("content")), ""


def limit_facts(args: dict[str, Any] | None, target: Any) -> dict[str, Any]:
    """The arguments as facts, with JSON text such as an MQTT payload read as an object."""
    facts: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and v.lstrip().startswith("{"):
            try:
                parsed = json.loads(v)
            except ValueError:
                parsed = None
            facts[k] = parsed if isinstance(parsed, dict) else v
        else:
            facts[k] = v
    if target is not None:
        facts.setdefault("target", target)
    return facts


async def evaluate_limits(
    db: AsyncSession, tenant_id: Any, key: str, facts: dict[str, Any]
) -> dict[str, Any]:
    from engine.decisions import service as S

    try:
        out = await S.evaluate(
            db, str(tenant_id), key, facts, want_trace=False, persist=False
        )
    except S.DecisionError as e:
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limit check could not run: {e.message}"],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limit check could not run: {e}"],
        }
    return limits_from_decision(out, key)


def limits_from_decision(out: dict[str, Any], key: str) -> dict[str, Any]:
    """Read ok and reason from a limits decision. Missing facts are a breach."""
    outcome = out.get("outcome")
    if outcome == "missing_facts":
        miss = ", ".join(out.get("missing_facts") or []) or "some arguments"
        return {
            "ok": False,
            "decision_key": key,
            "reasons": [f"The limit check needs {miss}"],
        }
    # no breach rule matched, same reading as the runtime gate
    if outcome == "no_match":
        return {"ok": True, "decision_key": key, "reasons": []}
    if outcome != "decided":
        return {
            "ok": False,
            "decision_key": key,
            "reasons": ["The limits could not read these arguments"],
        }
    results = out.get("result")
    results = results if isinstance(results, list) else [results]
    ok = True
    reasons: list[str] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        fine = r.get("ok", r.get("allowed"))
        if r.get("breach") is True or fine is False:
            ok = False
            why = r.get("reasons") or r.get("reason")
            if isinstance(why, list):
                reasons.extend(str(x) for x in why if x)
            elif why:
                reasons.append(str(why))
    if not ok and not reasons:
        reasons = ["A limit was breached"]
    return {"ok": ok, "decision_key": key, "reasons": reasons}


async def test_action_type(
    db: AsyncSession, user: Any, type_id: Any, part: str, action_id: Any = None
) -> dict[str, Any]:
    at = await get_action_type(db, user.tenant_id, type_id)
    if at is None:
        raise AutonomyError("This action type was not found.", 404, "NOT_FOUND")
    action = None
    if action_id:
        action = await get_action(db, user.tenant_id, action_id)
        if action is None or str(action.action_type_id) != str(at.id):
            raise AutonomyError("That action was not found.", 404, "NOT_FOUND")
    else:
        action = (
            await db.execute(
                select(AgentAction)
                .where(
                    AgentAction.tenant_id == user.tenant_id,
                    AgentAction.action_type_id == at.id,
                )
                .order_by(AgentAction.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    args = dict((action.arguments if action else None) or {})
    if part == "limits":
        if not at.limits_decision_key:
            return {
                "ok": True,
                "result": None,
                "message": "No hard limits are set. Pick a decision under Hard limits to add them.",
            }
        if action is None:
            return {
                "ok": False,
                "result": None,
                "message": "There is no action to test with yet. Run the agent once, then test again.",
            }
        facts = limit_facts(args, action.target)
        res = await evaluate_limits(db, user.tenant_id, at.limits_decision_key, facts)
        return {
            "ok": True,
            "result": res,
            "message": (
                "The last action was inside the limits."
                if res["ok"]
                else "The last action would be blocked: " + "; ".join(res["reasons"])
            ),
        }
    if part == "world_model":
        wm = at.world_model or {"kind": "none"}
        kind = wm.get("kind")
        if kind == "agent_stated":
            pred = action.prediction if action else None
            return {
                "ok": pred is not None,
                "result": pred,
                "message": (
                    "The agent states its own prediction with each call. This is the last one."
                    if pred
                    else "The agent has not stated a prediction yet. Run it once, then test again."
                ),
            }
        if kind == "decision":
            ctx = {"args": args, "target": getattr(action, "target", None)}
            facts = render(wm.get("inputs") or {"args": "{{args}}"}, ctx)
            from engine.decisions import service as S

            try:
                out = await S.evaluate(
                    db, str(user.tenant_id), wm["ref"], facts, want_trace=False
                )
            except S.DecisionError as e:
                return {"ok": False, "result": None, "message": e.message}
            return {
                "ok": out.get("outcome") == "decided",
                "result": out.get("result"),
                "message": f"The decision {wm['ref']} answered.",
            }
        if kind == "ml_model":
            return {
                "ok": False,
                "result": None,
                "message": "ML model predictions are made by the runtime during a run. Run the agent and check the prediction on its action card.",
            }
        return {
            "ok": True,
            "result": None,
            "message": "No prediction is made for this action. Pick a way to predict so it can earn Acts within limits.",
        }
    if part == "outcome_probe":
        probe = at.outcome_probe or {"kind": "none"}
        if probe.get("kind") == "tool":
            ok, content, err = await run_tool(
                db, user, probe["tool"], probe.get("arguments") or {}
            )
            if not ok:
                return {
                    "ok": False,
                    "result": None,
                    "message": f"The tool failed: {err}",
                }
            value = extract_path(content, probe.get("path"))
            return {
                "ok": value is not None,
                "result": {"value": value, "raw": content},
                "message": (
                    f"Read {probe.get('metric') or 'the outcome'} = {value}."
                    if value is not None
                    else f"The tool answered but {probe.get('path')} was not in it."
                ),
            }
        if probe.get("kind") in ("manual", "api"):
            return {
                "ok": True,
                "result": None,
                "message": (
                    "A person enters the outcome on the action card."
                    if probe["kind"] == "manual"
                    else "Your app reports the outcome through the SDK."
                ),
            }
        return {
            "ok": True,
            "result": None,
            "message": "Outcomes are not checked, so this action cannot be scored.",
        }
    raise AutonomyError(
        "part must be world_model, outcome_probe or limits.", 400, "BAD_PART"
    )


# enrolment


def _effect_dict(effect: Any) -> dict[str, Any] | None:
    if effect is None:
        return None
    if dataclasses.is_dataclass(effect):
        return dataclasses.asdict(effect)
    if isinstance(effect, dict):
        return dict(effect)
    return {"kind": str(getattr(effect, "kind", "external"))}


def tool_effect(tool_name: str) -> tuple[dict[str, Any] | None, str]:
    try:
        from engine.agent_executor import get_tool_class

        cls = get_tool_class(tool_name)
    except Exception:  # noqa: BLE001
        cls = None
    if cls is None:
        return None, "low"
    return _effect_dict(getattr(cls, "effect", None)), str(
        getattr(cls, "risk_tier", "low") or "low"
    )


def prefill_for(tool_name: str, effect: dict[str, Any] | None) -> dict[str, Any]:
    if tool_name == "sample_plant":
        return sample_action_type_spec()
    label = (effect or {}).get("label") or _tool_label(tool_name)
    return {
        "label": label,
        "world_model": {"kind": "agent_stated", "metric": "", "timeout_s": 10},
        "outcome_probe": {"kind": "manual", "after_s": 3600},
        "limits_decision_key": None,
        "max_band_width": 0.5,
    }


async def enrol_options(db: AsyncSession, user: Any, agent_id: Any) -> dict[str, Any]:
    agent = await get_agent(db, user.tenant_id, agent_id)
    if agent is None:
        raise AutonomyError("This agent was not found.", 404, "NOT_FOUND")
    tools = list(((agent.model_config_ or {}).get("tools")) or [])
    types = await list_action_types(db, user.tenant_id)
    grants = await list_grants(db, user.tenant_id, agent_id=agent.id)
    out = []
    for name in tools:
        if not isinstance(name, str):
            continue
        effect, tier = tool_effect(name)
        mine = [t for t in types if t.tool_name == name]
        if (effect is None or effect.get("kind") == "read") and not mine:
            continue
        ids = {t.id for t in mine}
        rows = [
            grant_row(await grant_bundle(db, g))
            for g in grants
            if g.action_type_id in ids
        ]
        plain = next((t for t in mine if not t.match), None)
        prefill = prefill_for(name, effect)
        prefill.setdefault("match_param", (effect or {}).get("target_param") or "")
        out.append(
            {
                "tool_name": name,
                "effect": effect,
                "risk_tier": tier,
                "existing_action_type": (
                    action_type_json(plain) if plain is not None else None
                ),
                "existing_action_types": [action_type_json(t) for t in mine],
                "grant": rows[0] if rows else None,
                "grants": rows,
                "prefill": prefill,
            }
        )
    return {
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "risk_tier": agent_tier(agent),
            "creator_id": _s(agent.creator_id),
        },
        "tools": out,
    }


def settings_conflict(at: Any, spec: dict[str, Any]) -> list[str]:
    """What the enrol form asks for that the existing action type does differently."""
    diffs: list[str] = []
    if "limits_decision_key" in spec and (spec.get("limits_decision_key") or None) != (
        at.limits_decision_key or None
    ):
        diffs.append("hard limits")
    wm, have_wm = spec.get("world_model"), at.world_model or {}
    if isinstance(wm, dict) and (
        wm.get("kind") != have_wm.get("kind")
        or (wm.get("ref") or None) != (have_wm.get("ref") or None)
    ):
        diffs.append("how we predict")
    probe, have_probe = spec.get("outcome_probe"), at.outcome_probe or {}
    if isinstance(probe, dict) and probe.get("kind") != have_probe.get("kind"):
        diffs.append("how we judge success")
    return diffs


def _key_for(tool_name: str, match: dict[str, Any] | None) -> str:
    if match and match.get("glob"):
        q = re.sub(r"[^a-z0-9._-]+", "_", str(match["glob"]).lower()).strip("_.")
        return f"{tool_name}:{q}" if q else tool_name
    if match and match.get("equals") is not None:
        q = re.sub(r"[^a-z0-9._-]+", "_", str(match["equals"]).lower()).strip("_.")
        return f"{tool_name}:{q}" if q else tool_name
    return tool_name


async def enrol(
    db: AsyncSession,
    user: Any,
    agent_id: Any,
    tool_name: str,
    spec: dict[str, Any],
    scope: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    is_sample: bool = False,
) -> dict[str, Any]:
    agent = await get_agent(db, user.tenant_id, agent_id)
    if agent is None:
        raise AutonomyError("This agent was not found.", 404, "NOT_FOUND")
    tool_name = (tool_name or "").strip()
    tools = list(((agent.model_config_ or {}).get("tools")) or [])
    if tool_name not in tools:
        raise AutonomyError(
            f"{agent.name} does not use the tool {tool_name}. Add it to the agent first.",
            400,
            "TOOL_NOT_ON_AGENT",
        )
    spec = dict(spec or {})
    if not str(spec.get("label") or "").strip():
        raise AutonomyError("Give the action a name.", 400, "BAD_ACTION_TYPE")
    problem = await action_type_spec_problem(db, user.tenant_id, spec)
    if problem:
        raise AutonomyError(problem, 400, "BAD_ACTION_TYPE")
    if scope is not None and not _valid_scope(scope):
        raise AutonomyError(
            'scope must look like {"param": "site", "equals": "A"}.', 400, "BAD_SCOPE"
        )
    key = key or spec.get("key") or _key_for(tool_name, spec.get("match"))
    at = await get_action_type_by_key(db, user.tenant_id, key)
    effect, _tier = tool_effect(tool_name)
    if at is None:
        at = ActionType(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            key=key,
            label=str(spec["label"]).strip(),
            description=str(spec.get("description") or ""),
            tool_name=tool_name,
            match=spec.get("match"),
            effect=spec.get("effect") or effect,
            world_model=spec.get("world_model") or {"kind": "agent_stated"},
            outcome_probe=spec.get("outcome_probe")
            or {"kind": "manual", "after_s": 3600},
            limits_decision_key=spec.get("limits_decision_key"),
            max_band_width=spec.get("max_band_width"),
            reversible=bool(
                spec.get(
                    "reversible",
                    (spec.get("effect") or effect or {}).get("reversible", False),
                )
            ),
            ceiling=spec.get("ceiling"),
            policy=spec.get("policy"),
            is_sample=is_sample,
            created_by=user.id,
        )
        db.add(at)
        await db.flush()
    elif at.tool_name != tool_name:
        raise AutonomyError(
            f"The action {key} belongs to the tool {at.tool_name}. Pick another name.",
            409,
            "KEY_TAKEN",
        )
    shash = scope_hash(scope)
    g = await find_grant(db, user.tenant_id, agent.id, at.id, shash)
    if g is not None and g.state != "removed":
        await db.commit()
        return grant_row(await grant_bundle(db, g))
    if not is_sample and (diffs := settings_conflict(at, spec)):
        raise AutonomyError(
            f'The action "{at.label}" already covers these calls with different '
            f"{' and '.join(diffs)}. Pick it under Existing actions to use its settings, "
            "or narrow Which calls so this becomes a new action.",
            409,
            "TYPE_EXISTS",
            {"action_type": action_type_json(at)},
        )
    current = await config_hash(db, agent.id)
    if g is None:
        g = AutonomyGrant(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            agent_id=agent.id,
            action_type_id=at.id,
            scope=scope,
            scope_hash=shash,
            level=0,
            ceiling=L.effective_ceiling(agent_tier(agent), at.ceiling, None),
            state="active",
            level_since=_now(),
            granted_by=user.id,
            agent_config_hash=current,
            reason="Enrolled",
            created_at=_now(),
        )
        db.add(g)
        await db.flush()
    else:
        g.state = "active"
        g.granted_by = user.id
        g.agent_config_hash = current
    await record_change(
        db,
        g,
        1,
        actor_type="user",
        actor_id=user.id,
        reason=f"Enrolled by {_user_name(user) or 'an owner'}, watching first",
    )
    await db.commit()
    return grant_row(await grant_bundle(db, g))


# reviews, outcomes and harm


async def reviews(db: AsyncSession, user: Any, limit: int) -> dict[str, Any]:
    rows = await pending_reviews(db, user.tenant_id, limit)
    settings = await tenant_settings(db, user.tenant_id)
    # off by default, an admin can hide the proposal to avoid anchoring
    hide = (settings.get("autonomy") or {}).get("hide_until_answered") is True
    inputs = await execution_inputs(db, [r.execution_id for r in rows])
    items = await action_rows(
        db, rows, hide_cards={str(r.id) for r in rows} if hide else set()
    )
    for item, r in zip(items, rows):
        msg = inputs.get(str(r.execution_id)) if r.execution_id else None
        item["situation"] = situation_for(r, item, msg, hidden=hide)
        item["proposal_hidden"] = hide
        if hide:
            for k in ("arguments", "intent", "prediction"):
                item[k] = None
    return {"items": items, "hide_until_answered": hide}


def situation_for(
    action: Any, item: dict[str, Any], message: str | None, *, hidden: bool = False
) -> str:
    who = (item.get("agent") or {}).get("name") or "The agent"
    label = ((item.get("action_type") or {}).get("label")) or action.tool_name
    parts = [f"{who} was asked: {message.strip()}" if message else f"{who} ran."]
    parts.append(f"It wanted to {label[0].lower() + label[1:] if label else 'act'}")
    if action.target:
        parts[-1] += f" on {action.target}"
    parts[-1] += (
        ". What would you have done?" if hidden else ". Would you have done the same?"
    )
    return " ".join(parts)


async def _grant_stats(db: AsyncSession, action: Any) -> dict[str, Any] | None:
    if not action.grant_id:
        return None
    g = await get_grant(db, action.tenant_id, action.grant_id)
    return (await grant_bundle(db, g))["stats"] if g else None


async def action_detail(db: AsyncSession, user: Any, action_id: Any) -> dict[str, Any]:
    a = await get_action(db, user.tenant_id, action_id)
    if a is None:
        raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
    stats = await _grant_stats(db, a)
    return (await action_rows(db, [a], stats_by_grant={str(a.grant_id): stats or {}}))[
        0
    ]


async def review(
    db: AsyncSession,
    user: Any,
    action_id: Any,
    answer: str,
    alternative: str | None,
) -> dict[str, Any]:
    if answer not in ("agree", "different", "unsure"):
        raise AutonomyError(
            "answer must be agree, different or unsure.", 400, "BAD_ANSWER"
        )
    a = await get_action(db, user.tenant_id, action_id)
    if a is None:
        raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
    if a.status != "watching":
        raise AutonomyError(
            "Only actions recorded in watching mode take a review.", 409, "NOT_WATCHING"
        )
    if a.reviewer_answer:
        raise AutonomyError(
            "Someone already reviewed this action.", 409, "ALREADY_REVIEWED"
        )
    if answer == "different" and not (alternative or "").strip():
        raise AutonomyError(
            "Say what you did instead, so the agent's record is fair.",
            400,
            "ALTERNATIVE_REQUIRED",
        )
    a.reviewer_answer = answer
    a.reviewer_alternative = (alternative or "").strip() or None
    a.decided_by = user.id
    a.decided_at = _now()
    if answer in ("different", "agree"):
        from app.services import lessons

        await lessons.capture_action(
            db,
            a,
            "autonomy_alternative" if answer == "different" else "positive",
            expected=a.reviewer_alternative,
            by=user.id,
        )
    score = dict(a.score or {})
    score["agreement"] = L.agreement_for("watching", answer)
    a.score = score
    if a.grant_id:
        g = await get_grant(db, user.tenant_id, a.grant_id)
        if g is not None:
            await reevaluate(db, g)
    await db.commit()
    return await action_detail(db, user, a.id)


async def record_outcome(
    db: AsyncSession,
    user: Any,
    action_id: Any,
    value: Any,
    note: str | None = None,
    *,
    source: str = "manual",
) -> dict[str, Any]:
    a = await get_action(db, user.tenant_id, action_id)
    if a is None:
        raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
    if a.status != "executed":
        raise AutonomyError(
            "This action did not run, so there is no outcome to record.",
            409,
            "NOT_EXECUTED",
        )
    if value is None or (isinstance(value, str) and not value.strip()):
        raise AutonomyError("Enter what actually happened.", 400, "BAD_VALUE")
    at = await get_action_type(db, user.tenant_id, a.action_type_id)
    await apply_outcome(
        db, a, at, value, source=source, by=getattr(user, "id", None), note=note
    )
    if a.grant_id:
        g = await get_grant(db, user.tenant_id, a.grant_id)
        if g is not None:
            await reevaluate(db, g)
    await db.commit()
    return await action_detail(db, user, a.id)


async def apply_outcome(
    db: AsyncSession,
    action: Any,
    at: Any,
    value: Any,
    *,
    source: str,
    by: Any = None,
    note: str | None = None,
) -> None:
    pred = action.prediction or {}
    metric = pred.get("metric") or (
        (at.outcome_probe or {}).get("metric") if at else None
    )
    action.outcome = {
        "metric": metric,
        "value": value,
        "source": source,
        "observed_at": _now().isoformat(),
        "by": _s(by),
        "note": note or None,
    }
    action.outcome_status = "manual" if source == "manual" else "observed"
    prev = action.score or {}
    score = L.score_action(
        action.prediction,
        value,
        getattr(at, "max_band_width", None),
        status=action.status,
        reviewer_answer=action.reviewer_answer,
        harm=bool(action.harm),
    )
    if prev.get("agreement") is not None:
        score["agreement"] = prev["agreement"]
    action.score = score
    if score.get("within_band") is False:
        from app.services import lessons

        await lessons.capture_action(
            db,
            action,
            "band_miss",
            note=f"Predicted {pred.get('low')} to {pred.get('high')} for {metric}, got {value}",
            by=by,
        )
    await events.emit(
        db,
        action.tenant_id,
        "action.outcome_recorded",
        {
            "action_id": str(action.id),
            "agent_id": _s(action.agent_id),
            "action_key": getattr(at, "key", None),
            "metric": metric,
            "value": value,
            "within_band": score["within_band"],
            "source": source,
        },
    )


async def flag_harm(
    db: AsyncSession, user: Any, action_id: Any, note: str
) -> dict[str, Any]:
    a = await get_action(db, user.tenant_id, action_id)
    if a is None:
        raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
    note = (note or "").strip()
    if not note:
        raise AutonomyError("Say what went wrong.", 400, "NOTE_REQUIRED")
    if a.harm:
        raise AutonomyError(
            "Harm is already flagged on this action.", 409, "ALREADY_FLAGGED"
        )
    a.harm = True
    a.harm_note = note
    from app.services import lessons

    await lessons.capture_action(db, a, "harm", note=note, by=user.id)
    a.score = {**(a.score or {}), "harm": True}
    if a.grant_id:
        g = await get_grant(db, user.tenant_id, a.grant_id)
        if g is not None:
            to = L.harm_demotion(int(g.level))
            if to < int(g.level):
                await demote(
                    db,
                    g,
                    to,
                    reason=f"Harm flagged by {_user_name(user) or 'a reviewer'}: {note}",
                )
            else:
                agent = await get_agent(db, g.tenant_id, g.agent_id)
                await notify_owners(
                    db,
                    g,
                    agent,
                    type="autonomy_demoted",
                    title=f"Harm flagged on an action by {getattr(agent, 'name', 'an agent')}",
                    message=note,
                    exclude=user.id,
                )
    await db.commit()
    return await action_detail(db, user, a.id)


# external actions from the SDK


def _matches(rule: dict[str, Any] | None, args: dict[str, Any]) -> bool:
    if not rule:
        return True
    import fnmatch

    got = args.get(rule.get("param"))
    if "equals" in rule:
        return str(got) == str(rule["equals"])
    if "glob" in rule:
        return got is not None and fnmatch.fnmatchcase(str(got), str(rule["glob"]))
    if "in" in rule:
        return got in (rule.get("in") or [])
    return True


async def pick_grant(
    db: AsyncSession, tenant_id: Any, at: Any, agent_id: Any, args: dict[str, Any]
) -> Any:
    grants = [
        g
        for g in await list_grants(db, tenant_id, action_type_id=at.id)
        if agent_id is None or str(g.agent_id) == str(agent_id)
    ]
    if agent_id is None and len({str(g.agent_id) for g in grants}) > 1:
        return None
    scoped = [g for g in grants if g.scope and _matches(g.scope, args)]
    if scoped:
        return scoped[0]
    return next((g for g in grants if not g.scope), None)


async def propose(db: AsyncSession, user: Any, body: dict[str, Any]) -> dict[str, Any]:
    key = str(body.get("action_key") or "").strip()
    at = await get_action_type_by_key(db, user.tenant_id, key) if key else None
    if at is None:
        raise AutonomyError(
            f"There is no action type called {key or '(blank)'}. Enrol it on the Autonomy page first.",
            404,
            "UNKNOWN_ACTION",
        )
    args = body.get("arguments") or {}
    if not isinstance(args, dict):
        raise AutonomyError("arguments must be an object.", 400, "BAD_ARGUMENTS")
    agent_id = _uuid(body.get("agent_id"))
    if body.get("agent_id") and agent_id is None:
        raise AutonomyError("agent_id is not a valid id.", 400, "BAD_AGENT")
    agent = await get_agent(db, user.tenant_id, agent_id) if agent_id else None
    if agent_id and agent is None:
        raise AutonomyError("This agent was not found.", 404, "NOT_FOUND")
    g = await pick_grant(db, user.tenant_id, at, agent_id, args)
    if g is not None and agent is None:
        agent = await get_agent(db, user.tenant_id, g.agent_id)
    prediction = body.get("prediction")
    if prediction is not None and not isinstance(prediction, dict):
        raise AutonomyError(
            "prediction must look like {metric, value, low, high}.",
            400,
            "BAD_PREDICTION",
        )
    level = None
    if g is not None:
        level = int(g.level)
        if g.state == "paused":
            level = min(level, 2)
    a = AgentAction(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=getattr(agent, "id", None),
        agent_name=getattr(agent, "name", "") or "",
        agent_config_hash=await config_hash(db, agent.id) if agent else None,
        user_id=user.id,
        action_type_id=at.id,
        grant_id=getattr(g, "id", None),
        tool_name=at.tool_name,
        level_at_time=level,
        mode="external",
        target=_s(body.get("target")),
        arguments=args,
        intent=body.get("intent"),
        prediction=prediction,
        status="recorded",
        outcome_status="none",
        created_at=_now(),
    )
    db.add(a)
    await db.flush()
    limits = None
    if at.limits_decision_key:
        facts = limit_facts(args, a.target)
        limits = await evaluate_limits(
            db, user.tenant_id, at.limits_decision_key, facts
        )
        a.limits_result = limits
    label = at.label[0].lower() + at.label[1:] if at.label else "act"
    name = getattr(agent, "name", None) or "This app"
    out: dict[str, Any] = {"action_id": str(a.id), "approval_id": None}
    if limits is not None and not limits["ok"]:
        a.status = "blocked"
        out.update(
            decision="blocked",
            message="Blocked by a hard limit: "
            + "; ".join(limits["reasons"])
            + ". An owner can review the limits on the Autonomy page.",
        )
    elif g is None:
        a.status = "approved"
        out.update(decision="run", message="Not enrolled, so it runs as before.")
    elif level == 0:
        a.status = "blocked"
        out.update(
            decision="blocked",
            message=f"{name} is not allowed to {label} (Off). An owner can change this on the Autonomy page: /autonomy/{g.id}",
        )
    elif level == 1:
        a.status = "watching"
        a.mode = "watching"
        out.update(
            decision="watching",
            message="Recorded in watching mode, not executed. A person will compare it with what they would do.",
        )
    else:
        fallback = None
        if level >= 3 and level == int(g.level):
            if not prediction:
                fallback = "No prediction was given, so it asks first"
            elif not L.band_ok(prediction, at.max_band_width):
                fallback = "The prediction band was too wide, so it asks first"
            elif limits is None and at.limits_decision_key:
                fallback = "The limits could not be checked, so it asks first"
        if level == 2 or fallback:
            if fallback:
                a.limits_result = {**(limits or {}), "fallback_reason": fallback}
            approval = await open_action_gate(
                db, user, a, at, agent, g, level, fallback
            )
            a.status = "pending"
            a.mode = "proposed"
            a.approval_id = approval.id
            out.update(
                decision="wait",
                approval_id=str(approval.id),
                message=(fallback + ". " if fallback else "")
                + "Waiting for a person to approve it in Approvals.",
            )
        else:
            a.status = "approved"
            a.mode = "auto" if level == 3 else "reported"
            out.update(
                decision="run",
                message=(
                    "Inside the limits with a confident prediction, so it runs."
                    if level == 3
                    else "It runs and the owners get a report."
                ),
            )
            if level == 4:
                await notify_owners(
                    db,
                    g,
                    agent,
                    type="action_reported",
                    title=f"{name} is about to {label}",
                    message=f"Acts and reports: {a.target or ''} {json.dumps(args, default=str)[:300]}".strip(),
                )
    a.events_sent = "proposed"
    await events.emit(
        db,
        user.tenant_id,
        "action.proposed",
        {
            "action_id": str(a.id),
            "agent_id": _s(a.agent_id),
            "action_key": at.key,
            "level": level,
            "decision": out["decision"],
            "target": a.target,
        },
    )
    await db.commit()
    if a.approval_id:
        approval = await db.get(Approval, a.approval_id)
        if approval is not None:
            await _announce_approval(db, approval, user)
    return out


async def open_action_gate(
    db: AsyncSession,
    user: Any,
    action: Any,
    at: Any,
    agent: Any,
    grant: Any,
    level: int,
    fallback: str | None,
) -> Any:
    bundle = await grant_bundle(db, grant)
    card = card_for(action, at, getattr(agent, "name", ""), bundle["stats"], level)
    card["fallback_reason"] = fallback
    card["editable_arguments"] = True
    seconds = int(
        ((at.policy or {}).get("approval_expires_s")) or DEFAULT_APPROVAL_SECONDS
    )
    label = at.label[0].lower() + at.label[1:] if at.label else "act"
    approval = Approval(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=getattr(agent, "id", None),
        title=f"{getattr(agent, 'name', 'An app')} wants to {label}"[:255],
        payload=card,
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=user.id,
        expires_at=_now() + timedelta(seconds=seconds),
        gate_kind=f"{ACTION_GATE_PREFIX}{at.key}"[:120],
    )
    db.add(approval)
    await db.flush()
    await events.emit(
        db,
        user.tenant_id,
        "approval.requested",
        {
            "approval_id": str(approval.id),
            "title": approval.title,
            "gate_kind": approval.gate_kind,
            "required_signoffs": 1,
        },
    )
    return approval


def _wait_view(a: Any, decided_by_name: str | None, approval: Any) -> dict[str, Any]:
    edited = ((approval.payload or {}).get("edited_arguments")) if approval else None
    args = (
        {**(a.arguments or {}), **edited} if isinstance(edited, dict) else a.arguments
    )
    if a.status in ("approved", "edited"):
        decision, msg = "run", (
            f"Approved by {decided_by_name}." if decided_by_name else "Approved."
        )
    elif a.status == "pending":
        decision, msg = "wait", "Still waiting for a person in Approvals."
    elif a.status == "watching":
        decision, msg = "watching", "Recorded in watching mode, not executed."
    else:
        who = decided_by_name or "nobody"
        why = f" Reason: {a.decision_note}." if a.decision_note else ""
        msg = (
            "Nobody answered in time, so it did not run."
            if a.status == "expired"
            else (
                f"Rejected by {who}.{why}"
                if a.status == "rejected"
                else f"It is {a.status}."
            )
        )
        decision = "blocked"
    return {
        "action_id": str(a.id),
        "status": a.status,
        "decision": decision,
        "arguments": args,
        "edited": isinstance(edited, dict),
        "decided_by_name": decided_by_name,
        "decision_note": a.decision_note,
        "approval_id": _s(a.approval_id),
        "message": msg,
    }


async def wait(
    db: AsyncSession, user: Any, action_id: Any, timeout_s: int
) -> dict[str, Any]:
    deadline = _now() + timedelta(seconds=max(1, min(int(timeout_s or 30), 120)))
    while True:
        a = await get_action(db, user.tenant_id, action_id)
        if a is None:
            raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
        approval = None
        if a.approval_id:
            approval = (
                await db.execute(
                    select(Approval).where(
                        Approval.id == a.approval_id,
                        Approval.tenant_id == user.tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if (
                a.status == "pending"
                and approval is not None
                and approval.status == ApprovalStatus.pending
                and approval.expires_at
                and approval.expires_at < _now()
            ):
                approval.status = ApprovalStatus.expired
                approval.decided_at = _now()
                await on_action_gate_resolved(db, approval, None)
                await db.commit()
        if a.status != "pending" or _now() >= deadline:
            names = await users_by_id(db, [a.decided_by])
            return _wait_view(a, names.get(str(a.decided_by)), approval)
        await db.commit()
        await asyncio.sleep(1.0)


async def mark_executed(
    db: AsyncSession, user: Any, action_id: Any, ok: bool, result_preview: str | None
) -> dict[str, Any]:
    a = await get_action(db, user.tenant_id, action_id)
    if a is None:
        raise AutonomyError("This action was not found.", 404, "NOT_FOUND")
    if a.status not in ("approved", "edited"):
        raise AutonomyError(
            f"This action is {a.status}, so it was not cleared to run.",
            409,
            "NOT_CLEARED",
        )
    at = await get_action_type(db, user.tenant_id, a.action_type_id)
    now = _now()
    a.status = "executed" if ok else "failed"
    a.executed_at = now
    a.result_preview = (result_preview or "")[:500] or None
    probe = (getattr(at, "outcome_probe", None) or {}) if at else {}
    if ok and probe.get("kind") and probe.get("kind") != "none":
        a.outcome_status = "pending"
        a.outcome_due_at = now + timedelta(seconds=int(probe.get("after_s") or 0))
    else:
        a.outcome_status = "none"
    a.events_sent = ",".join(x for x in ((a.events_sent or ""), "executed") if x)
    await events.emit(
        db,
        user.tenant_id,
        "action.executed",
        {
            "action_id": str(a.id),
            "agent_id": _s(a.agent_id),
            "action_key": getattr(at, "key", None),
            "ok": bool(ok),
            "mode": a.mode,
        },
    )
    await db.commit()
    return await action_detail(db, user, a.id)


# the observe_actions job


async def due_actions(db: AsyncSession, limit: int = 100) -> list[Any]:
    return list(
        (
            await db.execute(
                select(AgentAction)
                .where(
                    AgentAction.outcome_status == "pending",
                    AgentAction.outcome_due_at.isnot(None),
                    AgentAction.outcome_due_at <= _now(),
                )
                .order_by(AgentAction.outcome_due_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )


async def probe_user(db: AsyncSession, action: Any, at: Any) -> Any:
    """Whose name the probe runs under: the agent's creator, else the action type's author."""
    agent = (
        await get_agent(db, action.tenant_id, action.agent_id)
        if action.agent_id
        else None
    )
    for uid in (getattr(agent, "creator_id", None), getattr(at, "created_by", None)):
        if uid:
            u = (
                await db.execute(select(User).where(User.id == uid))
            ).scalar_one_or_none()
            if u is not None:
                return u
    return None


async def observe_one(db: AsyncSession, action: Any) -> bool:
    """Run one due probe. True when the action is settled, observed or unknown."""
    at = await get_action_type(db, action.tenant_id, action.action_type_id)
    probe = (getattr(at, "outcome_probe", None) or {}) if at else {}
    kind = probe.get("kind")
    now = _now()
    overdue = (
        action.outcome_due_at is not None
        and now - action.outcome_due_at > UNKNOWN_AFTER
    )
    if kind == "tool":
        user = await probe_user(db, action, at)
        ok, content, err = (False, None, "No user to run the probe as")
        if user is not None:
            args = render(
                probe.get("arguments") or {},
                {"args": action.arguments or {}, "target": action.target},
            )
            try:
                ok, content, err = await run_tool(db, user, probe["tool"], args)
            except Exception as e:  # noqa: BLE001
                ok, err = False, str(e)
        value = extract_path(content, probe.get("path")) if ok else None
        if value is not None:
            await apply_outcome(db, action, at, value, source="tool")
            return True
        action.outcome_attempts = int(action.outcome_attempts or 0) + 1
        if action.outcome_attempts >= MAX_PROBE_ATTEMPTS or overdue:
            action.outcome_status = "unknown"
            action.outcome = {
                "metric": probe.get("metric"),
                "value": None,
                "source": "tool",
                "observed_at": now.isoformat(),
                "by": None,
                "note": (err or f"{probe.get('path')} was not in the result")[:300],
            }
            return True
        # try again on a later tick
        action.outcome_due_at = now + timedelta(seconds=30)
        return False
    if kind in ("manual", "api"):
        if overdue:
            action.outcome_status = "unknown"
            return True
        return False
    action.outcome_status = "none"
    return True


async def notify_pending_reviews(db: AsyncSession) -> int:
    """At most hourly per grant, tell owners there are watching actions to review."""
    rows = (
        await db.execute(
            select(AgentAction.grant_id, func.count(), func.max(AgentAction.created_at))
            .where(
                AgentAction.status == "watching",
                AgentAction.reviewer_answer.is_(None),
                AgentAction.grant_id.isnot(None),
            )
            .group_by(AgentAction.grant_id)
        )
    ).all()
    sent = 0
    for gid, count, newest in rows:
        g = (
            await db.execute(select(AutonomyGrant).where(AutonomyGrant.id == gid))
        ).scalar_one_or_none()
        if g is None or g.state == "removed":
            continue
        last = g.review_notified_at
        if last is not None and (
            newest is None or newest <= last or _now() - last < timedelta(hours=1)
        ):
            continue
        agent = await get_agent(db, g.tenant_id, g.agent_id)
        for uid in await owners_of(g, agent):
            try:
                await notif.create_notification(
                    db,
                    tenant_id=g.tenant_id,
                    user_id=uid,
                    type="action_pending_review",
                    title=f"{count} watching actions by {getattr(agent, 'name', 'an agent')} to review",
                    message="Say whether you agree with what it would have done. Twenty quick reviews let it ask first instead.",
                    link="/approvals?tab=reviews",
                    metadata={"grant_id": str(g.id)},
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("review notification failed: %s", e)
        g.review_notified_at = _now()
        sent += 1
    return sent


async def emit_runtime_events(db: AsyncSession) -> int:
    """action.proposed and action.executed for rows the runtime gate wrote."""
    since = _now() - timedelta(days=1)
    rows = (
        (
            await db.execute(
                select(AgentAction)
                .where(
                    AgentAction.created_at >= since,
                    AgentAction.mode.notin_(["unmanaged", "external"]),
                    (
                        ~AgentAction.events_sent.contains("proposed")
                        | (
                            (AgentAction.status == "executed")
                            & ~AgentAction.events_sent.contains("executed")
                        )
                    ),
                )
                .order_by(AgentAction.created_at)
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    sent = 0
    for a in rows:
        at = await db.get(ActionType, a.action_type_id) if a.action_type_id else None
        done = set(filter(None, (a.events_sent or "").split(",")))
        base = {
            "action_id": str(a.id),
            "agent_id": _s(a.agent_id),
            "action_key": getattr(at, "key", None),
            "execution_id": _s(a.execution_id),
        }
        if "proposed" not in done:
            await events.emit(
                db,
                a.tenant_id,
                "action.proposed",
                {**base, "level": a.level_at_time, "mode": a.mode, "target": a.target},
            )
            done.add("proposed")
            sent += 1
        if a.status == "executed" and "executed" not in done:
            await events.emit(
                db, a.tenant_id, "action.executed", {**base, "ok": True, "mode": a.mode}
            )
            done.add("executed")
            sent += 1
        a.events_sent = ",".join(sorted(done))
    if rows:
        await db.commit()
    return sent


async def observe_tick(db: AsyncSession) -> dict[str, int]:
    touched: dict[str, Any] = {}
    settled = 0
    try:
        await emit_runtime_events(db)
    except Exception:  # noqa: BLE001
        logger.exception("autonomy event emit failed")
        await db.rollback()
    for a in await due_actions(db):
        try:
            if await observe_one(db, a):
                settled += 1
        except Exception:  # noqa: BLE001
            logger.exception("outcome probe failed for action %s", a.id)
            continue
        if a.grant_id:
            touched[str(a.grant_id)] = (a.tenant_id, a.grant_id)
    await db.commit()
    for tenant_id, gid in touched.values():
        g = await get_grant(db, tenant_id, gid)
        if g is None:
            continue
        try:
            await reevaluate(db, g)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("ladder re-evaluation failed for grant %s", gid)
            await db.rollback()
    # grants with no due probes still need demotion and recommendation checks
    since = _now() - timedelta(minutes=10)
    recent = (
        await db.execute(
            select(AgentAction.tenant_id, AgentAction.grant_id)
            .where(AgentAction.grant_id.isnot(None), AgentAction.created_at >= since)
            .distinct()
        )
    ).all()
    for tenant_id, gid in recent:
        if str(gid) in touched:
            continue
        g = await get_grant(db, tenant_id, gid)
        if g is None:
            continue
        try:
            await reevaluate(db, g)
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("ladder re-evaluation failed for grant %s", gid)
            await db.rollback()
    try:
        await notify_pending_reviews(db)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("pending review notifications failed")
        await db.rollback()
    return {"settled": settled, "grants": len(touched)}


# the sample plant


def sample_limits_document() -> dict[str, Any]:
    return {
        "kind": "rules",
        "hit_policy": "first",
        "facts": [
            {
                "path": "setpoint_bar",
                "type": "number",
                "label": "Setpoint (bar)",
                "required": True,
            }
        ],
        "outputs": [
            {"field": "ok", "label": "Inside the limits"},
            {"field": "reason", "label": "Reason"},
        ],
        "rules": [
            {
                "key": "below_minimum",
                "description": "Setpoint under 2 bar",
                "when": {"all": [{"fact": "setpoint_bar", "op": "lt", "value": 2}]},
                "then": {
                    "ok": {"value": False},
                    "reason": {"value": "The setpoint is below the 2 bar minimum"},
                },
            },
            {
                "key": "above_maximum",
                "description": "Setpoint over 6 bar",
                "when": {"all": [{"fact": "setpoint_bar", "op": "gt", "value": 6}]},
                "then": {
                    "ok": {"value": False},
                    "reason": {"value": "The setpoint is above the 6 bar maximum"},
                },
            },
            {
                "key": "inside_limits",
                "description": "Setpoint between 2 and 6 bar",
                "when": {
                    "all": [{"fact": "setpoint_bar", "op": "between", "values": [2, 6]}]
                },
                "then": {"ok": {"value": True}, "reason": {"value": ""}},
            },
        ],
    }


SAMPLE_LIMIT_TESTS = (
    # golden tests compare the whole result, reason included
    ("Inside the limits", {"setpoint_bar": 4.5}, {"ok": True, "reason": ""}),
    (
        "Below the minimum",
        {"setpoint_bar": 1.5},
        {"ok": False, "reason": "The setpoint is below the 2 bar minimum"},
    ),
    (
        "Above the maximum",
        {"setpoint_bar": 7.2},
        {"ok": False, "reason": "The setpoint is above the 6 bar maximum"},
    ),
)


def sample_action_type_spec() -> dict[str, Any]:
    return {
        "label": "Change the plant pressure setpoint",
        "description": "The sample agent changes the setpoint so pressure stays between 4 and 5 bar.",
        "match": {"param": "operation", "glob": "set_setpoint"},
        "effect": {
            "kind": "control",
            "label": "Change the plant pressure setpoint",
            "target_param": None,
            "magnitude_param": "setpoint_bar",
            "reversible": True,
        },
        "world_model": {
            "kind": "agent_stated",
            "metric": "pressure_bar",
            "timeout_s": 10,
        },
        "outcome_probe": {
            "kind": "tool",
            "after_s": 30,
            "tool": "sample_plant",
            "arguments": {"operation": "read"},
            "path": "pressure_bar",
            "metric": "pressure_bar",
        },
        "limits_decision_key": SAMPLE_LIMITS_KEY,
        "max_band_width": 0.2,
        "reversible": True,
        "policy": SAMPLE_POLICY,
    }


async def default_model(db: AsyncSession) -> str:
    """The cheapest model on a provider that is connected."""
    try:
        from app.routers.llm_models import _probe_providers

        providers = await _probe_providers(db)
    except Exception:  # noqa: BLE001
        providers = {}
    order = (
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("claude_subscription", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-4o-mini"),
        ("azure", "gpt-4o-mini"),
        ("google", "gemini-2.5-flash"),
    )
    for provider, model in order:
        if (providers.get(provider) or {}).get("configured"):
            return model
    return "claude-haiku-4-5-20251001"


async def _sample_agent(db: AsyncSession, user: Any) -> Any:
    from models.agent import AgentStatus

    found = (
        await db.execute(
            select(Agent).where(
                Agent.tenant_id == user.tenant_id,
                Agent.slug == SAMPLE_AGENT_SLUG,
                Agent.status != AgentStatus.ARCHIVED,
            )
        )
    ).scalar_one_or_none()
    if found is not None:
        await sync_sample(db, found)
        return found
    from app.routers import agents as agents_router
    from app.schemas.agents import CreateAgentRequest

    body = CreateAgentRequest(
        name=SAMPLE_AGENT_NAME,
        slug=SAMPLE_AGENT_SLUG,
        description="Keeps the sample plant's pressure between 4 and 5 bar. Installed from the Autonomy page.",
        system_prompt=SAMPLE_PROMPT,
        model_config={
            "model": await default_model(db),
            "temperature": 0.2,
            "tools": ["sample_plant"],
            "max_tokens": 1024,
            "max_iterations": 6,
        },
        category="sample",
    )
    resp = await agents_router.create_agent(body, None, user, db)
    payload = json.loads(bytes(resp.body))
    if payload.get("error"):
        raise AutonomyError(
            "The sample agent could not be created: "
            + str((payload["error"] or {}).get("message")),
            resp.status_code,
            "SAMPLE_FAILED",
        )
    return await get_agent(db, user.tenant_id, payload["data"]["id"])


async def sync_sample(db: AsyncSession, agent: Any) -> bool:
    """Bring an installed sample up to the current prompt and window. True when it changed."""
    if agent is None:
        return False
    changed = False
    if getattr(agent, "system_prompt", None) != SAMPLE_PROMPT:
        agent.system_prompt = SAMPLE_PROMPT
        changed = True
    at = await get_action_type_by_key(db, agent.tenant_id, SAMPLE_ACTION_KEY)
    if getattr(at, "is_sample", False) and "window" not in (at.policy or {}):
        # an owner's own threshold edits stay, only the missing window is added
        at.policy = {**(at.policy or {}), "window": SAMPLE_POLICY["window"]}
        changed = True
    if changed:
        await db.commit()
    return changed


async def _sample_limits(db: AsyncSession, user: Any) -> dict[str, Any]:
    """The limits decision, created, tested and published through the decisions service."""
    from app.routers import decisions as D
    from models.decision import DecisionModel, DecisionTest, DecisionVersion

    m = (
        await db.execute(
            select(DecisionModel).where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.key == SAMPLE_LIMITS_KEY,
            )
        )
    ).scalar_one_or_none()
    if m is not None and m.archived_at is not None:
        return {
            "ready": False,
            "message": f"The decision {SAMPLE_LIMITS_KEY} was archived. Restore it under Decisions.",
        }
    if m is None:
        m = DecisionModel(
            tenant_id=user.tenant_id,
            key=SAMPLE_LIMITS_KEY,
            name="Sample plant limits",
            description="Hard limits for the sample plant: the setpoint must be between 2 and 6 bar.",
            risk_tier="low",
            tags=["sample", "autonomy"],
            created_by=user.id,
        )
        db.add(m)
        await db.flush()
        await D._new_draft(
            db, user, m, sample_limits_document(), version=1, note="Sample limits"
        )
        for name, facts, expected in SAMPLE_LIMIT_TESTS:
            db.add(
                DecisionTest(
                    tenant_id=user.tenant_id,
                    model_id=m.id,
                    name=name,
                    facts=facts,
                    expected_outcome="decided",
                    expected=expected,
                    created_by=user.id,
                )
            )
        await db.commit()
    versions = list(
        (
            await db.execute(
                select(DecisionVersion).where(DecisionVersion.model_id == m.id)
            )
        )
        .scalars()
        .all()
    )
    if any(v.state == "published" and v.superseded_at is None for v in versions):
        return {"ready": True, "message": None}
    # an install made before the tests carried full results gets them repaired
    want = {name: expected for name, _, expected in SAMPLE_LIMIT_TESTS}
    for t in (
        (await db.execute(select(DecisionTest).where(DecisionTest.model_id == m.id)))
        .scalars()
        .all()
    ):
        if t.name in want and t.expected != want[t.name]:
            t.expected = want[t.name]
    await db.flush()
    v = max(versions, key=lambda x: x.version) if versions else None
    if v is None:
        return {"ready": False, "message": "The limits decision has no version."}
    if v.state == "draft":
        resp = await D.propose(
            SAMPLE_LIMITS_KEY,
            v.version,
            D.ProposeBody(note="Sample limits"),
            None,
            user,
            db,
        )
        if resp.status_code >= 400:
            return {
                "ready": False,
                "message": "The sample limits did not pass their checks: "
                + str(json.loads(bytes(resp.body)).get("error", {}).get("message")),
            }
        await db.refresh(v)
    if v.state == "approved":
        resp = await D.publish(
            SAMPLE_LIMITS_KEY, v.version, D.PublishBody(), None, user, db
        )
        if resp.status_code >= 400:
            return {
                "ready": False,
                "message": str(
                    json.loads(bytes(resp.body)).get("error", {}).get("message")
                ),
            }
        return {"ready": True, "message": None}
    return {
        "ready": False,
        "message": "The sample limits are waiting for sign-off in Approvals before they apply.",
    }


async def install_sample(db: AsyncSession, user: Any) -> dict[str, Any]:
    agent = await _sample_agent(db, user)
    if agent is None:
        raise AutonomyError(
            "The sample agent could not be found after creating it.",
            500,
            "SAMPLE_FAILED",
        )
    limits = await _sample_limits(db, user)
    spec = sample_action_type_spec()
    if not limits["ready"]:
        # the action type still works, without limits until they are published
        logger.info("sample limits not published: %s", limits["message"])
    row = await enrol(
        db,
        user,
        agent.id,
        "sample_plant",
        spec,
        None,
        key=SAMPLE_ACTION_KEY,
        is_sample=True,
    )
    return {
        "grant": row,
        "agent_id": str(agent.id),
        "limits_ready": bool(limits["ready"]),
        "limits_message": limits["message"],
    }


def _request_for(agent_id: Any, body: dict[str, Any]) -> Any:
    from starlette.requests import Request

    raw = json.dumps(body).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    path = f"/api/agents/{agent_id}/execute"
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 0),
        "server": ("autonomy", 0),
        "state": {
            "run_origin": {"kind": "autonomy_sample", "name": "Earned autonomy sample"}
        },
    }
    return Request(scope, receive)


async def run_sample(db: AsyncSession, user: Any, count: int) -> dict[str, Any]:
    from models.agent import AgentStatus

    agent = (
        await db.execute(
            select(Agent).where(
                Agent.tenant_id == user.tenant_id,
                Agent.slug == SAMPLE_AGENT_SLUG,
                Agent.status != AgentStatus.ARCHIVED,
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise AutonomyError(
            "The sample is not installed. Choose Try it with the sample plant first.",
            404,
            "SAMPLE_MISSING",
        )
    await sync_sample(db, agent)
    from app.routers import agents as agents_router
    from app.schemas.agents import ExecuteRequest

    ids: list[str] = []
    errors: list[str] = []
    for _ in range(max(1, min(int(count or 1), 5))):
        body = {
            "message": SAMPLE_RUN_MESSAGE,
            "stream": False,
            "wait": False,
            "wait_mode": "submitted",
        }
        resp = await agents_router.execute_agent(
            str(agent.id),
            ExecuteRequest(**body),
            _request_for(agent.id, body),
            user,
            db,
        )
        try:
            payload = json.loads(bytes(resp.body))
        except Exception:  # noqa: BLE001
            errors.append(f"The run answered {getattr(resp, 'status_code', '?')}")
            continue
        data = payload.get("data") or {}
        if isinstance(data, dict) and data.get("execution_id"):
            ids.append(str(data["execution_id"]))
        else:
            err = payload.get("error") or {}
            errors.append(str(err.get("message") if isinstance(err, dict) else err))
    if not ids and errors:
        raise AutonomyError(
            "The sample agent did not start: " + errors[0], 409, "SAMPLE_RUN_FAILED"
        )
    return {"execution_ids": ids, "agent_id": str(agent.id), "errors": errors}
