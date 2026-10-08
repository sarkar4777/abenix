"""The "Start here" journey on the dashboard, one checklist per role."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from models.agent import Agent, AgentStatus, AgentType
from models.autonomy import AutonomyGrant
from models.collection_grant import AgentCollectionGrant
from models.conversation import Conversation, Message
from models.evals import EvalCase, EvalSuite
from models.execution import Execution
from models.governance import RiskPolicy
from models.knowledge_base import KnowledgeBase
from models.moderation_policy import ModerationPolicy
from models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/me/journey", tags=["journey"])

PREFS_KEY = "journey"
SEEN_STEPS = {"risk"}


def role_of(user: User) -> str:
    role = getattr(user, "role", None)
    r = (role.value if hasattr(role, "value") else str(role or "")).lower()
    if r == "admin":
        return "admin"
    if r == "creator":
        return "builder"
    return "member"


def _prefs(user: User) -> dict[str, Any]:
    raw = getattr(user, "notification_settings", None) or {}
    j = raw.get(PREFS_KEY) if isinstance(raw, dict) else None
    return dict(j) if isinstance(j, dict) else {}


def _save_prefs(user: User, journey: dict[str, Any]) -> None:
    # reassign the whole dict so the JSONB change is picked up
    prefs = dict(getattr(user, "notification_settings", None) or {})
    prefs[PREFS_KEY] = journey
    user.notification_settings = prefs


async def _exists(db: AsyncSession, stmt) -> bool:
    return (await db.execute(stmt.limit(1))).scalar() is not None


async def _model_connected(db: AsyncSession) -> bool:
    from app.routers.llm_models import _probe_providers

    try:
        providers = await _probe_providers(db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("journey provider probe failed: %s", exc)
        return False
    return any(bool((p or {}).get("configured")) for p in providers.values())


async def admin_facts(db: AsyncSession, user: User) -> dict[str, bool]:
    t = user.tenant_id
    users = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.tenant_id == t, User.is_active.is_(True))
        )
    ).scalar() or 0
    risk_changed = await _exists(
        db,
        select(RiskPolicy.id).where(
            RiskPolicy.tenant_id == t, RiskPolicy.updated_by.is_not(None)
        ),
    )
    moderation_on = await _exists(
        db,
        select(ModerationPolicy.id).where(
            ModerationPolicy.tenant_id == t, ModerationPolicy.is_active.is_(True)
        ),
    )
    return {
        "connect_model": await _model_connected(db),
        "invite_team": int(users) > 1,
        "review_risk": risk_changed or "risk" in (_prefs(user).get("seen") or []),
        "moderation": moderation_on,
    }


async def builder_facts(db: AsyncSession, user: User) -> dict[str, Any]:
    from app.core.platform_features import marketplace_enabled

    t = user.tenant_id
    rows = (
        await db.execute(
            select(Agent.id, Agent.is_published, Agent.status)
            .where(
                Agent.tenant_id == t,
                Agent.creator_id == user.id,
                Agent.agent_type != AgentType.OOB,
                Agent.status != AgentStatus.ARCHIVED,
            )
            .order_by(Agent.created_at.desc())
            .limit(500)
        )
    ).all()
    ids = [r[0] for r in rows]
    facts: dict[str, Any] = {
        "first_agent_id": str(ids[0]) if ids else None,
        "marketplace": await marketplace_enabled(db),
        "build_agent": bool(ids),
        "run_agent": False,
        "add_knowledge": False,
        "add_tests": False,
        "enrol_autonomy": False,
        "list_marketplace": any(
            bool(r[1]) or r[2] == AgentStatus.PENDING_REVIEW for r in rows
        ),
    }
    if not ids:
        return facts
    facts["run_agent"] = await _exists(
        db,
        select(Execution.id).where(
            Execution.tenant_id == t, Execution.agent_id.in_(ids)
        ),
    )
    granted = select(AgentCollectionGrant.collection_id).where(
        AgentCollectionGrant.agent_id.in_(ids)
    )
    facts["add_knowledge"] = await _exists(
        db,
        select(KnowledgeBase.id).where(
            KnowledgeBase.tenant_id == t,
            or_(KnowledgeBase.agent_id.in_(ids), KnowledgeBase.id.in_(granted)),
        ),
    )
    facts["add_tests"] = await _exists(
        db,
        select(EvalCase.id)
        .join(EvalSuite, EvalSuite.id == EvalCase.suite_id)
        .where(
            EvalSuite.tenant_id == t,
            EvalCase.tenant_id == t,
            EvalSuite.agent_id.in_(ids),
        ),
    )
    facts["enrol_autonomy"] = await _exists(
        db,
        select(AutonomyGrant.id).where(
            AutonomyGrant.tenant_id == t, AutonomyGrant.agent_id.in_(ids)
        ),
    )
    return facts


async def member_facts(db: AsyncSession, user: User) -> dict[str, bool]:
    t = user.tenant_id
    chatted = await _exists(
        db,
        select(Conversation.id).where(
            Conversation.tenant_id == t, Conversation.user_id == user.id
        ),
    ) or await _exists(
        db,
        select(Execution.id).where(
            Execution.tenant_id == t, Execution.user_id == user.id
        ),
    )
    # a follow-up in the same thread shows the agent remembers the conversation
    followed_up = await _exists(
        db,
        select(Message.conversation_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.tenant_id == t,
            Conversation.user_id == user.id,
            Message.role == "user",
        )
        .group_by(Message.conversation_id)
        .having(func.count() >= 2),
    )
    return {"try_chat": chatted, "follow_up": followed_up}


def _step(
    sid: str, title: str, why: str, href: str, cta: str, done: bool
) -> dict[str, Any]:
    return {
        "id": sid,
        "title": title,
        "why": why,
        "href": href,
        "cta": cta,
        "done": bool(done),
    }


def build_steps(role: str, f: dict[str, Any]) -> list[dict[str, Any]]:
    if role == "admin":
        return [
            _step(
                "connect_model",
                "Connect an AI model",
                "Agents cannot answer anything until a model key or subscription is set up.",
                "/admin/tool-config",
                "Add a model key",
                f["connect_model"],
            ),
            _step(
                "invite_team",
                "Invite your team",
                "Agents pay off when the people who rely on them can sign in too.",
                "/settings/team",
                "Invite people",
                f["invite_team"],
            ),
            _step(
                "review_risk",
                "Review risk policies",
                "Decide which actions need a person to approve them before they run.",
                "/admin/risk",
                "Open risk policies",
                f["review_risk"],
            ),
            _step(
                "moderation",
                "Turn on moderation",
                "Screen what goes into and comes out of your agents for harmful content.",
                "/moderation",
                "Open moderation",
                f["moderation"],
            ),
        ]
    if role == "builder":
        agent = f.get("first_agent_id")
        steps = [
            _step(
                "build_agent",
                "Build your first agent",
                "An agent is a model with instructions and tools that does one job well.",
                "/builder",
                "Open the builder",
                f["build_agent"],
            ),
            _step(
                "run_agent",
                "Run it",
                "A first run shows whether the agent does what you meant.",
                f"/agents/{agent}/chat" if agent else "/agents",
                "Try it in chat",
                f["run_agent"],
            ),
            _step(
                "add_knowledge",
                "Give it knowledge",
                "Agents answer better when they can cite your own documents.",
                "/knowledge",
                "Add a knowledge base",
                f["add_knowledge"],
            ),
            _step(
                "add_tests",
                "Add tests",
                "Saved test cases warn you when a change makes the agent worse.",
                "/evals",
                "Add a test suite",
                f["add_tests"],
            ),
            _step(
                "enrol_autonomy",
                "Enrol an action in Autonomy",
                "The agent earns the right to act on its own, one kind of action at a time.",
                "/autonomy",
                "Enrol an action",
                f["enrol_autonomy"],
            ),
        ]
        if f.get("marketplace"):
            steps.append(
                _step(
                    "list_marketplace",
                    "List it in the marketplace",
                    "Other teams can find and use what you built.",
                    f"/agents/{agent}/info" if agent else "/agents",
                    "Open your agent",
                    f["list_marketplace"],
                )
            )
        return steps
    return [
        _step(
            "try_chat",
            "Try an agent in chat",
            "Ask an agent a real question and see how it answers.",
            "/chat",
            "Open chat",
            f["try_chat"],
        ),
        _step(
            "follow_up",
            "Ask a follow-up in the same chat",
            "The agent remembers the conversation, so you can build on its last answer.",
            "/chat",
            "Continue a chat",
            f["follow_up"],
        ),
    ]


async def journey_view(db: AsyncSession, user: User) -> dict[str, Any]:
    role = role_of(user)
    if role == "admin":
        facts: dict[str, Any] = await admin_facts(db, user)
    elif role == "builder":
        facts = await builder_facts(db, user)
    else:
        facts = await member_facts(db, user)
    steps = build_steps(role, facts)
    done = sum(1 for s in steps if s["done"])
    return {
        "role": role,
        "steps": steps,
        "done": done,
        "total": len(steps),
        "complete": done == len(steps),
        "dismissed": bool(_prefs(user).get("dismissed")),
    }


@router.get("")
async def get_journey(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return success(await journey_view(db, user))


@router.put("")
async def set_journey(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    dismissed = body.get("dismissed")
    if not isinstance(dismissed, bool):
        return error("Send dismissed as true or false.", 400)
    journey = _prefs(user)
    journey["dismissed"] = dismissed
    _save_prefs(user, journey)
    await db.commit()
    return success(await journey_view(db, user))


@router.post("/seen")
async def mark_seen(
    body: dict = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    step = str(body.get("step") or "")
    if step not in SEEN_STEPS:
        return error("Unknown step.", 400)
    journey = _prefs(user)
    seen = list(journey.get("seen") or [])
    if step not in seen:
        seen.append(step)
        journey["seen"] = seen
        _save_prefs(user, journey)
        await db.commit()
    return success({"step": step, "seen": True})
