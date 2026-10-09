"""Governed self-improvement: propose a fix, prove it offline, approve, release as a revision, watch, roll back."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import BigInteger, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import notifications as notif
from app.services import events
from app.services import improvement_rules as R
from models.agent import Agent
from models.approval import Approval, ApprovalStatus
from models.user import User

logger = logging.getLogger("abenix.improvements")

GATE = "improvement.release"
PROPOSE_LOCK_KEY = 0x494D5050  # "IMPP"
WATCH_LOCK_KEY = 0x494D5057  # "IMPW"
SAMPLE_SLUG = "sample-temperature-helper"
SAMPLE_NAME = "Temperature helper (sample)"
CLAIM_MINUTES = 20
RUN_TIMEOUT = int(os.environ.get("IMPROVEMENTS_RUN_TIMEOUT_SECONDS", "180"))
MAX_CASES = 200
MAX_TARGET_LESSONS = 20
CACHE_TTL = 7 * 24 * 3600
_slots = asyncio.Semaphore(
    max(1, int(os.environ.get("IMPROVEMENTS_PROOF_CONCURRENCY", "2")))
)
_tasks: set[asyncio.Task] = set()
_memo: dict[str, dict[str, Any]] = {}

SAMPLE_SELF_APPROVAL = (
    "This is the sample, so you can approve it yourself. "
    "In real use someone else approves fixes."
)
SOLO_SELF_APPROVAL = (
    "You are the only person in this workspace who can approve fixes, "
    "so you can approve it yourself. It is recorded as self-approved."
)
AUTHOR_REFUSED = (
    "You built this agent, so someone else has to approve this fix. "
    "Invite a teammate under Settings, Team, and give them Approve improvements."
)
KILL_SWITCH_TEXT = (
    "Agent improvements are stopped by a kill switch. "
    "An admin can resume them under Admin, Risk and Controls."
)


class ImprovementError(Exception):
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


def _name(u: Any) -> str:
    return (getattr(u, "full_name", None) or getattr(u, "email", None) or "").strip()


def _session():
    from app.core.deps import async_session

    return async_session()


# models, S1's migration owns the tables

_MODULES = (
    "models.improvements",
    "models.improvement",
    "models.lessons",
    "models.lesson",
    "models.feedback",
    "models.self_improvement",
)


def model(table: str) -> Any:
    from models.base import Base

    for m in Base.registry.mappers:
        if getattr(m.local_table, "name", None) == table:
            return m.class_
    for name in _MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            continue
    for m in Base.registry.mappers:
        if getattr(m.local_table, "name", None) == table:
            return m.class_
    raise ImprovementError(
        "Agent improvements are not set up yet. Run the database migration.",
        503,
        "NOT_INSTALLED",
    )


def Proposal() -> Any:  # noqa: N802
    return model("improvement_proposals")


def Cluster() -> Any:  # noqa: N802
    return model("lesson_clusters")


def Lesson() -> Any:  # noqa: N802
    return model("lessons")


def Feedback() -> Any:  # noqa: N802
    return model("feedback")


# queries, kept small so tests can swap them


async def get_proposal(db: AsyncSession, tenant_id: Any, pid: Any) -> Any:
    P = Proposal()
    i = _uuid(pid)
    if i is None:
        return None
    return (
        await db.execute(select(P).where(P.id == i, P.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def get_cluster(db: AsyncSession, tenant_id: Any, cid: Any) -> Any:
    C = Cluster()
    i = _uuid(cid)
    if i is None:
        return None
    return (
        await db.execute(select(C).where(C.id == i, C.tenant_id == tenant_id))
    ).scalar_one_or_none()


async def get_agent(db: AsyncSession, tenant_id: Any, agent_id: Any) -> Any:
    i = _uuid(agent_id)
    if i is None:
        return None
    return (
        await db.execute(
            select(Agent).where(Agent.id == i, Agent.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()


async def cluster_lessons(db: AsyncSession, cluster_id: Any, limit: int = 50) -> list:
    L = Lesson()
    return list(
        (
            await db.execute(
                select(L)
                .where(L.cluster_id == cluster_id)
                .order_by(L.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def active_proposal(db: AsyncSession, cluster_id: Any) -> Any:
    P = Proposal()
    return (
        await db.execute(
            select(P)
            .where(P.cluster_id == cluster_id, P.state.in_(R.ACTIVE_STATES))
            .order_by(P.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def tenant_settings(db: AsyncSession, tenant_id: Any) -> dict[str, Any]:
    from models.tenant import Tenant

    t = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    return dict(getattr(t, "settings", None) or {}) if t else {}


async def settings_for(
    db: AsyncSession, tenant_id: Any, agent_id: Any
) -> dict[str, Any]:
    return R.settings_for(await tenant_settings(db, tenant_id), agent_id)


async def current_hash(db: AsyncSession, agent_id: Any) -> str | None:
    from app.services.eval_runner import current_config_hash

    return await current_config_hash(db, agent_id)


async def stopped(tenant_id: Any) -> str | None:
    """The kill switch reason when improvements are stopped for this tenant."""
    from engine import governance

    await governance.ensure_fresh()
    hit = governance.stopped(tenant_id, "improvements")
    if hit is None:
        return None
    return KILL_SWITCH_TEXT + (
        f" Reason given: {hit[2].rstrip('. ')}." if hit[2] else ""
    )


def is_sample(agent: Any) -> bool:
    return str(getattr(agent, "slug", "") or "") == SAMPLE_SLUG


# rows


def proposal_row(p: Any, agent: Any = None, cluster: Any = None) -> dict[str, Any]:
    """ProposalRow from the contract. S1's agent view uses this too."""
    state = str(p.state or "")
    return {
        "id": str(p.id),
        "agent": {
            "id": _s(p.agent_id),
            "name": getattr(agent, "name", None) or "",
        },
        "cluster": {
            "id": _s(p.cluster_id),
            "title": getattr(cluster, "title", None) or "",
        },
        "change_kind": p.change_kind,
        "change_label": R.CHANGE_LABELS.get(p.change_kind or "", "Not drafted yet"),
        "diff": p.diff or {},
        "rationale": p.rationale or "",
        "risk": p.risk or "low",
        "state": state,
        "state_label": R.STATE_LABELS.get(state, state),
        "progress": p.progress or {},
        "proof": p.proof or {},
        "approval_id": _s(p.approval_id),
        "released_revision_id": _s(p.released_revision_id),
        "watch_until": _iso(p.watch_until),
        "watch_runs_target": getattr(p, "watch_runs_target", None),
        "watch_result": p.watch_result,
        "error": getattr(p, "error", None),
        "created_at": _iso(p.created_at),
        "updated_at": _iso(getattr(p, "updated_at", None)),
    }


async def row_for(db: AsyncSession, p: Any) -> dict[str, Any]:
    agent = await get_agent(db, p.tenant_id, p.agent_id)
    cluster = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    return proposal_row(p, agent, cluster)


# who may do what


async def _has(db: AsyncSession, user: Any, cap: str) -> bool:
    from app.core import capabilities as caps

    return await caps.has_capability(db, user, cap)


async def check_view(db: AsyncSession, user: Any, agent: Any) -> None:
    if agent is None:
        raise ImprovementError("This agent was not found.", 404, "NOT_FOUND")
    if str(getattr(agent, "creator_id", "")) == str(user.id):
        return
    visible = await _visible(db, user)
    if visible is None or agent.id in visible:
        return
    raise ImprovementError(
        "You need the View improvements permission to see this. An admin can grant it under Admin, Permissions.",
        403,
        "FORBIDDEN",
    )


async def check_propose(db: AsyncSession, user: Any, agent: Any) -> None:
    if agent is None:
        raise ImprovementError("This agent was not found.", 404, "NOT_FOUND")
    if await _has(db, user, "improvements.propose"):
        return
    raise ImprovementError(
        "You need the Propose improvements permission for this. An admin can grant it under Admin, Permissions.",
        403,
        "FORBIDDEN",
    )


async def _visible(db: AsyncSession, user: Any) -> set[uuid.UUID] | None:
    """Same sharing rule as the lessons views: None means every agent in the tenant."""
    from app.services.lessons import visible_agents

    return await visible_agents(db, user)


async def someone_else_can_approve(db: AsyncSession, user: Any) -> bool:
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
        if await caps.has_capability(db, other, "improvements.approve"):
            return True
    return False


async def self_approval_reason(db: AsyncSession, user: Any, agent: Any) -> str | None:
    """Why the author may approve a fix to their own agent, None when someone else must."""
    if is_sample(agent):
        return SAMPLE_SELF_APPROVAL
    if await someone_else_can_approve(db, user):
        return None
    return SOLO_SELF_APPROVAL


async def release_denial(db: AsyncSession, user: Any, approval: Any) -> str | None:
    """Separation of duties for releases: never the agent's author, rechecked at sign time."""
    payload = approval.payload or {}
    agent = await get_agent(
        db, approval.tenant_id, (payload.get("agent") or {}).get("id")
    )
    creator = payload.get("agent_creator_id") or _s(getattr(agent, "creator_id", None))
    if creator and str(creator) == str(user.id):
        if await self_approval_reason(db, user, agent) is None:
            return AUTHOR_REFUSED
    return None


# budget


async def usage_today(db: AsyncSession, tenant_id: Any) -> dict[str, int]:
    P = Proposal()
    day = _now().date().isoformat()
    tok = func.coalesce(P.progress["tokens"].astext.cast(BigInteger), 0)
    auto = P.created_by.is_(None)
    row = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(tok), 0),
                func.count().filter(auto),
                func.coalesce(func.sum(tok).filter(auto), 0),
            ).where(
                P.tenant_id == tenant_id,
                P.progress["started_on"].astext == day,
            )
        )
    ).first()
    if not row:
        return {"proofs": 0, "tokens": 0, "auto_proofs": 0, "auto_tokens": 0}
    return {
        "proofs": int(row[0] or 0),
        "tokens": int(row[1] or 0),
        "auto_proofs": int(row[2] or 0),
        "auto_tokens": int(row[3] or 0),
    }


async def queue_depth(db: AsyncSession, tenant_id: Any = None) -> int:
    P = Proposal()
    q = select(func.count()).select_from(P).where(P.state.in_(R.WORK_STATES))
    if tenant_id is not None:
        q = q.where(P.tenant_id == tenant_id)
    return int((await db.execute(q)).scalar() or 0)


async def budget(db: AsyncSession, user: Any) -> dict[str, Any]:
    s = await settings_for(db, user.tenant_id, None)
    used = await usage_today(db, user.tenant_id)
    left = room(used, s)
    return {
        "tokens_today": used["tokens"],
        "tokens_limit": int(s["tokens_per_day"]),
        "proofs_today": used["proofs"],
        "proofs_limit": int(s["proofs_per_day"]),
        "auto_tokens_today": used.get("auto_tokens", 0),
        "auto_proofs_today": used.get("auto_proofs", 0),
        "tokens_left": left["tokens"],
        "proofs_left": left["proofs"],
        "queue_depth": await queue_depth(db, user.tenant_id),
        "stopped": await stopped(user.tenant_id),
    }


def room(
    used: dict[str, int], s: dict[str, Any], automatic: bool = False
) -> dict[str, int]:
    """What is left today. Automatic proposals get half, so a fix a person asks for can still run."""
    lim_p, lim_t = int(s["proofs_per_day"]), int(s["tokens_per_day"])
    half_p, half_t = lim_p // 2, lim_t // 2
    auto_p = int(used.get("auto_proofs") or 0)
    auto_t = int(used.get("auto_tokens") or 0)
    if automatic:
        return {"proofs": max(0, half_p - auto_p), "tokens": max(0, half_t - auto_t)}
    people_p = int(used.get("proofs") or 0) - auto_p
    people_t = int(used.get("tokens") or 0) - auto_t
    return {
        "proofs": max(0, lim_p - people_p - min(auto_p, half_p)),
        "tokens": max(0, lim_t - people_t - min(auto_t, half_t)),
    }


def budget_reason(
    used: dict[str, int], s: dict[str, Any], automatic: bool = False
) -> str | None:
    left = room(used, s, automatic)
    if automatic and (left["proofs"] <= 0 or left["tokens"] <= 0):
        return (
            "Automatic proposals have used their half of today's improvement budget. "
            "This one waits in line and starts tomorrow. Fixes a person asks for still run."
        )
    if left["proofs"] <= 0:
        return (
            f"Today's improvement budget is used up ({int(s['proofs_per_day'])} proofs a day). "
            "This one waits in line and starts tomorrow, or an admin can raise the budget."
        )
    if left["tokens"] <= 0:
        return (
            f"Today's improvement budget is used up ({int(s['tokens_per_day']):,} tokens a day). "
            "This one waits in line and starts tomorrow, or an admin can raise the budget."
        )
    return None


# propose


async def propose(
    db: AsyncSession, user: Any, cluster_id: Any, *, automatic: bool = False
) -> dict[str, Any]:
    tenant = user.tenant_id
    cluster = await get_cluster(db, tenant, cluster_id)
    if cluster is None:
        raise ImprovementError("This group of lessons was not found.", 404, "NOT_FOUND")
    agent = await get_agent(db, tenant, cluster.agent_id)
    if not automatic:
        await check_propose(db, user, agent)
    if agent is None:
        raise ImprovementError(
            "The agent for these lessons was deleted.", 404, "NOT_FOUND"
        )
    if str(cluster.state or "") in ("dismissed", "fixed"):
        raise ImprovementError(
            "This group is closed. Reopen it, or wait for new lessons, to propose a fix.",
            409,
            "CLUSTER_CLOSED",
        )
    why = await stopped(tenant)
    if why:
        raise ImprovementError(why, 409, "KILL_SWITCH")
    existing = await active_proposal(db, cluster.id)
    if existing is not None:
        return proposal_row(existing, agent, cluster)
    P = Proposal()
    p = P(
        id=uuid.uuid4(),
        tenant_id=tenant,
        agent_id=agent.id,
        cluster_id=cluster.id,
        base_config_hash=await current_hash(db, agent.id),
        # empty until the improver drafts it
        change_kind="",
        diff={},
        rationale="",
        risk="low",
        state="drafting",
        progress=R.new_progress(),
        proof={},
        watch_runs_target=0,
        approval_id=None,
        released_revision_id=None,
        watch_until=None,
        watch_result=None,
        error=None,
        created_by=None if automatic else user.id,
        created_at=_now(),
    )
    db.add(p)
    cluster.state = "proposing"
    await db.commit()
    kick()
    return proposal_row(p, agent, cluster)


async def rerun(
    db: AsyncSession, user: Any, proposal_id: Any, diff: dict[str, Any] | None
) -> dict[str, Any]:
    """Edit and re-prove. A pending approval is withdrawn, the new proof asks again."""
    p = await get_proposal(db, user.tenant_id, proposal_id)
    if p is None:
        raise ImprovementError("This proposal was not found.", 404, "NOT_FOUND")
    agent = await get_agent(db, p.tenant_id, p.agent_id)
    await check_propose(db, user, agent)
    if p.state not in ("failed_proof", "awaiting_approval", "rejected"):
        raise ImprovementError(
            f"A proof can only run again before release. This one is {R.STATE_LABELS.get(p.state, p.state).lower()}.",
            409,
            "WRONG_STATE",
        )
    why = await stopped(p.tenant_id)
    if why:
        raise ImprovementError(why, 409, "KILL_SWITCH")
    if diff is not None:
        if not p.change_kind:
            raise ImprovementError(
                "There is no drafted change to edit yet.", 409, "NO_DRAFT"
            )
        base = R.state_of(agent)
        try:
            new = R.apply_change(
                base, p.change_kind, R.clean_diff(diff), **await _change_ctx(agent)
            )
        except R.ChangeRejected as e:
            raise ImprovementError(str(e), 400, "CHANGE_NOT_ALLOWED") from e
        p.diff = {**R.clean_diff(diff), "preview": R.preview(base, new)}
        p.base_config_hash = await current_hash(db, agent.id)
    await _withdraw_approval(db, p, "The fix was edited, so it is being proved again.")
    p.state = "proving"
    p.proof = {}
    p.error = None
    p.progress = R.new_progress(skip_draft=True)
    await db.commit()
    kick()
    return await row_for(db, p)


async def _withdraw_approval(db: AsyncSession, p: Any, note: str) -> None:
    if p.approval_id is None:
        return
    a = await db.get(Approval, p.approval_id)
    if a is not None and a.status == ApprovalStatus.pending:
        a.status = ApprovalStatus.expired
        a.decided_at = _now()
        a.payload = {**(a.payload or {}), "withdrawn": note}
    p.approval_id = None


# the queue: proposals in drafting or proving are the work, claimed with SKIP LOCKED


def kick() -> None:
    """Start draining on this replica when it is a proof worker, the scheduler covers the rest."""
    if not drains_here():
        return
    try:
        t = asyncio.get_running_loop().create_task(drain_once())
    except RuntimeError:
        return
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def drains_here() -> bool:
    role = os.environ.get("IMPROVEMENTS_PROOF_DRAIN", "api").lower()
    worker = os.environ.get("IMPROVEMENTS_PROOF_WORKER", "").lower() in ("1", "true")
    return worker or role != "pool"


async def claim(limit: int) -> list[uuid.UUID]:
    """Take up to limit queued proposals no other worker holds."""
    if limit <= 0:
        return []
    P = Proposal()
    now = _now()
    runner = os.environ.get("HOSTNAME", "") or str(os.getpid())
    async with _session() as db:
        rows = (
            (
                await db.execute(
                    select(P)
                    .where(
                        P.state.in_(R.WORK_STATES),
                        or_(
                            P.progress["claimed_until"].astext.is_(None),
                            P.progress["claimed_until"].astext < now.isoformat(),
                        ),
                    )
                    # a fix a person asked for goes ahead of automatic ones
                    .order_by(P.created_by.is_not(None).desc(), P.created_at)
                    .limit(limit * 4)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        out: list[uuid.UUID] = []
        stopped_tenants: dict[str, str | None] = {}
        used: dict[str, dict[str, int]] = {}
        for p in rows:
            if len(out) >= limit:
                break
            t = str(p.tenant_id)
            if t not in stopped_tenants:
                stopped_tenants[t] = await stopped(p.tenant_id)
            prog = dict(p.progress or {})
            if stopped_tenants[t]:
                if prog.get("waiting") != stopped_tenants[t]:
                    p.progress = {
                        **prog,
                        "waiting": stopped_tenants[t],
                        "message": stopped_tenants[t],
                    }
                continue
            if not prog.get("started_on"):
                if t not in used:
                    used[t] = await usage_today(db, p.tenant_id)
                s = await settings_for(db, p.tenant_id, p.agent_id)
                automatic = p.created_by is None
                why = budget_reason(used[t], s, automatic)
                if why:
                    if prog.get("waiting") != why:
                        p.progress = {**prog, "waiting": why, "message": why}
                    continue
                used[t]["proofs"] += 1
                if automatic:
                    used[t]["auto_proofs"] = used[t].get("auto_proofs", 0) + 1
                prog["started_on"] = now.date().isoformat()
                prog["started_at"] = now.isoformat()
            prog.pop("waiting", None)
            prog["claimed_until"] = (now + timedelta(minutes=CLAIM_MINUTES)).isoformat()
            prog["runner"] = runner
            p.progress = prog
            out.append(p.id)
        await db.commit()
    return out


async def drain_once() -> int:
    """Claim what this replica has room for and work on it in the background."""
    free = _slots._value  # noqa: SLF001
    try:
        ids = await claim(free)
    except ImprovementError:
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("improvement claim failed")
        return 0
    for pid in ids:
        t = asyncio.get_running_loop().create_task(_work(pid))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return len(ids)


async def _work(pid: uuid.UUID) -> None:
    async with _slots:
        try:
            await work_on(pid)
        except Exception as e:  # noqa: BLE001
            logger.exception("improvement %s failed", pid)
            await _fail(pid, f"The proof stopped with an error: {str(e)[:400]}")


async def _save(pid: Any, **fields: Any) -> None:
    P = Proposal()
    async with _session() as db:
        p = await db.get(P, pid)
        if p is None:
            return
        for k, v in fields.items():
            setattr(p, k, v)
        await db.commit()


async def _fail(pid: Any, message: str) -> None:
    P = Proposal()
    async with _session() as db:
        p = await db.get(P, pid)
        if p is None:
            return
        prog = dict(p.progress or {})
        for s in prog.get("steps") or []:
            if s.get("state") == "running":
                s["state"] = "failed"
        prog.update({"phase": "failed", "message": message, "claimed_until": None})
        p.progress = prog
        p.state = "failed_proof"
        p.error = message
        c = await db.get(Cluster(), p.cluster_id) if p.cluster_id else None
        if c is not None and c.state == "proposing":
            c.state = "open"
        await db.commit()


async def work_on(pid: Any) -> None:
    """Draft when needed, then prove, then ask for approval when the proof passes."""
    P = Proposal()
    async with _session() as db:
        p = await db.get(P, pid)
        if p is None or p.state not in R.WORK_STATES:
            return
        agent = await get_agent(db, p.tenant_id, p.agent_id)
        if agent is None:
            await _fail(pid, "The agent was deleted.")
            return
        if p.state == "drafting":
            await draft(db, p, agent)
            if p.state != "proving":
                return
    await prove(pid)


# the improver


IMPROVER_SYSTEM = """You improve one AI agent from lessons people and runs taught it.

You get one group of similar lessons, the test cases written from them, the agent's
current instructions, tools, tool settings and model, and some recent results.
Propose ONE small change that should fix the lessons without breaking anything else.

Change kinds, prefer the smallest that works:
1. examples: {"examples": [{"input": "...", "output": "..."}]}  1 to 5 good examples, taken from corrections
2. prompt_edit: {"edits": [{"find": "exact text in the instructions", "replace": "new text"}]} or {"append": "text"}
   find must match the instructions exactly once. Edit, never rewrite.
3. tool_config: {"tool": "name", "set": {"parameter_defaults": {...}, "max_calls": n, "require_approval": true, "locked_defaults": true}}
4. tool_set: {"add": ["read_only_tool"]} or {"remove": ["tool"]}, one tool only
5. model: {"model": "model id"} only from the allowed models

Never touch limits, risk tier, autonomy, credentials or sharing.

Reply with JSON only:
{"change_kind": "...", "diff": {...}, "rationale": "two or three plain sentences a non-engineer understands",
 "risk": "low|medium|high", "fixes": ["lesson ids this should fix"]}"""


async def _change_ctx(agent: Any) -> dict[str, Any]:
    from engine import governance, risk

    tier = risk.normalize((agent.model_config_ or {}).get("risk_tier"))
    await governance.ensure_fresh()
    pol = governance.policy(str(agent.tenant_id), tier)
    return {
        "model_ok": lambda m: risk.model_allowed(pol, m),
        "read_only_tools": read_only_tools(),
        "registry": [{"name": n} for n in all_tools()],
    }


def all_tools() -> list[str]:
    try:
        from engine import agent_executor as AE

        AE._ensure_tool_classes()  # noqa: SLF001
        return sorted(AE._TOOL_CLASSES)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        return []


def read_only_tools() -> set[str]:
    try:
        from engine import agent_executor as AE
        from engine.autonomy import REPLAY_HOLD
        from engine.tools.base import BaseTool

        AE._ensure_tool_classes()  # noqa: SLF001
        base_fn = getattr(BaseTool.effect_for, "__func__", None)
        out = set()
        for name, cls in AE._TOOL_CLASSES.items():  # noqa: SLF001
            if getattr(cls, "effect", None) is not None or name in REPLAY_HOLD:
                continue
            if getattr(cls.effect_for, "__func__", None) is not base_fn:
                continue
            out.add(name)
        return out
    except Exception:  # noqa: BLE001
        return set()


async def improver_model(db: AsyncSession, agent: Any) -> str:
    """The tenant's cheapest connected model when the tier allows it, else the agent's own."""
    from app.services.autonomy import default_model

    ctx = await _change_ctx(agent)
    cheap = await default_model(db)
    if ctx["model_ok"](cheap):
        return cheap
    return (agent.model_config_ or {}).get("model") or cheap


def _lesson_brief(lesson: Any) -> dict[str, Any]:
    return {
        "id": str(lesson.id),
        "source": lesson.source,
        "input": (lesson.input_text or "")[:1500],
        "output": (lesson.output_text or "")[:1500],
        "expected": (lesson.expected or "")[:1500] or None,
        "note": (lesson.note or "")[:800] or None,
        "failure_code": lesson.failure_code,
        "tool": lesson.tool_name,
    }


async def recent_results(db: AsyncSession, agent_id: Any, n: int = 5) -> list[dict]:
    from models.execution import Execution

    rows = (
        await db.execute(
            select(Execution.input_message, Execution.output_message, Execution.status)
            .where(Execution.agent_id == agent_id)
            .order_by(Execution.created_at.desc())
            .limit(n)
        )
    ).all()
    return [
        {
            "input": (r[0] or "")[:600],
            "output": (r[1] or "")[:600],
            "status": str(getattr(r[2], "value", r[2]) or ""),
        }
        for r in rows
    ]


def parse_json(textv: str) -> Any:
    t = (textv or "").strip().strip("`")
    if t.startswith("json\n"):
        t = t[5:]
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b == -1:
        raise ValueError("no JSON object in the reply")
    return json.loads(t[a : b + 1])


async def _complete(model_name: str, system: str, prompt: str, tenant: Any) -> Any:
    from engine import credentials
    from engine.llm_router import LLMRouter

    token = credentials.set_tenant(str(tenant))
    try:
        await credentials.ensure_fresh()
        return await LLMRouter().complete(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            model=model_name,
            temperature=0.2,
            max_tokens=2500,
        )
    finally:
        credentials.reset_tenant(token)


async def draft(db: AsyncSession, p: Any, agent: Any) -> None:
    """Ask the improver for one change, check it against the allow list, retry once with the reason."""
    p.progress = R.step(p.progress, "draft", state="running")
    p.progress["message"] = "Drafting one small change for these lessons."
    await db.commit()
    cluster = await get_cluster(db, p.tenant_id, p.cluster_id)
    lessons = await cluster_lessons(db, p.cluster_id, 12)
    base = R.state_of(agent)
    ctx = await _change_ctx(agent)
    mc = base["model_config"]
    tokens = 0
    if mc.get("mode") == "pipeline":
        out = await _draft_pipeline(db, p, agent, cluster, lessons, ctx)
        tokens = out.pop("_tokens", 0)
    else:
        model_name = await improver_model(db, agent)
        cases = await _cases_for(db, agent.id, [lsn.id for lsn in lessons])
        brief = {
            "group": {
                "title": getattr(cluster, "title", ""),
                "summary": getattr(cluster, "summary", ""),
                "count": getattr(cluster, "count", 0),
            },
            "lessons": [_lesson_brief(lsn) for lsn in lessons],
            "test_cases": [
                {
                    "name": c.name,
                    "input": (c.input_message or "")[:800],
                    "assertions": c.assertions,
                }
                for c in cases[:12]
            ],
            "instructions": base["system_prompt"][:24000],
            "tools": list(mc.get("tools") or []),
            "tool_settings": mc.get("tool_config") or {},
            "model": mc.get("model"),
            "read_only_tools_available": sorted(ctx["read_only_tools"])[:200],
            "recent_results": await recent_results(db, agent.id),
        }
        prompt = json.dumps(brief, default=str)
        out, problem = None, None
        for attempt in range(2):
            ask = prompt
            if problem:
                ask += f"\n\nYour last proposal was refused: {problem} Propose a change that is allowed."
            try:
                resp = await _complete(model_name, IMPROVER_SYSTEM, ask, p.tenant_id)
                tokens += int(resp.input_tokens or 0) + int(resp.output_tokens or 0)
                got = parse_json(resp.content)
                kind = str(got.get("change_kind") or "")
                diff = got.get("diff") or {}
                new = R.apply_change(base, kind, diff, **ctx)
                out = {
                    "change_kind": kind,
                    "diff": {**R.clean_diff(diff), "preview": R.preview(base, new)},
                    "rationale": str(got.get("rationale") or "")[:4000],
                    "risk": got.get("risk") if got.get("risk") in R.RISKS else "medium",
                }
                break
            except R.ChangeRejected as e:
                problem = str(e)
            except Exception as e:  # noqa: BLE001
                problem = f"the reply could not be read ({str(e)[:200]})"
        if out is None:
            p.progress = R.step(p.progress, "draft", state="failed")
            p.progress.update({"tokens": tokens, "claimed_until": None})
            p.progress["message"] = (
                f"The improver could not draft an allowed change: {problem}"
            )
            p.state = "failed_proof"
            p.error = p.progress["message"]
            if cluster is not None and cluster.state == "proposing":
                cluster.state = "open"
            await db.commit()
            return
    p.change_kind = out["change_kind"]
    p.diff = out["diff"]
    p.rationale = out["rationale"]
    p.risk = out["risk"]
    p.state = "proving"
    prog = R.step(p.progress, "draft", state="done", done=1, total=1)
    prog["tokens"] = int(prog.get("tokens") or 0) + tokens
    prog["message"] = "Drafted. Proving it against the test set next."
    p.progress = prog
    if cluster is not None:
        cluster.state = "proposed"
    await events.emit(
        db,
        p.tenant_id,
        "improvement.proposed",
        {
            "proposal_id": str(p.id),
            "agent_id": str(p.agent_id),
            "cluster_id": _s(p.cluster_id),
            "change_kind": p.change_kind,
        },
    )
    await db.commit()
    _count_tokens(tokens)


async def _draft_pipeline(db, p, agent, cluster, lessons, ctx) -> dict[str, Any]:
    """Pipelines go through the Pipeline Surgeon, its patch then gets the same proof and approval."""
    from engine import pipeline_surgeon
    from engine.llm_router import LLMRouter

    failing = next((x for x in lessons if x.source == "pipeline_failed"), None)
    failure = {
        "group": getattr(cluster, "title", ""),
        "lesson": _lesson_brief(failing or lessons[0]) if lessons else {},
        "meta": (getattr(failing, "meta", None) or {}) if failing else {},
    }
    mc = agent.model_config_ or {}
    model_name = await improver_model(db, agent)
    from engine import credentials

    token = credentials.set_tenant(str(p.tenant_id))
    try:
        got = await pipeline_surgeon.propose_patch(
            llm_router=LLMRouter(),
            model=model_name,
            dsl_before={"pipeline_config": mc.get("pipeline_config") or {}},
            failure=failure,
            recent_successes=await recent_results(db, agent.id, 3),
            tool_registry=ctx["registry"],
        )
    finally:
        credentials.reset_tenant(token)
    base = R.state_of(agent)
    diff = {"patch": got["json_patch"], "title": got["title"]}
    new = R.apply_change(base, "pipeline_patch", diff, **ctx)
    return {
        "change_kind": "pipeline_patch",
        "diff": {**diff, "preview": R.preview(base, new)},
        "rationale": got.get("rationale") or got["title"],
        "risk": got.get("risk_level") if got.get("risk_level") in R.RISKS else "medium",
        "_tokens": 0,
    }


def _count_tokens(n: int) -> None:
    try:
        from app.core.telemetry import improvement_proof_tokens_total

        if n:
            improvement_proof_tokens_total.inc(n)
    except Exception:  # noqa: BLE001
        pass


# the proof


async def _cases_for(db: AsyncSession, agent_id: Any, lesson_ids: list[Any]) -> list:
    """Accepted cases of every suite of the agent, plus suggested ones written from these lessons."""
    from models.evals import EvalCase, EvalSuite

    q = (
        select(EvalCase)
        .join(EvalSuite, EvalSuite.id == EvalCase.suite_id)
        .where(EvalSuite.agent_id == agent_id)
    )
    state_col = getattr(EvalCase, "state", None)
    lesson_col = getattr(EvalCase, "source_lesson_id", None)
    if state_col is not None:
        conds = [state_col.is_(None), state_col == "accepted"]
        if lesson_col is not None and lesson_ids:
            conds.append(lesson_col.in_(lesson_ids) & (state_col == "suggested"))
        q = q.where(or_(*conds))
    rows = (
        (await db.execute(q.order_by(EvalCase.created_at).limit(MAX_CASES)))
        .scalars()
        .all()
    )
    return list(rows)


async def _gating_suites(db: AsyncSession, agent_id: Any) -> dict[str, float]:
    from models.evals import EvalSuite

    rows = (
        await db.execute(
            select(EvalSuite.id, EvalSuite.pass_threshold).where(
                EvalSuite.agent_id == agent_id, EvalSuite.gating.is_(True)
            )
        )
    ).all()
    return {str(r[0]): float(r[1] or 0.9) for r in rows}


async def replay_inputs(
    db: AsyncSession, agent_id: Any, n: int
) -> list[dict[str, Any]]:
    """Recent real completed runs, stratified by input shape. Their stored answers are the before side."""
    from models.execution import Execution, ExecutionStatus

    if n <= 0:
        return []
    since = _now() - timedelta(days=30)
    rows = (
        await db.execute(
            select(
                Execution.id,
                Execution.input_message,
                Execution.output_message,
                Execution.cost,
                Execution.duration_ms,
                Execution.tool_calls,
            )
            .where(
                Execution.agent_id == agent_id,
                Execution.status == ExecutionStatus.COMPLETED,
                Execution.created_at >= since,
                or_(
                    Execution.trigger_kind.is_(None),
                    Execution.trigger_kind.notin_(("eval", "improvement_proof")),
                ),
            )
            .order_by(Execution.created_at.desc())
            .limit(max(n * 6, 60))
        )
    ).all()
    items = []
    for r in rows:
        calls = r[5]
        if isinstance(calls, dict):
            calls = calls.get("calls") or list(calls.values())
        items.append(
            {
                "execution_id": str(r[0]),
                "input": r[1] or "",
                "output": r[2] or "",
                "cost": float(r[3] or 0),
                "duration_ms": r[4],
                "tool_calls": len(calls) if isinstance(calls, list) else 0,
            }
        )
    return R.stratify(items, n)


def _with_context(message: str, context: dict[str, Any] | None) -> str:
    if not context:
        return message
    lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
    return f"{message}\n\n[Input Parameters]\n{lines}"


async def run_config(
    agent: Any, state: dict[str, Any], message: str, user: Any
) -> dict[str, Any]:
    """One offline run of a configuration with every effect tool held. No execution row is written."""
    from app.services import inline_run
    from engine import credentials, governance

    mc = state.get("model_config") or {}
    tenant = str(agent.tenant_id)
    root = governance.RunContext(
        tenant_id=tenant,
        agent_id=str(agent.id),
        user_id=str(user.id),
        agent_name=str(agent.name or ""),
        scope="pipeline" if mc.get("mode") == "pipeline" else "agent",
        subject_id=str(agent.id),
        replay=True,
    )
    started = time.monotonic()
    ctoken = credentials.set_tenant(tenant)
    gtoken = governance.begin_run(root)
    parts: dict[str, Any] = {}
    try:
        role = str(getattr(getattr(user, "role", None), "value", "user") or "user")
        if mc.get("mode") == "pipeline":
            out = await _run_pipeline(agent, mc, message, user, role)
        else:
            from app.routers.agents import _build_effective_system_prompt
            from engine.agent_executor import AgentExecutor
            from engine.llm_router import LLMRouter

            proxy = SimpleNamespace(
                id=agent.id,
                model_config_=mc,
                system_prompt=state.get("system_prompt") or "",
            )
            run_row = SimpleNamespace(tenant_id=agent.tenant_id, user_id=user.id)
            async with _session() as db:
                parts = await inline_run.prepare(
                    db,
                    proxy,
                    user,
                    run_row,
                    agent_id=str(agent.id),
                    tenant_id=tenant,
                    execution_id="",
                    agent_name=agent.name,
                    db_url="",
                    user_id=str(user.id),
                    user_role=role,
                )
            executor = AgentExecutor(
                llm_router=LLMRouter(),
                tool_registry=parts["registry"],
                system_prompt=_build_effective_system_prompt(
                    parts["system_prompt"], mc.get("tool_config")
                ),
                model=mc.get("model") or "claude-sonnet-4-5-20250929",
                temperature=mc.get("temperature", 0.7),
                max_iterations=int(mc.get("max_iterations") or 10),
                max_tokens=int(mc.get("max_tokens") or 4096),
                agent_id=str(agent.id),
                execution_id="",
                tenant_id=tenant,
                tool_config=mc.get("tool_config") or {},
                require_tools=list(mc.get("require_tools") or []),
                risk_tier=str(mc.get("risk_tier") or ""),
                agent_name=agent.name,
                user_id=str(user.id),
            )
            res = await asyncio.wait_for(executor.invoke(message), RUN_TIMEOUT)
            failed = bool(
                getattr(res, "governance_refusal", None)
                or getattr(res, "budget_exceeded", False)
                or getattr(res, "moderation_blocked", False)
            )
            out = {
                "output": res.output or "",
                "status": "failed" if failed else "completed",
                "cost": float(res.cost or 0),
                "tokens": int(res.input_tokens or 0) + int(res.output_tokens or 0),
                "tool_calls": len(res.tool_calls or []),
                "tool_call_list": res.tool_calls or [],
                "error": (
                    (res.governance_refusal or {}).get("message") if failed else None
                ),
            }
    except asyncio.TimeoutError:
        out = {
            "output": "",
            "status": "failed",
            "error": "The run took too long.",
            "cost": 0.0,
            "tokens": 0,
            "tool_calls": 0,
        }
    except Exception as e:  # noqa: BLE001
        out = {
            "output": "",
            "status": "failed",
            "error": str(e)[:500],
            "cost": 0.0,
            "tokens": 0,
            "tool_calls": 0,
        }
    finally:
        governance.end_run(gtoken)
        credentials.reset_tenant(ctoken)
        for client in parts.get("mcp_clients") or []:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
    out["duration_ms"] = int((time.monotonic() - started) * 1000)
    out["held"] = list(root.replay_held)
    return out


async def _run_pipeline(agent, mc, message, user, role) -> dict[str, Any]:
    from app.routers.agents import _final_text
    from engine.agent_executor import build_tool_registry
    from engine.pipeline import PipelineExecutor, parse_pipeline_nodes, pipeline_usage

    reg = build_tool_registry(
        list(mc.get("tools") or []),
        agent_id=str(agent.id),
        tenant_id=str(agent.tenant_id),
        execution_id="",
        user_id=str(user.id),
        user_role=role,
    )
    # no db_url, so a replay never writes healing captures
    ex = PipelineExecutor(
        tool_registry=reg,
        timeout_seconds=RUN_TIMEOUT,
        db_url="",
        agent_id=str(agent.id),
        tenant_id=str(agent.tenant_id),
    )
    nodes = parse_pipeline_nodes((mc.get("pipeline_config") or {}).get("nodes") or [])
    ctx = {
        k: message
        for k in ("user_message", "message", "input", "prompt", "query", "text")
    }
    res = await asyncio.wait_for(ex.execute(nodes, ctx), RUN_TIMEOUT)
    use = pipeline_usage(res)
    return {
        "output": _final_text(res.final_output) or "",
        "status": "completed" if res.status == "completed" else "failed",
        "cost": float(use.get("cost") or 0),
        "tokens": int(use.get("input_tokens") or 0)
        + int(use.get("output_tokens") or 0),
        "tool_calls": len(res.execution_path or []),
        "error": "; ".join(f"{k}: {v}" for k, v in (res.node_errors or {}).items())[
            :500
        ]
        or None,
    }


def _cache_key(chash: str, message: str) -> str:
    return "impcache:" + hashlib.sha256(f"{chash}|{message}".encode()).hexdigest()


async def _cache_get(key: str) -> dict[str, Any] | None:
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        raw = await r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    return _memo.get(key)


async def _cache_set(key: str, value: dict[str, Any]) -> None:
    if len(_memo) > 2000:
        _memo.clear()
    _memo[key] = value
    try:
        import redis.asyncio as aioredis

        from app.core.config import settings

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.set(key, json.dumps(value, default=str), ex=CACHE_TTL)
    except Exception:  # noqa: BLE001
        pass


async def _judge(rubric: str, inp: str, out: str, model_name: str):
    from app.services.eval_runner import judge

    return await judge(rubric, inp, out, model_name)


async def _score(assertions: list, run: dict[str, Any], message: str, judge_model: str):
    from app.services import eval_assertions as EA

    obs = EA.Observed(
        output=run.get("output") or "",
        tool_calls=run.get("tool_call_list") or [],
        cost=float(run.get("cost") or 0),
        duration_ms=run.get("duration_ms"),
        status=run.get("status") or "failed",
        input_message=message,
    )
    marked = [
        (
            {**a, "model": a.get("model") or judge_model}
            if a.get("type") == "judge"
            else a
        )
        for a in assertions or []
        if isinstance(a, dict)
    ]

    async def judge_fn(rubric, inp, out, model_name):
        return await _judge(rubric, inp, out, model_name or judge_model)

    outcome, judge_cost = await EA.evaluate_case(marked, obs, judge_fn)
    return outcome, float(judge_cost or 0)


def _lesson_case(lesson: Any) -> dict[str, Any]:
    """A target lesson with no case yet still gets checked, from what the person said."""
    if lesson.expected:
        rubric = (
            "The answer must agree with this correct answer from a person: "
            f"{lesson.expected[:1500]}"
        )
    else:
        rubric = (
            "A person said an earlier answer to this input was wrong because: "
            f"{(lesson.note or 'it was not right')[:1500]}. The answer must not make that mistake."
        )
    return {
        "id": None,
        "name": f"Lesson: {(lesson.input_text or '')[:60]}",
        "input": lesson.input_text or "",
        "context": {},
        "assertions": [{"type": "judge", "rubric": rubric, "min_score": 0.7}],
        "suite_id": None,
        "lesson_ids": [str(lesson.id)],
    }


async def _progress(pid: Any, prog: dict[str, Any]) -> None:
    # every save renews the claim, so a long proof is never taken by a second worker
    prog["claimed_until"] = (_now() + timedelta(minutes=CLAIM_MINUTES)).isoformat()
    await _save(pid, progress=dict(prog))


BUDGET_STOP = (
    "It stopped at today's improvement budget before every run finished. "
    "Run the proof again tomorrow, or an admin can raise the budget."
)


async def _budget_stop(tenant_id: Any, agent_id: Any, automatic: bool) -> str | None:
    """Checked as a proof saves progress, so one big proof cannot spend past the day's budget."""
    async with _session() as db:
        s = await settings_for(db, tenant_id, agent_id)
        used = await usage_today(db, tenant_id)
    return BUDGET_STOP if room(used, s, automatic)["tokens"] <= 0 else None


async def prove(pid: Any) -> None:
    """Run the test set and a replay on the candidate and the current revision, then apply the bar."""
    P = Proposal()
    async with _session() as db:
        p = await db.get(P, pid)
        if p is None or p.state != "proving":
            return
        agent = await get_agent(db, p.tenant_id, p.agent_id)
        if agent is None:
            await _fail(pid, "The agent was deleted.")
            return
        user = await db.get(User, p.created_by) if p.created_by else None
        if user is None:
            user = await db.get(User, agent.creator_id)
        if user is None:
            await _fail(pid, "Nobody to run the proof as, the agent's author has left.")
            return
        s = await settings_for(db, p.tenant_id, p.agent_id)
        chash = await current_hash(db, agent.id) or ""
        if p.base_config_hash and chash and p.base_config_hash != chash:
            await _fail(
                pid,
                "The agent changed since this fix was drafted. Run the proof again to check it against the new version.",
            )
            return
        base = R.state_of(agent)
        try:
            cand = R.apply_change(
                base, p.change_kind, R.clean_diff(p.diff), **await _change_ctx(agent)
            )
        except R.ChangeRejected as e:
            await _fail(pid, f"The change no longer applies: {e}")
            return
        lessons = await cluster_lessons(db, p.cluster_id, MAX_TARGET_LESSONS)
        negative = [
            x
            for x in lessons
            if (getattr(x, "polarity", "negative") or "negative") != "positive"
        ]
        cases = await _cases_for(db, agent.id, [x.id for x in lessons])
        gating = await _gating_suites(db, agent.id)
        replay = await replay_inputs(db, agent.id, int(s["replay_sample"]))
        judge_model = await improver_model(db, agent)
        prog = dict(p.progress or {})
        tenant_id, automatic = p.tenant_id, p.created_by is None
        db.expunge_all()

    by_case = {str(c.id): c for c in cases}
    items: list[dict[str, Any]] = [
        {
            "id": str(c.id),
            "name": c.name,
            "input": c.input_message or "",
            "context": c.context or {},
            "assertions": c.assertions or [],
            "suite_id": str(c.suite_id),
            "lesson_ids": [],
        }
        for c in cases
    ]
    for lsn in negative:
        cid = _s(getattr(lsn, "case_id", None))
        if cid and cid in by_case:
            for it in items:
                if it["id"] == cid:
                    it["lesson_ids"].append(str(lsn.id))
        else:
            items.append(_lesson_case(lsn))
    for c in cases:
        lid = _s(getattr(c, "source_lesson_id", None))
        if lid and any(str(x.id) == lid for x in negative):
            for it in items:
                if it["id"] == str(c.id) and lid not in it["lesson_ids"]:
                    it["lesson_ids"].append(lid)

    tokens = int(prog.get("tokens") or 0)
    prog = R.step(prog, "test_set", state="running", done=0, total=len(items))
    prog["message"] = (
        f"Running {len(items)} test cases on the current and the new version."
    )
    await _progress(pid, prog)

    sem = asyncio.Semaphore(4)
    results: list[dict[str, Any]] = []
    done = 0
    last_save = 0.0
    stop: str | None = None

    async def save_and_check() -> None:
        nonlocal stop
        prog["tokens"] = tokens
        await _progress(pid, prog)
        if stop is None:
            stop = await _budget_stop(tenant_id, agent.id, automatic)

    async def one_case(it: dict[str, Any]) -> None:
        nonlocal tokens, done, last_save, prog
        msg = _with_context(it["input"], it["context"])
        async with sem:
            if stop:
                return
            key = _cache_key(chash, msg)
            before = await _cache_get(key)
            timed = before is None
            if before is None:
                before = await run_config(agent, base, msg, user)
                tokens += int(before.get("tokens") or 0)
                if before.get("status") == "completed":
                    await _cache_set(key, before)
            after = await run_config(agent, cand, msg, user)
            tokens += int(after.get("tokens") or 0)
            ob, _ = await _score(it["assertions"], before, msg, judge_model)
            oa, _ = await _score(it["assertions"], after, msg, judge_model)
        results.append(
            {
                "item": it,
                "before": {
                    **before,
                    "passed": ob.passed,
                    "score": ob.score,
                    "kind": "case",
                    "cost": float(before.get("cost") or 0),
                    "timed": timed,
                },
                "after": {
                    **after,
                    "passed": oa.passed,
                    "score": oa.score,
                    "kind": "case",
                    "cost": float(after.get("cost") or 0),
                    "timed": timed,
                },
                "why": (
                    next(
                        (
                            r.get("message") or r.get("reason")
                            for r in oa.results
                            if not r.get("passed")
                        ),
                        None,
                    )
                    if not oa.passed
                    else None
                ),
            }
        )
        done += 1
        if time.monotonic() - last_save > 1.0 or done == len(items):
            last_save = time.monotonic()
            prog = R.step(prog, "test_set", done=done)
            await save_and_check()

    await asyncio.gather(*(one_case(it) for it in items))
    if stop:
        prog["tokens"] = tokens
        await _progress(pid, prog)
        await _fail(pid, stop)
        return
    prog = R.step(prog, "test_set", state="done", done=len(items), total=len(items))
    prog = R.step(prog, "replay", state="running", done=0, total=len(replay))
    prog["message"] = (
        f"Replaying {len(replay)} recent real inputs with every action held, nothing changes in the world."
        if replay
        else "The agent has no recent runs to replay."
    )
    prog["tokens"] = tokens
    await _progress(pid, prog)

    replays: list[dict[str, Any]] = []
    done = 0

    async def one_replay(r: dict[str, Any]) -> None:
        nonlocal tokens, done, last_save, prog
        async with sem:
            if stop:
                return
            after = await run_config(agent, cand, r["input"], user)
        tokens += int(after.get("tokens") or 0)
        replays.append({"input": r, "after": after})
        done += 1
        if time.monotonic() - last_save > 1.0 or done == len(replay):
            last_save = time.monotonic()
            prog = R.step(prog, "replay", done=done)
            await save_and_check()

    await asyncio.gather(*(one_replay(r) for r in replay))
    if stop:
        prog["tokens"] = tokens
        await _progress(pid, prog)
        await _fail(pid, stop)
        return
    prog = R.step(prog, "replay", state="done", done=len(replay), total=len(replay))
    prog = R.step(prog, "comparing", state="running", done=0, total=1)
    prog["message"] = "Comparing the two versions."
    prog["tokens"] = tokens
    await _progress(pid, prog)

    proof = build_proof(results, replays, negative, gating, s)
    proof["tokens"] = tokens
    proof["finished_at"] = _now().isoformat()
    _count_tokens(tokens)
    prog = R.step(prog, "comparing", state="done", done=1)
    prog = R.step(prog, "done", state="done", done=1, total=1)
    prog.update(
        {
            "phase": "done",
            "tokens": tokens,
            "claimed_until": None,
            "finished_at": proof["finished_at"],
            "message": (
                f"Fixed {len(proof['fixed'])} of {len(negative) or len(proof['fixed'])} lessons, broke {len(proof['broken'])}."
            ),
        }
    )
    await finish_proof(pid, proof, prog)


def build_proof(
    results: list[dict[str, Any]],
    replays: list[dict[str, Any]],
    lessons: list[Any],
    gating: dict[str, float],
    s: dict[str, Any],
) -> dict[str, Any]:
    """The proof JSON from per-case and replay outcomes. Pure, so the bar is testable."""
    titles = {str(x.id): (x.input_text or "")[:120] for x in lessons}
    fixed, still, broken, examples = [], [], [], []
    fixed_ids: set[str] = set()
    for r in results:
        it, b, a = r["item"], r["before"], r["after"]
        for lid in it["lesson_ids"]:
            if a["passed"] and lid not in fixed_ids:
                fixed_ids.add(lid)
                fixed.append({"lesson_id": lid, "title": titles.get(lid, it["name"])})
            elif not a["passed"]:
                still.append({"lesson_id": lid, "title": titles.get(lid, it["name"])})
        if b["passed"] and not a["passed"]:
            broken.append(
                {
                    "case_id": it["id"],
                    "name": it["name"],
                    "why": r.get("why") or a.get("error") or "It no longer passes.",
                }
            )
        if it["lesson_ids"] and a["passed"] and not b["passed"]:
            examples.append(
                {
                    "input": it["input"][:1000],
                    "before": (b.get("output") or "")[:1500],
                    "after": (a.get("output") or "")[:1500],
                    "verdict": "fixed",
                }
            )
    changed_n, held_n = 0, 0
    replay_before, replay_after = [], []
    for rp in replays:
        src, a = rp["input"], rp["after"]
        held_n += len(a.get("held") or [])
        replay_before.append(
            {**src, "status": "completed", "kind": "replay", "timed": False}
        )
        replay_after.append({**a, "kind": "replay", "timed": False})
        if a.get("status") != "completed":
            broken.append(
                {
                    "case_id": None,
                    "name": f"Replay: {src['input'][:60]}",
                    "why": f"The run failed on a real input that worked before: {a.get('error') or 'no answer'}",
                }
            )
        elif R.changed(src.get("output"), a.get("output")):
            changed_n += 1
            if len(examples) < 6:
                examples.append(
                    {
                        "input": src["input"][:1000],
                        "before": (src.get("output") or "")[:1500],
                        "after": (a.get("output") or "")[:1500],
                        "verdict": "changed",
                    }
                )
    before = R.summarise([r["before"] for r in results] + replay_before)
    after = R.summarise([r["after"] for r in results] + replay_after)
    gating_ok: bool | None = None
    for suite_id, threshold in gating.items():
        rows = [r for r in results if r["item"].get("suite_id") == suite_id]
        if not rows:
            continue
        score = sum(float(r["after"].get("score") or 0) for r in rows) / len(rows)
        gating_ok = (gating_ok is not False) and score >= threshold
    passed, reasons = R.bar(
        fixed=len(fixed),
        broken=len(broken),
        before=before,
        after=after,
        gating_ok=gating_ok,
        cost_margin=float(s["cost_margin"]),
        latency_margin=float(s["latency_margin"]),
    )
    still_ids = {x["lesson_id"] for x in still} - fixed_ids
    return {
        "fixed": fixed,
        "broken": broken,
        "still_failing": [x for x in still if x["lesson_id"] in still_ids],
        "target_lessons": len(lessons),
        "cases_run": len(results),
        "scores": {"before": before, "after": after},
        "replay": {
            "sampled": len(replays),
            "changed": changed_n,
            "watching_effects": held_n,
        },
        "gating": {"suites": len(gating), "passed": gating_ok},
        "examples": examples[:3],
        "passed_bar": passed,
        "bar_reasons": reasons,
    }


async def finish_proof(pid: Any, proof: dict[str, Any], prog: dict[str, Any]) -> None:
    P = Proposal()
    async with _session() as db:
        p = await db.get(P, pid)
        if p is None:
            return
        p.proof = proof
        p.progress = prog
        p.state = "awaiting_approval" if proof["passed_bar"] else "failed_proof"
        if not proof["passed_bar"]:
            p.error = " ".join(proof["bar_reasons"])
            c = await db.get(Cluster(), p.cluster_id) if p.cluster_id else None
            if c is not None and c.state in ("proposing", "proposed"):
                c.state = "open"
        await events.emit(
            db,
            p.tenant_id,
            "improvement.proved",
            {
                "proposal_id": str(p.id),
                "agent_id": str(p.agent_id),
                "passed_bar": proof["passed_bar"],
                "fixed": len(proof["fixed"]),
                "broken": len(proof["broken"]),
            },
        )
        await db.commit()
        try:
            from app.core.telemetry import improvement_proofs_total

            improvement_proofs_total.labels(
                result="passed" if proof["passed_bar"] else "failed"
            ).inc()
        except Exception:  # noqa: BLE001
            pass
        if proof["passed_bar"]:
            await request_approval(db, p)


# approval


async def request_approval(db: AsyncSession, p: Any) -> dict[str, Any]:
    """Idempotent: a pending approval for this proposal is returned as it is."""
    if p.state != "awaiting_approval":
        raise ImprovementError(
            "Only a proposal that passed its proof goes for approval. "
            + (
                " ".join((p.proof or {}).get("bar_reasons") or [])
                if p.state == "failed_proof"
                else ""
            ),
            409,
            "NOT_PROVEN",
        )
    if p.approval_id is not None:
        a = await db.get(Approval, p.approval_id)
        if a is not None and a.status == ApprovalStatus.pending:
            return {"approval_id": str(a.id), "created": False}
    agent = await get_agent(db, p.tenant_id, p.agent_id)
    cluster = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    requester_id = p.created_by or getattr(agent, "creator_id", None)
    requester = await db.get(User, requester_id) if requester_id else None
    self_reason = None
    if requester is not None and str(getattr(agent, "creator_id", "")) == str(
        requester.id
    ):
        self_reason = await self_approval_reason(db, requester, agent)
    row = proposal_row(p, agent, cluster)
    payload = {
        **row,
        "kind": GATE,
        "proposal_id": str(p.id),
        "agent_creator_id": _s(getattr(agent, "creator_id", None)),
        "is_sample": is_sample(agent),
        "self_approval": self_reason,
        "link": f"/agents/{p.agent_id}/improvements?proposal={p.id}",
    }
    title = f"Release a fix to {getattr(agent, 'name', 'an agent')}: {getattr(cluster, 'title', '') or row['change_label']}"
    a = Approval(
        id=uuid.uuid4(),
        tenant_id=p.tenant_id,
        agent_id=p.agent_id,
        title=title[:255],
        payload=payload,
        required_signoffs=1,
        signoffs=[],
        status=ApprovalStatus.pending,
        requested_by=requester_id,
        expires_at=_now() + timedelta(days=7),
        gate_kind=GATE,
        policy={"exclude_requester": False, "capability": "improvements.approve"},
    )
    db.add(a)
    await db.flush()
    p.approval_id = a.id
    await events.emit(
        db,
        p.tenant_id,
        "approval.requested",
        {
            "approval_id": str(a.id),
            "title": a.title,
            "gate_kind": GATE,
            "required_signoffs": 1,
        },
    )
    await db.commit()
    if requester is not None:
        try:
            from app.routers.approvals import _notify_pending

            await _notify_pending(db, a, requester=requester)
        except Exception as e:  # noqa: BLE001
            logger.warning("approval notification failed: %s", e)
    await _notify(
        db,
        p,
        agent,
        type="improvement_ready",
        title=f"A proven fix for {getattr(agent, 'name', 'your agent')} is ready to approve",
        message=(
            f"It fixed {len((p.proof or {}).get('fixed') or [])} lessons and broke none. "
            "Someone with Approve improvements signs it off in Approvals."
        ),
    )
    return {"approval_id": str(a.id), "created": True}


async def request_approval_for(db: AsyncSession, user: Any, pid: Any) -> dict[str, Any]:
    p = await get_proposal(db, user.tenant_id, pid)
    if p is None:
        raise ImprovementError("This proposal was not found.", 404, "NOT_FOUND")
    await check_propose(db, user, await get_agent(db, p.tenant_id, p.agent_id))
    out = await request_approval(db, p)
    return {**await row_for(db, p), **out}


async def on_release_resolved(db: AsyncSession, approval: Any, decider: Any) -> None:
    """Approved releases the fix, a rejection becomes a lesson for the improver."""
    payload = approval.payload or {}
    p = await get_proposal(
        db, approval.tenant_id, payload.get("proposal_id") or payload.get("id")
    )
    if p is None or p.approval_id != approval.id:
        return
    status = getattr(approval.status, "value", approval.status)
    if status == "approved" and decider is not None:
        if p.state != "awaiting_approval":
            return
        p.state = "approved"
        await db.commit()
        try:
            await release(db, p, decider)
        except ImprovementError as e:
            p.state = "superseded" if e.code == "AGENT_CHANGED" else "failed_proof"
            p.error = e.message
            await db.commit()
        return
    reason = ""
    for s in reversed(approval.signoffs or []):
        if s.get("decision") in ("deny", "return"):
            reason = (s.get("reason") or "").strip()
            break
    p.state = "rejected"
    p.error = (
        f"Rejected: {reason}"
        if reason
        else ("Nobody approved it in time." if status == "expired" else "Rejected.")
    )
    c = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    if c is not None and c.state in ("proposed", "proposing"):
        c.state = "open"
    if reason and status in ("denied", "returned"):
        await _rejection_lesson(db, p, reason, decider)
    await db.commit()


async def _rejection_lesson(
    db: AsyncSession, p: Any, reason: str, decider: Any
) -> None:
    try:
        L = Lesson()
    except ImprovementError:
        return
    lsn = L(
        id=uuid.uuid4(),
        tenant_id=p.tenant_id,
        agent_id=p.agent_id,
        cluster_id=p.cluster_id,
        source="note",
        polarity="negative",
        input_text=f"Proposed fix: {R.CHANGE_LABELS.get(p.change_kind or '', '')}",
        output_text=json.dumps(R.clean_diff(p.diff), default=str)[:8000],
        note=f"A person rejected this fix: {reason}"[:4000],
        by_user=getattr(decider, "id", None),
        meta={"proposal_id": str(p.id), "rejected_fix": True},
    )
    db.add(lsn)


# release


async def _record(
    db, agent, *, actor_id, change_type, previous, source, summary, proposal_id
):
    from app.services.agent_revisions import record_revision

    return await record_revision(
        db,
        agent,
        changed_by=actor_id,
        change_type=change_type,
        previous_state=previous,
        source=source,
        diff_summary=summary,
        proposal_id=proposal_id,
    )


async def release(db: AsyncSession, p: Any, approver: Any) -> Any:
    """Apply the proven change as a revision, the same path a person's edit takes."""
    from app.core.audit import log_action
    from app.services.agent_revisions import agent_state

    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == p.agent_id, Agent.tenant_id == p.tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if agent is None:
        raise ImprovementError("The agent was deleted.", 404, "NOT_FOUND")
    chash = await current_hash(db, agent.id)
    if p.base_config_hash and chash and chash != p.base_config_hash:
        raise ImprovementError(
            "The agent changed after this fix was proved, so it was not released. Run the proof again.",
            409,
            "AGENT_CHANGED",
        )
    base = R.state_of(agent)
    new = R.apply_change(
        base, p.change_kind, R.clean_diff(p.diff), **await _change_ctx(agent)
    )
    previous = agent_state(agent)
    agent.system_prompt = new["system_prompt"]
    agent.model_config_ = new["model_config"]
    cluster = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    rev = await _record(
        db,
        agent,
        actor_id=approver.id,
        change_type="improvement",
        previous=previous,
        source="improvement",
        summary=f"Improvement: {getattr(cluster, 'title', '') or R.CHANGE_LABELS.get(p.change_kind, '')}"[
            :500
        ],
        proposal_id=p.id,
    )
    s = await settings_for(db, p.tenant_id, p.agent_id)
    now = _now()
    p.state = "released"
    p.released_revision_id = rev.id
    p.watch_until = now + timedelta(days=int(s["watch_days"]))
    p.watch_runs_target = int(s["watch_runs"])
    await db.flush()
    p.watch_result = {
        "outcome": "watching",
        "started_at": now.isoformat(),
        "base_hash": chash,
        "new_hash": await current_hash(db, agent.id),
        "approved_by": str(approver.id),
        "approved_by_name": _name(approver),
        "points": [],
    }
    await log_action(
        db,
        p.tenant_id,
        approver.id,
        "improvement.released",
        {
            "proposal_id": str(p.id),
            "agent_id": str(agent.id),
            "revision_id": str(rev.id),
        },
        resource_type="agent",
        resource_id=str(agent.id),
    )
    await events.emit(
        db,
        p.tenant_id,
        "improvement.released",
        {
            "proposal_id": str(p.id),
            "agent_id": str(agent.id),
            "revision_id": str(rev.id),
            "watch_until": _iso(p.watch_until),
        },
    )
    await db.commit()
    _release_metric("released")
    await _start_gate_runs(db, agent, approver)
    return rev


async def _start_gate_runs(db: AsyncSession, agent: Any, user: Any) -> None:
    """The eval gate runs on every change to a live agent, so start its gating suites on the new revision."""
    from app.services.eval_runner import start_run
    from models.evals import EvalSuite

    try:
        suites = (
            (
                await db.execute(
                    select(EvalSuite).where(
                        EvalSuite.agent_id == agent.id, EvalSuite.gating.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        for su in suites:
            await start_run(db, su, user.id, triggered_by="publish_gate")
    except Exception as e:  # noqa: BLE001
        logger.warning("gating suites after release did not start: %s", e)


def _release_metric(outcome: str) -> None:
    try:
        from app.core.telemetry import improvement_releases_total

        improvement_releases_total.labels(outcome=outcome).inc()
    except Exception:  # noqa: BLE001
        pass


# the watch


async def measures(
    db: AsyncSession,
    agent_id: Any,
    chash: str | None,
    since: datetime,
    until: datetime | None,
    cluster_id: Any,
) -> dict[str, Any]:
    """Live results of one revision of the agent in a window."""
    from models.autonomy import AgentAction
    from models.drift_alert import DriftAlert
    from models.execution import Execution, ExecutionStatus

    out: dict[str, Any] = {"runs": 0, "failures": 0, "cost_avg": 0.0}
    if not chash:
        return out
    conds = [
        Execution.agent_id == agent_id,
        Execution.provenance["config_hash"].astext == chash,
        Execution.created_at >= since,
        or_(
            Execution.trigger_kind.is_(None),
            Execution.trigger_kind.notin_(("eval", "improvement_proof")),
        ),
    ]
    if until is not None:
        conds.append(Execution.created_at < until)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Execution.status == ExecutionStatus.FAILED),
                func.avg(Execution.cost),
            ).where(*conds)
        )
    ).first()
    out["runs"], out["failures"] = int(row[0] or 0), int(row[1] or 0)
    out["cost_avg"] = round(float(row[2] or 0), 6)
    try:
        F = Feedback()
        fb = (
            await db.execute(
                select(func.count(), func.count().filter(F.rating < 0))
                .select_from(F)
                .join(Execution, Execution.id == F.execution_id)
                .where(*conds)
            )
        ).first()
        out["thumbs_total"], out["thumbs_down"] = int(fb[0] or 0), int(fb[1] or 0)
    except ImprovementError:
        out["thumbs_total"], out["thumbs_down"] = 0, 0
    acc = (
        await db.execute(
            select(
                func.count().filter(AgentAction.score.isnot(None)),
                func.count().filter(AgentAction.score["within_band"].astext == "true"),
            ).where(
                AgentAction.agent_id == agent_id,
                AgentAction.agent_config_hash == chash,
                AgentAction.created_at >= since,
                *([AgentAction.created_at < until] if until is not None else []),
            )
        )
    ).first()
    out["scored"], out["accurate"] = int(acc[0] or 0), int(acc[1] or 0)
    if until is None:
        drift = (
            await db.execute(
                select(DriftAlert.metric).where(
                    DriftAlert.agent_id == agent_id, DriftAlert.created_at >= since
                )
            )
        ).all()
        out["drift"] = sorted({r[0] for r in drift})
    if cluster_id is not None:
        try:
            L = Lesson()
            q = (
                select(func.count())
                .select_from(L)
                .where(L.cluster_id == cluster_id, L.created_at >= since)
            )
            if until is not None:
                q = q.where(L.created_at < until)
            out["cluster_lessons"] = int((await db.execute(q)).scalar() or 0)
        except ImprovementError:
            out["cluster_lessons"] = 0
    return out


async def check_watch(db: AsyncSession, p: Any) -> str:
    """Compare old and new now. Returns watching, kept, rolled_back or stopped."""
    wr = dict(p.watch_result or {})
    started = (
        datetime.fromisoformat(wr["started_at"])
        if wr.get("started_at")
        else p.updated_at
    )
    s = await settings_for(db, p.tenant_id, p.agent_id)
    now_hash = await current_hash(db, p.agent_id)
    if wr.get("new_hash") and now_hash and now_hash != wr["new_hash"]:
        wr.update(
            {
                "outcome": "stopped",
                "reason": "The agent was changed after the release, so the watch stopped.",
                "checked_at": _now().isoformat(),
            }
        )
        p.watch_result = wr
        p.state = "superseded"
        await db.commit()
        return "stopped"
    old = await measures(
        db,
        p.agent_id,
        wr.get("base_hash"),
        started - timedelta(days=int(s["watch_days"])),
        started,
        p.cluster_id,
    )
    new = await measures(
        db, p.agent_id, wr.get("new_hash"), started, None, p.cluster_id
    )
    reasons = R.watch_reasons(
        old, new, min_runs=int(s["watch_min_runs"]), cost_margin=float(s["cost_margin"])
    )
    now = _now()
    points = list(wr.get("points") or [])[-49:]
    points.append(
        {
            "at": now.isoformat(),
            "runs": new["runs"],
            "failure_rate": R.rate(new["failures"], new["runs"]),
            "thumbs_down_rate": R.rate(
                new.get("thumbs_down", 0), new.get("thumbs_total", 0)
            ),
            "cost_avg": new["cost_avg"],
        }
    )
    wr.update(
        {
            "old": old,
            "new": new,
            "points": points,
            "checked_at": now.isoformat(),
            "worse": reasons,
        }
    )
    p.watch_result = wr
    if reasons:
        await rollback(db, p, None, " ".join(reasons), automatic=True)
        return "rolled_back"
    if R.watch_done(new["runs"], int(p.watch_runs_target or 0), now, p.watch_until):
        await keep(db, p, new)
        return "kept"
    await db.commit()
    return "watching"


async def keep(db: AsyncSession, p: Any, new: dict[str, Any]) -> None:
    wr = dict(p.watch_result or {})
    wr.update({"outcome": "kept", "ended_at": _now().isoformat()})
    p.watch_result = wr
    p.state = "kept"
    c = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    if c is not None:
        c.state = "fixed"
    await events.emit(
        db,
        p.tenant_id,
        "improvement.kept",
        {
            "proposal_id": str(p.id),
            "agent_id": str(p.agent_id),
            "runs": new.get("runs", 0),
        },
    )
    await db.commit()
    _release_metric("kept")
    agent = await get_agent(db, p.tenant_id, p.agent_id)
    await _notify(
        db,
        p,
        agent,
        type="improvement_kept",
        title=f"The fix to {getattr(agent, 'name', 'your agent')} was kept",
        message=f"It did as well or better than the old version over {new.get('runs', 0)} runs. The lessons it fixed are closed.",
        approvers=True,
    )


async def rollback(
    db: AsyncSession, p: Any, actor: Any, reason: str, *, automatic: bool = False
) -> dict[str, Any]:
    """Back to the revision before the release, at once, with no approval."""
    from app.core.audit import log_action
    from app.services.agent_revisions import agent_state
    from models.agent_revision import AgentRevision

    if p.state != "released":
        raise ImprovementError(
            f"Only a release in its watch period can be rolled back. This one is {R.STATE_LABELS.get(p.state, p.state).lower()}.",
            409,
            "WRONG_STATE",
        )
    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == p.agent_id, Agent.tenant_id == p.tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if agent is None:
        raise ImprovementError("The agent was deleted.", 404, "NOT_FOUND")
    wr = dict(p.watch_result or {})
    now_hash = await current_hash(db, agent.id)
    if wr.get("new_hash") and now_hash and now_hash != wr["new_hash"]:
        raise ImprovementError(
            "The agent changed after this release, so rolling back would undo someone's edit. "
            "Restore an earlier version from the agent's revision history instead.",
            409,
            "AGENT_CHANGED",
        )
    rev = (
        await db.get(AgentRevision, p.released_revision_id)
        if p.released_revision_id
        else None
    )
    prev = (rev.previous_state if rev is not None else None) or {}
    if "system_prompt" not in prev and "model_config" not in prev:
        raise ImprovementError(
            "The version before this release was not found.", 409, "NO_PREVIOUS"
        )
    before = agent_state(agent)
    if prev.get("system_prompt") is not None:
        agent.system_prompt = prev["system_prompt"]
    if prev.get("model_config") is not None:
        agent.model_config_ = prev["model_config"]
    actor_id = (
        getattr(actor, "id", None) or _uuid(wr.get("approved_by")) or agent.creator_id
    )
    why = reason.strip() or "Rolled back by a person."
    await _record(
        db,
        agent,
        actor_id=actor_id,
        change_type="revert",
        previous=before,
        source="revert",
        summary=f"Rolled back the improvement: {why}"[:500],
        proposal_id=p.id,
    )
    wr.update(
        {
            "outcome": "rolled_back",
            "reason": why,
            "automatic": automatic,
            "rolled_back_by": None if automatic else str(actor_id),
            "rolled_back_by_name": "Automatic" if automatic else _name(actor),
            "ended_at": _now().isoformat(),
        }
    )
    p.watch_result = wr
    p.state = "rolled_back"
    c = await get_cluster(db, p.tenant_id, p.cluster_id) if p.cluster_id else None
    if c is not None and c.state in ("proposed", "fixed"):
        c.state = "open"
    await log_action(
        db,
        p.tenant_id,
        actor_id,
        "improvement.rolled_back",
        {
            "proposal_id": str(p.id),
            "agent_id": str(agent.id),
            "reason": why,
            "automatic": automatic,
        },
        resource_type="agent",
        resource_id=str(agent.id),
    )
    await events.emit(
        db,
        p.tenant_id,
        "improvement.rolled_back",
        {
            "proposal_id": str(p.id),
            "agent_id": str(agent.id),
            "reason": why,
            "actor": "system" if automatic else "user",
        },
    )
    await db.commit()
    _release_metric("rolled_back")
    await _notify(
        db,
        p,
        agent,
        type="improvement_rolled_back",
        title=f"The fix to {agent.name} was rolled back",
        message=(
            f"It was rolled back automatically because it did worse. {why}"
            if automatic
            else f"{_name(actor) or 'Someone'} rolled it back. {why}"
        ),
        approvers=True,
        exclude=None if automatic else getattr(actor, "id", None),
    )
    return await row_for(db, p)


async def rollback_by_user(
    db: AsyncSession, user: Any, pid: Any, reason: str
) -> dict[str, Any]:
    p = await get_proposal(db, user.tenant_id, pid)
    if p is None:
        raise ImprovementError("This proposal was not found.", 404, "NOT_FOUND")
    agent = await get_agent(db, p.tenant_id, p.agent_id)
    if str(getattr(agent, "creator_id", "")) != str(user.id):
        await check_propose(db, user, agent)
    return await rollback(db, p, user, reason, automatic=False)


async def watch_now(db: AsyncSession, user: Any, pid: Any) -> dict[str, Any]:
    p = await get_proposal(db, user.tenant_id, pid)
    if p is None:
        raise ImprovementError("This proposal was not found.", 404, "NOT_FOUND")
    await check_view(db, user, await get_agent(db, p.tenant_id, p.agent_id))
    if p.state != "released":
        raise ImprovementError(
            "Only a release in its watch period is checked.", 409, "WRONG_STATE"
        )
    await check_watch(db, p)
    return await row_for(db, p)


async def _notify(
    db: AsyncSession,
    p: Any,
    agent: Any,
    *,
    type: str,
    title: str,
    message: str,
    approvers: bool = False,
    exclude: Any = None,
) -> None:
    ids: list[uuid.UUID] = []
    for uid in (getattr(agent, "creator_id", None), p.created_by):
        u = _uuid(uid)
        if u and u not in ids:
            ids.append(u)
    if approvers and p.approval_id is not None:
        a = await db.get(Approval, p.approval_id)
        for s in (a.signoffs if a is not None else None) or []:
            u = _uuid(s.get("user_id"))
            if u and u not in ids and s.get("decision") == "approve":
                ids.append(u)
    for uid in ids:
        if exclude is not None and str(uid) == str(exclude):
            continue
        try:
            await notif.create_notification(
                db,
                tenant_id=p.tenant_id,
                user_id=uid,
                type=type,
                title=title[:255],
                message=message,
                link=f"/agents/{p.agent_id}/improvements?proposal={p.id}",
                metadata={"proposal_id": str(p.id), "agent_id": str(p.agent_id)},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("improvement notification failed: %s", e)
    # callers notify after their own commit, so the rows are committed here
    await db.commit()


# scheduled jobs: the IMPP tick only enqueues and drains, the IMPW tick watches


async def auto_propose(db: AsyncSession) -> int:
    """Open clusters over the size or severity threshold get a proposal, worst first."""
    C = Cluster()
    P = Proposal()
    sev = {"high": 3, "medium": 2, "low": 1}
    rows = (
        (
            await db.execute(
                select(C)
                .where(C.state == "open")
                .where(
                    ~select(P.id)
                    .where(P.cluster_id == C.id, P.state.in_(R.ACTIVE_STATES))
                    .exists()
                )
                .order_by(C.updated_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    rows = sorted(
        rows, key=lambda c: -sev.get(str(c.severity or "low"), 1) * int(c.count or 0)
    )
    made = 0
    settings_cache: dict[str, dict[str, Any]] = {}
    for c in rows:
        t = str(c.tenant_id)
        if t not in settings_cache:
            settings_cache[t] = await tenant_settings(db, c.tenant_id)
        s = R.settings_for(settings_cache[t], c.agent_id)
        if not s["auto_propose"]:
            continue
        if not (
            int(c.count or 0) >= int(s["auto_propose_min_count"])
            or c.severity == "high"
        ):
            continue
        if await stopped(c.tenant_id):
            continue
        if budget_reason(await usage_today(db, c.tenant_id), s, automatic=True):
            continue
        sysuser = SimpleNamespace(id=None, tenant_id=c.tenant_id)
        try:
            await propose(db, sysuser, c.id, automatic=True)
            made += 1
        except ImprovementError as e:
            logger.debug("auto propose skipped for %s: %s", c.id, e.message)
        if made >= 20:
            break
    return made


async def propose_tick() -> dict[str, int]:
    out = {"proposed": 0, "claimed": 0}
    try:
        async with _session() as db:
            out["proposed"] = await auto_propose(db)
            try:
                from app.core.telemetry import (
                    improvement_clusters_open,
                    improvement_proof_queue_depth,
                )

                improvement_proof_queue_depth.set(await queue_depth(db))
                C = Cluster()
                improvement_clusters_open.set(
                    int(
                        (
                            await db.execute(
                                select(func.count())
                                .select_from(C)
                                .where(C.state == "open")
                            )
                        ).scalar()
                        or 0
                    )
                )
            except ImprovementError:
                raise
            except Exception:  # noqa: BLE001
                pass
    except ImprovementError:
        return out
    if drains_here():
        out["claimed"] = await drain_once()
    return out


async def watch_tick() -> dict[str, int]:
    P = Proposal()
    counts = {"watching": 0, "kept": 0, "rolled_back": 0, "stopped": 0}
    async with _session() as db:
        ids = (
            (
                await db.execute(
                    select(P.id)
                    .where(P.state == "released")
                    .order_by(P.watch_until)
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
    for pid in ids:
        try:
            async with _session() as db:
                p = await db.get(P, pid)
                if p is None or p.state != "released":
                    continue
                counts[await check_watch(db, p)] += 1
        except Exception:  # noqa: BLE001
            logger.exception("watch check for %s failed", pid)
    return counts


# GDPR and retention reach proposals through the agent and the tenant, see gdpr_purge


async def get_row(db: AsyncSession, user: Any, pid: Any) -> dict[str, Any]:
    p = await get_proposal(db, user.tenant_id, pid)
    if p is None:
        raise ImprovementError("This proposal was not found.", 404, "NOT_FOUND")
    await check_view(db, user, await get_agent(db, p.tenant_id, p.agent_id))
    return await row_for(db, p)


async def propose_for(db: AsyncSession, user: Any, cluster_id: Any) -> dict[str, Any]:
    return await propose(db, user, cluster_id)


async def list_for(
    db: AsyncSession,
    user: Any,
    *,
    agent_id: Any = None,
    state: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Proposals the caller may see, newest first. Backs the SDK's improvements.list."""
    P = Proposal()
    q = select(P).where(P.tenant_id == user.tenant_id)
    if agent_id is not None:
        aid = _uuid(agent_id)
        if aid is None:
            raise ImprovementError("agent_id is not a valid id.", 400, "BAD_ID")
        q = q.where(P.agent_id == aid)
    if state:
        if state not in R.STATES:
            raise ImprovementError(
                "state must be one of " + ", ".join(R.STATES) + ".", 400, "BAD_STATE"
            )
        q = q.where(P.state == state)
    visible = await _visible(db, user)
    if visible is not None:
        q = q.where(P.agent_id.in_(list(visible) or [uuid.uuid4()]))
    rows = (
        (
            await db.execute(
                q.order_by(P.created_at.desc()).limit(max(1, min(limit, 200)))
            )
        )
        .scalars()
        .all()
    )
    return {"items": [await row_for(db, p) for p in rows]}


# the sample: an agent with a planted mistake and lessons that point at it

SAMPLE_PROMPT = (
    "You are a friendly temperature conversion helper.\n"
    "Convert the temperature the user gives you and show the result with at most two decimals.\n"
    "Always give the answer in degrees Fahrenheit, whatever unit the user asks for.\n"
    "Keep every answer to one short sentence."
)
SAMPLE_LESSONS = (
    (
        "What is 25 degrees Celsius in Kelvin?",
        "25 °C is 77 °F.",
        "25 °C is 298.15 K.",
        "298.15",
    ),
    ("Convert 100 °C to kelvin", "100 °C is 212 °F.", "100 °C is 373.15 K.", "373.15"),
    (
        "How many kelvin is 0 degrees Celsius?",
        "0 °C is 32 °F.",
        "0 °C is 273.15 K.",
        "273.15",
    ),
    ("I need -40 C in K please", "-40 °C is -40 °F.", "-40 °C is 233.15 K.", "233.15"),
)
SAMPLE_GOOD = (
    ("Convert 212 degrees Fahrenheit to Celsius", "100"),
    ("What is 50 °F in Celsius?", "10"),
)
SAMPLE_CLUSTER_TITLE = "Answers in Fahrenheit when the user asks for Kelvin"


async def install_sample(db: AsyncSession, user: Any) -> dict[str, Any]:
    """Idempotent. The agent, four corrected lessons in one group, their suggested tests and two good examples."""
    from app.services.autonomy import default_model
    from models.agent import AgentStatus
    from models.evals import EvalCase, EvalSuite

    agent = (
        await db.execute(
            select(Agent).where(
                Agent.tenant_id == user.tenant_id,
                Agent.slug == SAMPLE_SLUG,
                Agent.status != AgentStatus.ARCHIVED,
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        from app.routers import agents as agents_router
        from app.schemas.agents import CreateAgentRequest

        body = CreateAgentRequest(
            name=SAMPLE_NAME,
            slug=SAMPLE_SLUG,
            description="Converts temperatures. It has a planted mistake so you can watch the improvement loop fix it.",
            system_prompt=SAMPLE_PROMPT,
            model_config={
                "model": await default_model(db),
                "temperature": 0.0,
                "tools": [],
                "max_tokens": 300,
                "max_iterations": 2,
            },
            category="sample",
        )
        resp = await agents_router.create_agent(body, None, user, db)
        payload = json.loads(bytes(resp.body))
        if payload.get("error"):
            raise ImprovementError(
                "The sample agent could not be created: "
                + str((payload["error"] or {}).get("message")),
                resp.status_code,
                "SAMPLE_FAILED",
            )
        agent = await get_agent(db, user.tenant_id, payload["data"]["id"])
    C, L = Cluster(), Lesson()
    cluster = (
        await db.execute(
            select(C).where(
                C.tenant_id == user.tenant_id,
                C.agent_id == agent.id,
                C.signature == "sample:kelvin",
            )
        )
    ).scalar_one_or_none()
    if cluster is not None:
        reset = await _reset_sample(db, user, agent, cluster)
        return {
            "agent_id": str(agent.id),
            "cluster_id": str(cluster.id),
            "created": False,
            "reset": reset,
        }
    now = _now()
    cluster = C(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        title=SAMPLE_CLUSTER_TITLE,
        summary="People asked for Kelvin and got Fahrenheit, then said what the right answer was.",
        signature="sample:kelvin",
        count=len(SAMPLE_LESSONS),
        negative_count=len(SAMPLE_LESSONS),
        severity="medium",
        trend=[{"day": now.date().isoformat(), "count": len(SAMPLE_LESSONS)}],
        state="open",
        last_lesson_at=now,
    )
    db.add(cluster)
    suite = (
        await db.execute(
            select(EvalSuite).where(
                EvalSuite.agent_id == agent.id, EvalSuite.name == "Improvement tests"
            )
        )
    ).scalar_one_or_none()
    if suite is None:
        suite = EvalSuite(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            name="Improvement tests",
            description="Tests written from the agent's lessons.",
            agent_id=agent.id,
            gating=False,
            pass_threshold=0.9,
            created_by=user.id,
        )
        db.add(suite)
    await db.flush()
    for inp, out, expected, must in SAMPLE_LESSONS:
        lid = uuid.uuid4()
        case = EvalCase(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            suite_id=suite.id,
            name=f"Kelvin: {inp[:60]}",
            input_message=inp,
            assertions=[{"type": "contains", "value": must}],
            reference_output=expected,
        )
        if hasattr(EvalCase, "state"):
            case.state = "suggested"
            case.source_lesson_id = lid
        db.add(case)
        db.add(
            L(
                id=lid,
                tenant_id=user.tenant_id,
                agent_id=agent.id,
                cluster_id=cluster.id,
                case_id=case.id,
                source="correction",
                polarity="negative",
                input_text=inp,
                output_text=out,
                expected=expected,
                note="It answered in Fahrenheit, I asked for Kelvin.",
                by_user=user.id,
                meta={"sample": True},
            )
        )
    for inp, must in SAMPLE_GOOD:
        case = EvalCase(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            suite_id=suite.id,
            name=f"Good: {inp[:60]}",
            input_message=inp,
            assertions=[{"type": "contains", "value": must}],
        )
        if hasattr(EvalCase, "state"):
            case.state = "accepted"
        db.add(case)
    await _sample_settings(db, user.tenant_id, agent.id)
    await db.commit()
    return {"agent_id": str(agent.id), "cluster_id": str(cluster.id), "created": True}


async def _reset_sample(db: AsyncSession, user: Any, agent: Any, cluster: Any) -> bool:
    """Trying the sample again puts the planted mistake back once the last loop has finished."""
    from app.services.agent_revisions import agent_state

    if await active_proposal(db, cluster.id) is not None:
        return False
    if cluster.state == "open" and agent.system_prompt == SAMPLE_PROMPT:
        return False
    if agent.system_prompt != SAMPLE_PROMPT:
        previous = agent_state(agent)
        agent.system_prompt = SAMPLE_PROMPT
        await _record(
            db,
            agent,
            actor_id=user.id,
            change_type="prompt_update",
            previous=previous,
            source="edit",
            summary="The sample was reset to its planted mistake",
            proposal_id=None,
        )
    cluster.state = "open"
    await db.commit()
    return True


async def _sample_settings(db: AsyncSession, tenant_id: Any, agent_id: Any) -> None:
    """A short watch for the sample, so the whole loop fits in a few minutes."""
    from sqlalchemy.orm.attributes import flag_modified

    from models.tenant import Tenant

    t = (
        await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if t is None:
        return
    st = dict(t.settings or {})
    imp = dict(st.get("improvements") or {})
    agents = dict(imp.get("agents") or {})
    agents[str(agent_id)] = {
        "watch_min_runs": 3,
        "watch_runs": 20,
        "replay_sample": 10,
        "watch_days": 1,
    }
    imp["agents"] = agents
    st["improvements"] = imp
    t.settings = st
    flag_modified(t, "settings")
