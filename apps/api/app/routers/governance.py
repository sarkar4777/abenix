"""Governance: capabilities, permission sets, risk tier policies, kill switches, audit chain."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import capabilities as caps
from app.core.audit import log_action
from app.core.capabilities import require_capability
from app.core.deps import get_current_user, get_db
from app.core.responses import error, success
from engine import governance, risk
from models.governance import (
    KillSwitch,
    PermissionAssignment,
    PermissionSet,
    RiskPolicy,
)
from models.user import User

router = APIRouter(prefix="/api/governance", tags=["governance"])


@router.get("/capabilities")
async def list_capabilities(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    mine = await caps.capabilities_for(db, user)
    return success(
        {
            "catalog": caps.catalog_json(),
            "role_defaults": {r: sorted(v) for r, v in caps.ROLE_DEFAULTS.items()},
            "mine": sorted(mine),
        }
    )


class PermissionSetBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)


def _set_json(ps: PermissionSet, members: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(ps.id),
        "name": ps.name,
        "description": ps.description,
        "capabilities": list(ps.capabilities or []),
        "members": members,
        "created_at": ps.created_at.isoformat() if ps.created_at else None,
        "updated_at": ps.updated_at.isoformat() if ps.updated_at else None,
    }


def _bad_caps(values: list[str]) -> list[str]:
    return [c for c in values if not caps.valid_capability(c)]


@router.get("/permission-sets")
async def list_permission_sets(
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    sets = (
        (
            await db.execute(
                select(PermissionSet)
                .where(PermissionSet.tenant_id == user.tenant_id)
                .order_by(PermissionSet.name)
            )
        )
        .scalars()
        .all()
    )
    rows = (
        await db.execute(
            select(
                PermissionAssignment.permission_set_id,
                User.id,
                User.email,
                User.full_name,
            )
            .join(User, User.id == PermissionAssignment.user_id)
            .where(PermissionAssignment.tenant_id == user.tenant_id)
        )
    ).all()
    members: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for set_id, uid, email, name in rows:
        members.setdefault(set_id, []).append(
            {"user_id": str(uid), "email": email, "name": name}
        )
    return success([_set_json(s, members.get(s.id, [])) for s in sets])


@router.post("/permission-sets")
async def create_permission_set(
    body: PermissionSetBody,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    bad = _bad_caps(body.capabilities)
    if bad:
        return error(f"Unknown capabilities: {', '.join(bad)}", 400)
    exists = (
        await db.execute(
            select(PermissionSet.id).where(
                PermissionSet.tenant_id == user.tenant_id,
                PermissionSet.name == body.name.strip(),
            )
        )
    ).scalar()
    if exists:
        return error(f"A permission set named {body.name.strip()} already exists", 409)
    ps = PermissionSet(
        tenant_id=user.tenant_id,
        name=body.name.strip(),
        description=body.description,
        capabilities=sorted(set(body.capabilities)),
        created_by=user.id,
    )
    db.add(ps)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "permission_set.created",
        {"name": ps.name, "capabilities": ps.capabilities},
        request,
        resource_type="permission_set",
        resource_id=str(ps.id),
    )
    await db.commit()
    await db.refresh(ps)
    return success(_set_json(ps, []), status_code=201)


async def _get_set(
    db: AsyncSession, user: User, set_id: uuid.UUID
) -> PermissionSet | None:
    return (
        await db.execute(
            select(PermissionSet).where(
                PermissionSet.id == set_id, PermissionSet.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


@router.patch("/permission-sets/{set_id}")
async def update_permission_set(
    set_id: uuid.UUID,
    body: PermissionSetBody,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ps = await _get_set(db, user, set_id)
    if ps is None:
        return error("Permission set not found", 404)
    bad = _bad_caps(body.capabilities)
    if bad:
        return error(f"Unknown capabilities: {', '.join(bad)}", 400)
    old = {"name": ps.name, "capabilities": list(ps.capabilities or [])}
    ps.name = body.name.strip()
    ps.description = body.description
    ps.capabilities = sorted(set(body.capabilities))
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "permission_set.updated",
        None,
        request,
        resource_type="permission_set",
        resource_id=str(ps.id),
        old_value=old,
        new_value={"name": ps.name, "capabilities": ps.capabilities},
    )
    await db.commit()
    caps.invalidate()
    await db.refresh(ps)
    return success(_set_json(ps, []))


@router.delete("/permission-sets/{set_id}")
async def delete_permission_set(
    set_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ps = await _get_set(db, user, set_id)
    if ps is None:
        return error("Permission set not found", 404)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "permission_set.deleted",
        {"name": ps.name, "capabilities": list(ps.capabilities or [])},
        request,
        resource_type="permission_set",
        resource_id=str(ps.id),
    )
    await db.delete(ps)
    await db.commit()
    caps.invalidate()
    return success({"deleted": True})


class AssignBody(BaseModel):
    email: str


@router.post("/permission-sets/{set_id}/members")
async def add_member(
    set_id: uuid.UUID,
    body: AssignBody,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ps = await _get_set(db, user, set_id)
    if ps is None:
        return error("Permission set not found", 404)
    email = body.email.strip().lower()
    member = (
        await db.execute(
            select(User).where(User.email == email, User.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if member is None:
        return error(f"No user with email {email} in this tenant", 404)
    exists = (
        await db.execute(
            select(PermissionAssignment.id).where(
                PermissionAssignment.permission_set_id == ps.id,
                PermissionAssignment.user_id == member.id,
            )
        )
    ).scalar()
    if not exists:
        db.add(
            PermissionAssignment(
                tenant_id=user.tenant_id,
                permission_set_id=ps.id,
                user_id=member.id,
                created_by=user.id,
            )
        )
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "permission_set.member_added",
            {"set": ps.name, "member": email},
            request,
            resource_type="permission_set",
            resource_id=str(ps.id),
        )
        await db.commit()
    caps.invalidate(member.id)
    return success(
        {"user_id": str(member.id), "email": member.email, "name": member.full_name}
    )


@router.delete("/permission-sets/{set_id}/members/{user_id}")
async def remove_member(
    set_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("permissions.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    ps = await _get_set(db, user, set_id)
    if ps is None:
        return error("Permission set not found", 404)
    res = await db.execute(
        delete(PermissionAssignment).where(
            PermissionAssignment.permission_set_id == ps.id,
            PermissionAssignment.user_id == user_id,
        )
    )
    if res.rowcount:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "permission_set.member_removed",
            {"set": ps.name, "member_id": str(user_id)},
            request,
            resource_type="permission_set",
            resource_id=str(ps.id),
        )
    await db.commit()
    caps.invalidate(user_id)
    return success({"removed": bool(res.rowcount)})


@router.get("/risk")
async def risk_overview(
    user: User = Depends(require_capability("risk.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    stored = {
        p.tier: p
        for p in (
            await db.execute(
                select(RiskPolicy).where(RiskPolicy.tenant_id == user.tenant_id)
            )
        )
        .scalars()
        .all()
    }
    tiers = []
    for t in risk.TIERS:
        row = stored.get(t)
        tiers.append(
            {
                "tier": t,
                "guide": risk.TIER_GUIDE[t],
                "default": risk.DEFAULT_POLICIES[t],
                "overrides": (row.policy if row else {}) or {},
                "effective": risk.merged_policy(t, row.policy if row else None),
                "updated_at": (
                    row.updated_at.isoformat() if row and row.updated_at else None
                ),
            }
        )
    return success(
        {
            "tiers": tiers,
            "tool_call_actions": list(risk.TOOL_CALL_ACTIONS),
            "tools": _tool_tiers(),
        }
    )


def _tool_tiers() -> list[dict[str, str]]:
    from engine.agent_executor import get_tool_class, list_tool_classes

    out = []
    for slug in list_tool_classes():
        cls = get_tool_class(slug)
        if cls is None:
            continue
        out.append(
            {"tool": slug, "tier": risk.normalize(getattr(cls, "risk_tier", "low"))}
        )
    return sorted(out, key=lambda r: (-risk.rank(r["tier"]), r["tool"]))


@router.put("/risk/{tier}")
async def set_risk_policy(
    tier: str,
    body: dict[str, Any],
    request: Request,
    user: User = Depends(require_capability("risk.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if tier not in risk.TIERS:
        return error(f"tier must be one of {', '.join(risk.TIERS)}", 400)
    problems = risk.validate_policy(body)
    if problems:
        return error("; ".join(problems), 400)
    row = (
        await db.execute(
            select(RiskPolicy).where(
                RiskPolicy.tenant_id == user.tenant_id, RiskPolicy.tier == tier
            )
        )
    ).scalar_one_or_none()
    old = dict(row.policy or {}) if row else {}
    if row is None:
        row = RiskPolicy(
            tenant_id=user.tenant_id, tier=tier, policy=body, updated_by=user.id
        )
        db.add(row)
    else:
        row.policy = body
        row.updated_by = user.id
        row.updated_at = datetime.now(timezone.utc)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "risk_policy.updated",
        {"tier": tier},
        request,
        resource_type="risk_policy",
        resource_id=tier,
        old_value=old,
        new_value=body,
    )
    await db.commit()
    governance.invalidate()
    return success(
        {"tier": tier, "overrides": body, "effective": risk.merged_policy(tier, body)}
    )


@router.delete("/risk/{tier}")
async def reset_risk_policy(
    tier: str,
    request: Request,
    user: User = Depends(require_capability("risk.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if tier not in risk.TIERS:
        return error(f"tier must be one of {', '.join(risk.TIERS)}", 400)
    res = await db.execute(
        delete(RiskPolicy).where(
            RiskPolicy.tenant_id == user.tenant_id, RiskPolicy.tier == tier
        )
    )
    if res.rowcount:
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "risk_policy.reset",
            {"tier": tier},
            request,
            resource_type="risk_policy",
            resource_id=tier,
        )
    await db.commit()
    governance.invalidate()
    return success({"tier": tier, "effective": risk.DEFAULT_POLICIES[tier]})


class KillSwitchBody(BaseModel):
    scope: str
    target: str = "*"
    reason: str = Field(min_length=3, max_length=2000)


def _switch_json(k: KillSwitch) -> dict[str, Any]:
    return {
        "id": str(k.id),
        "scope": k.scope,
        "target": k.target,
        "active": k.active,
        "reason": k.reason,
        "set_by": str(k.set_by) if k.set_by else None,
        "set_at": k.set_at.isoformat() if k.set_at else None,
        "cleared_by": str(k.cleared_by) if k.cleared_by else None,
        "cleared_at": k.cleared_at.isoformat() if k.cleared_at else None,
    }


@router.get("/kill-switches")
async def list_kill_switches(
    include_cleared: bool = False,
    user: User = Depends(require_capability("risk.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    q = select(KillSwitch).where(KillSwitch.tenant_id == user.tenant_id)
    if not include_cleared:
        q = q.where(KillSwitch.active.is_(True))
    rows = (
        (await db.execute(q.order_by(KillSwitch.set_at.desc()).limit(500)))
        .scalars()
        .all()
    )
    return success(
        {"switches": [_switch_json(k) for k in rows], "scopes": list(governance.SCOPES)}
    )


@router.post("/kill-switches")
async def set_kill_switch(
    body: KillSwitchBody,
    request: Request,
    user: User = Depends(require_capability("killswitch.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.scope not in governance.SCOPES:
        return error(f"scope must be one of {', '.join(governance.SCOPES)}", 400)
    target = "*" if body.scope == "all" else (body.target.strip() or "*")
    existing = (
        await db.execute(
            select(KillSwitch).where(
                KillSwitch.tenant_id == user.tenant_id,
                KillSwitch.scope == body.scope,
                KillSwitch.target == target,
                KillSwitch.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return success(_switch_json(existing))
    k = KillSwitch(
        tenant_id=user.tenant_id,
        scope=body.scope,
        target=target,
        reason=body.reason.strip(),
        active=True,
        set_by=user.id,
    )
    db.add(k)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "kill_switch.set",
        {"scope": k.scope, "target": k.target, "reason": k.reason},
        request,
        resource_type="kill_switch",
        resource_id=str(k.id),
    )
    from app.services.events import emit

    await emit(
        db,
        user.tenant_id,
        "kill_switch.set",
        {"scope": k.scope, "target": k.target, "reason": k.reason},
    )
    await db.commit()
    governance.invalidate()
    await db.refresh(k)
    return success(_switch_json(k), status_code=201)


@router.post("/kill-switches/{switch_id}/clear")
async def clear_kill_switch(
    switch_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_capability("killswitch.manage")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    k = (
        await db.execute(
            select(KillSwitch).where(
                KillSwitch.id == switch_id, KillSwitch.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if k is None:
        return error("Kill switch not found", 404)
    if k.active:
        k.active = False
        k.cleared_by = user.id
        k.cleared_at = datetime.now(timezone.utc)
        await log_action(
            db,
            user.tenant_id,
            user.id,
            "kill_switch.cleared",
            {"scope": k.scope, "target": k.target},
            request,
            resource_type="kill_switch",
            resource_id=str(k.id),
        )
        from app.services.events import emit

        await emit(
            db,
            user.tenant_id,
            "kill_switch.cleared",
            {"scope": k.scope, "target": k.target},
        )
        await db.commit()
        governance.invalidate()
    return success(_switch_json(k))


@router.get("/audit/verify")
async def verify_audit_chain(
    request: Request,
    user: User = Depends(require_capability("audit.verify")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.services.audit_chain import verify_tenant

    started = datetime.now(timezone.utc)
    result = await verify_tenant(db, user.tenant_id)
    result["verified_at"] = started.isoformat()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "audit.verified",
        {
            "ok": result["ok"],
            "checked": result["checked"],
            "reason": result.get("reason"),
        },
        request,
    )
    await db.commit()
    return success(result)


@router.get("/runs/{execution_id}/provenance")
async def run_provenance(
    execution_id: uuid.UUID,
    user: User = Depends(require_capability("runs.replay")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from models.agent import Agent
    from models.execution import Execution
    from models.governance import ExecutionConfigSnapshot

    ex = (
        await db.execute(
            select(Execution).where(
                Execution.id == execution_id, Execution.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if ex is None:
        return error("Execution not found", 404)
    prov = dict(ex.provenance or {})
    snap = None
    if prov.get("config_hash"):
        snap = await db.get(ExecutionConfigSnapshot, prov["config_hash"])
    current = None
    if ex.agent_id:
        current = (
            await db.execute(select(Agent).where(Agent.id == ex.agent_id))
        ).scalar_one_or_none()
    changed: list[str] = []
    if snap is not None and current is not None:
        if (snap.system_prompt or "") != (current.system_prompt or ""):
            changed.append("system_prompt")
        then, now = snap.model_config or {}, current.model_config_ or {}
        changed += sorted(k for k in set(then) | set(now) if then.get(k) != now.get(k))
    return success(
        {
            "execution_id": str(ex.id),
            "agent_id": str(ex.agent_id) if ex.agent_id else None,
            "agent_revision": ex.agent_revision,
            "prompt_hash": ex.prompt_hash,
            "risk_tier": ex.risk_tier,
            "risk_reasons": ex.risk_reasons or [],
            "provenance": prov,
            "snapshot": (
                {"system_prompt": snap.system_prompt, "model_config": snap.model_config}
                if snap
                else None
            ),
            "changed_since": changed,
            "agent_deleted": ex.agent_id is not None and current is None,
        }
    )


@router.get("/audit/export")
async def export_audit(
    request: Request,
    since: str | None = None,
    until: str | None = None,
    user: User = Depends(require_capability("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    """The tenant's linked activity log as JSON lines, with each row's hashes, for evidence and archiving."""
    from fastapi.responses import StreamingResponse
    from sqlalchemy import text as _text

    from app.core.deps import async_session

    try:
        lo = datetime.fromisoformat(since) if since else None
        hi = datetime.fromisoformat(until) if until else None
    except ValueError:
        return error("Use ISO dates for since and until, like 2026-01-01.", 400)
    tenant_id = user.tenant_id
    await log_action(
        db,
        tenant_id,
        user.id,
        "audit.exported",
        {"since": since, "until": until},
        request,
    )
    await db.commit()
    await db.close()

    async def gen():
        import json as _json

        last = 0
        while True:
            async with async_session() as s:
                rows = (
                    (
                        await s.execute(
                            _text(
                                "SELECT id, chain_pos, action, details, created_at, prev_hash, row_hash, pii_digest, "
                                "user_id, audit_seq FROM activity_logs WHERE tenant_id = :t AND chain_pos > :p "
                                "AND (CAST(:lo AS timestamptz) IS NULL OR created_at >= :lo) "
                                "AND (CAST(:hi AS timestamptz) IS NULL OR created_at < :hi) "
                                "ORDER BY chain_pos LIMIT 2000"
                            ),
                            {"t": tenant_id, "p": last, "lo": lo, "hi": hi},
                        )
                    )
                    .mappings()
                    .all()
                )
            if not rows:
                break
            for r in rows:
                line = {
                    k: (
                        v.isoformat()
                        if hasattr(v, "isoformat")
                        else str(v) if k in ("id", "user_id") else v
                    )
                    for k, v in r.items()
                }
                yield (_json.dumps(line, default=str) + "\n").encode()
            last = int(rows[-1]["chain_pos"])

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=audit-log.jsonl"},
    )


class ReplayBody(BaseModel):
    mode: str = "pinned"  # pinned | current
    model: str | None = None


@router.post("/runs/{execution_id}/replay")
async def replay_run(
    execution_id: uuid.UUID,
    body: ReplayBody,
    request: Request,
    user: User = Depends(require_capability("runs.replay")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run a past agent execution again on its recorded input, pinned to what it ran with or on the agent as it is now."""
    from app.core.config import settings
    from engine.agent_executor import AgentExecutor, build_tool_registry
    from engine.llm_router import LLMRouter
    from models.agent import Agent
    from models.execution import Execution, ExecutionStatus
    from models.governance import ExecutionConfigSnapshot

    if body.mode not in ("pinned", "current"):
        return error("mode must be pinned or current", 400)
    ex = (
        await db.execute(
            select(Execution).where(
                Execution.id == execution_id, Execution.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()
    if ex is None or ex.agent_id is None:
        return error("Execution not found", 404)
    agent = await db.get(Agent, ex.agent_id)
    if agent is None:
        return error(
            "The agent behind this run was deleted, so it cannot be replayed.", 409
        )
    snap = None
    prov = dict(ex.provenance or {})
    if body.mode == "pinned":
        snap = (
            await db.get(ExecutionConfigSnapshot, prov.get("config_hash"))
            if prov.get("config_hash")
            else None
        )
        if snap is None:
            return error(
                "This run has no recorded configuration, it predates provenance. Replay it on the current agent instead.",
                409,
                error_code="NO_SNAPSHOT",
            )
        system_prompt, mc = snap.system_prompt or "", dict(snap.model_config or {})
    else:
        system_prompt, mc = agent.system_prompt or "", dict(agent.model_config_ or {})
    if mc.get("mode") == "pipeline":
        return error("Pipeline runs replay from a step on the run page.", 400)
    model = body.model or mc.get("model") or "claude-sonnet-4-5-20250929"
    new = Execution(
        tenant_id=user.tenant_id,
        agent_id=agent.id,
        user_id=user.id,
        input_message=ex.input_message,
        status=ExecutionStatus.RUNNING,
        parent_execution_id=ex.id,
        model_requested=model,
        provenance=(
            {**prov, "replay_of": str(ex.id), "replay_mode": "pinned"}
            if body.mode == "pinned"
            else None
        ),
        agent_revision=ex.agent_revision if body.mode == "pinned" else None,
        prompt_hash=ex.prompt_hash if body.mode == "pinned" else None,
    )
    db.add(new)
    await db.commit()
    await db.refresh(new)
    registry = build_tool_registry(
        list(mc.get("tools") or []),
        agent_id=str(agent.id),
        tenant_id=str(user.tenant_id),
        execution_id=str(new.id),
        agent_name=agent.name,
        db_url=str(settings.database_url).replace("+asyncpg", ""),
        user_id=str(user.id),
        user_role=user.role.value if hasattr(user.role, "value") else str(user.role),
    )
    executor = AgentExecutor(
        llm_router=LLMRouter(),
        tool_registry=registry,
        system_prompt=system_prompt,
        model=model,
        temperature=mc.get("temperature", 0.7),
        max_tokens=mc.get("max_tokens", 4096),
        max_iterations=mc.get("max_iterations", 10),
        agent_id=str(agent.id),
        execution_id=str(new.id),
        tenant_id=str(user.tenant_id),
        tool_config=mc.get("tool_config"),
        agent_name=agent.name,
    )
    await db.close()
    try:
        result = await executor.invoke(ex.input_message or "")
        failed = bool(result.governance_refusal)
        err_msg = (result.governance_refusal or {}).get("message")
    except Exception as e:  # noqa: BLE001
        result, failed, err_msg = None, True, str(e)[:1000]
    from app.core.deps import async_session

    async with async_session() as s:
        row = await s.get(Execution, new.id)
        row.status = ExecutionStatus.FAILED if failed else ExecutionStatus.COMPLETED
        row.completed_at = datetime.now(timezone.utc)
        if result is not None:
            row.output_message = result.output
            row.input_tokens, row.output_tokens = (
                result.input_tokens,
                result.output_tokens,
            )
            row.cost = float(result.cost)
            row.duration_ms = result.duration_ms
            row.tool_calls = result.tool_calls or None
            row.model_used = result.model
            row.risk_tier = result.risk_tier or row.risk_tier
            row.risk_reasons = result.risk_reasons or None
        if err_msg:
            row.error_message = err_msg
        await log_action(
            s,
            user.tenant_id,
            user.id,
            "run.replayed",
            {
                "original": str(ex.id),
                "replay": str(new.id),
                "mode": body.mode,
                "model": model,
            },
            request,
        )
        await s.commit()
    before_tools = [t.get("name") for t in (ex.tool_calls or []) if isinstance(t, dict)]
    after_tools = [
        t.get("name")
        for t in ((result.tool_calls if result else None) or [])
        if isinstance(t, dict)
    ]
    return success(
        {
            "execution_id": str(new.id),
            "mode": body.mode,
            "original": {
                "output": ex.output_message,
                "model": ex.model_used,
                "tools": before_tools,
                "cost": float(ex.cost or 0),
            },
            "replay": {
                "output": result.output if result else None,
                "model": result.model if result else model,
                "tools": after_tools,
                "cost": float(result.cost) if result else 0.0,
                "error": err_msg,
            },
            "same_output": bool(result)
            and (result.output or "").strip() == (ex.output_message or "").strip(),
            "same_tools": before_tools == after_tools,
        }
    )
