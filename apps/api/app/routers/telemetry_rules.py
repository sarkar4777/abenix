"""Signal rules over telemetry streams: build, preview against history, and see what each firing did."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_action
from app.core.capabilities import cap_words, require_capability
from app.core.deps import get_db
from app.core.responses import error, success
from app.telemetry import access, reads
from app.telemetry import keys as K
from app.telemetry.rules import model as M
from app.telemetry.rules import preview as P
from app.telemetry.rules.evaluator import HEALTH_KEY, VERSION_KEY
from app.telemetry.rules.index import AssetFacts, akey, compile_rule
from models.telemetry_rules import TelemetryAsset, TelemetryRule, TelemetryRuleFiring
from models.user import User

router = APIRouter(prefix="/api/telemetry/rules", tags=["telemetry"])

MAX_RULES = 500
PREVIEW_HOURS = (1, 6, 24)


def _redis() -> Any:
    from app.routers.telemetry import redis

    return redis()


async def _bump() -> None:
    try:
        await _redis().incr(VERSION_KEY)
    except Exception:  # noqa: BLE001
        pass


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def _invalid(fields: dict[str, str]) -> JSONResponse:
    return error(
        next(iter(fields.values())),
        422,
        error_code="VALIDATION_ERROR",
        details={"fields": fields},
    )


def _refusal() -> JSONResponse:
    return error(
        f"Changing rules needs {cap_words('telemetry.manage')}. An admin can grant it under Admin, Permissions.",
        403,
        error_code="FORBIDDEN",
    )


async def _facts(db: AsyncSession, tenant: Any) -> tuple[AssetFacts, dict[str, str]]:
    rows = (
        await db.execute(
            select(
                TelemetryAsset.grp,
                TelemetryAsset.node,
                TelemetryAsset.device,
                TelemetryAsset.display_name,
                TelemetryAsset.asset_type,
                TelemetryAsset.tags,
            ).where(TelemetryAsset.tenant_id == tenant)
        )
    ).all()
    f = AssetFacts()
    names = {}
    for g, n, d, name, t, tags in rows:
        f.rows[akey(g, n, d or "")] = {
            "type": t,
            "tags": list(tags or []),
            "name": name,
        }
        if name:
            names[akey(g, n, d or "")] = name
    return f, names


async def _labels(db: AsyncSession, rules: list[Any]) -> dict[str, str]:
    from models.agent import Agent

    ids = set()
    for r in rules:
        for a in r.actions or []:
            if a.get("kind") == "run" and a.get("agent_id"):
                try:
                    ids.add(uuid.UUID(str(a["agent_id"])))
                except ValueError:
                    pass
    if not ids:
        return {}
    rows = (
        await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    ).all()
    return {str(i): n for i, n in rows}


async def _visible(db: AsyncSession, user: User) -> tuple[bool, set[str], bool]:
    scope = await access.scope_for(db, user)
    can_edit = scope.everything or await access.has(db, user, "telemetry.manage")
    if scope.everything:
        return True, set(), can_edit
    from app.routers.telemetry_assets import my_teams

    return False, await my_teams(db, user), can_edit


def _sees(rule: Any, everything: bool, teams: set[str]) -> bool:
    return everything or not rule.team_id or str(rule.team_id) in teams


def _rule_json(
    r: Any,
    names: dict[str, str],
    labels: dict[str, str],
    can_edit: bool,
    open_count: int = 0,
    last: Any = None,
) -> dict[str, Any]:
    body = {"condition": r.condition, "scope": r.scope, "actions": r.actions}
    return {
        "id": str(r.id),
        "name": r.name,
        "description": r.description,
        "enabled": r.enabled,
        "severity": r.severity,
        "scope": r.scope,
        "condition": r.condition,
        "cooldown_s": r.cooldown_s,
        "actions": r.actions,
        "team_id": str(r.team_id) if r.team_id else None,
        "summary": M.describe(body, names, labels),
        "condition_words": M.describe_condition(r.condition or {}),
        "scope_words": M.describe_scope(r.scope or {}, names),
        "action_words": [M.describe_action(a, labels) for a in r.actions or []],
        "fire_count": r.fire_count or 0,
        "last_fired_at": _iso(r.last_fired_at),
        "firing_now": open_count,
        "last_firing": last,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
        "can_edit": can_edit,
    }


def _firing_json(f: Any, outputs: bool = False) -> dict[str, Any]:
    steps = f.actions or []
    if not outputs:
        steps = [
            {k: v for k, v in a.items() if k not in ("input", "output")}
            for a in steps
            if isinstance(a, dict)
        ]
    return {
        "id": str(f.id),
        "rule_id": str(f.rule_id) if f.rule_id else None,
        "rule": f.rule_name,
        "fired_at": _iso(f.fired_at),
        "cleared_at": _iso(f.cleared_at),
        "status": f.status,
        "group": f.grp,
        "node": f.node,
        "device": f.device,
        "asset": (f.context or {}).get("asset") or f.node,
        "signal": f.signal,
        "value": f.value,
        "detail": f.detail,
        "actions": steps,
    }


async def _check_actions(
    db: AsyncSession, user: User, actions: list[dict[str, Any]]
) -> dict[str, str]:
    """Steps the saver cannot set up, in plain words per field."""
    err: dict[str, str] = {}
    for i, a in enumerate(actions):
        k = a.get("kind")
        if k == "command" and not await access.has(db, user, "telemetry.command"):
            err[f"actions.{i}.kind"] = (
                f"Sending commands needs {cap_words('telemetry.command')}. "
                "An admin can add you to Machine operators under Admin, Permissions."
            )
        if k == "run":
            from app.services.agent_share import resolve_agent_access
            from models.agent import Agent, AgentType
            from models.resource_share import SharePermission

            try:
                aid = uuid.UUID(a.get("agent_id") or "")
            except ValueError:
                err[f"actions.{i}.agent_id"] = "Pick the agent or pipeline to run."
                continue
            agent = (
                await db.execute(
                    select(Agent).where(
                        Agent.id == aid,
                        or_(
                            Agent.tenant_id == user.tenant_id,
                            Agent.agent_type == AgentType.OOB,
                        ),
                    )
                )
            ).scalar_one_or_none()
            if agent is None:
                err[f"actions.{i}.agent_id"] = (
                    "That agent or pipeline does not exist in this workspace."
                )
            elif not await resolve_agent_access(
                db, user, agent, permission_required=SharePermission.EXECUTE
            ):
                err[f"actions.{i}.agent_id"] = (
                    f"You cannot run {agent.name}, so the rule cannot run it for you."
                )
        if k == "decision":
            from models.decision import DecisionModel

            ok = await db.scalar(
                select(DecisionModel.id).where(
                    DecisionModel.tenant_id == user.tenant_id,
                    DecisionModel.key == a.get("key"),
                    DecisionModel.archived_at.is_(None),
                )
            )
            if not ok:
                err[f"actions.{i}.key"] = (
                    f"No decision table called {a.get('key')}. Pick one from the list."
                )
        if k == "notify" and a.get("to"):
            from models.user import User as U

            ids = []
            for x in a["to"]:
                try:
                    ids.append(uuid.UUID(str(x)))
                except ValueError:
                    err[f"actions.{i}.to"] = "Pick people from the list."
            if ids:
                n = await db.scalar(
                    select(func.count())
                    .select_from(U)
                    .where(U.id.in_(ids), U.tenant_id == user.tenant_id)
                )
                if int(n or 0) != len(set(ids)):
                    err[f"actions.{i}.to"] = (
                        "Some of these people are not in this workspace."
                    )
    return err


async def _team(
    db: AsyncSession, user: User, raw: Any, err: dict[str, str]
) -> uuid.UUID | None:
    if not raw:
        return None
    from models.governance import PermissionSet

    try:
        tid = uuid.UUID(str(raw))
    except ValueError:
        err["team_id"] = "Pick a team from the list."
        return None
    ok = await db.scalar(
        select(PermissionSet.id).where(
            PermissionSet.id == tid, PermissionSet.tenant_id == user.tenant_id
        )
    )
    if not ok:
        err["team_id"] = "That team does not exist in this workspace."
    return tid


# reading


@router.get("")
async def list_rules(
    q: str = "",
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    everything, teams, can_edit = await _visible(db, user)
    rules = (
        (
            await db.execute(
                select(TelemetryRule)
                .where(TelemetryRule.tenant_id == user.tenant_id)
                .order_by(TelemetryRule.name)
            )
        )
        .scalars()
        .all()
    )
    rules = [r for r in rules if _sees(r, everything, teams)]
    if q.strip():
        ql = q.strip().lower()
        rules = [
            r
            for r in rules
            if ql in r.name.lower() or ql in (r.description or "").lower()
        ]
    ids = [r.id for r in rules]
    open_counts: dict[str, int] = {}
    lasts: dict[str, dict[str, Any]] = {}
    if ids:
        for rid, n in (
            await db.execute(
                select(TelemetryRuleFiring.rule_id, func.count())
                .where(
                    TelemetryRuleFiring.rule_id.in_(ids),
                    TelemetryRuleFiring.status == "firing",
                    TelemetryRuleFiring.cleared_at.is_(None),
                )
                .group_by(TelemetryRuleFiring.rule_id)
            )
        ).all():
            open_counts[str(rid)] = int(n)
        sub = (
            select(
                TelemetryRuleFiring.rule_id,
                func.max(TelemetryRuleFiring.fired_at).label("m"),
            )
            .where(
                TelemetryRuleFiring.rule_id.in_(ids),
                TelemetryRuleFiring.status != "test",
            )
            .group_by(TelemetryRuleFiring.rule_id)
            .subquery()
        )
        for f in (
            (
                await db.execute(
                    select(TelemetryRuleFiring).join(
                        sub,
                        and_(
                            TelemetryRuleFiring.rule_id == sub.c.rule_id,
                            TelemetryRuleFiring.fired_at == sub.c.m,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        ):
            lasts[str(f.rule_id)] = _firing_json(f)
    _, names = await _facts(db, user.tenant_id)
    labels = await _labels(db, rules)
    can_command = await access.has(db, user, "telemetry.command")
    return success(
        [
            _rule_json(
                r,
                names,
                labels,
                can_edit,
                open_counts.get(str(r.id), 0),
                lasts.get(str(r.id)),
            )
            for r in rules
        ],
        meta={
            "total": len(rules),
            "can_edit": can_edit,
            "can_command": can_command,
            "max_rules": MAX_RULES,
        },
    )


@router.get("/firings")
async def list_firings(
    rule_id: str = "",
    status: str = "",
    limit: int = Query(50, ge=1, le=500),
    before: str | None = None,
    since: str | None = Query(
        None, description="Only firings after this ISO time, oldest first"
    ),
    include: str = Query("", description="outputs adds each step's input and output"),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    everything, teams, _ = await _visible(db, user)
    q = select(TelemetryRuleFiring).where(
        TelemetryRuleFiring.tenant_id == user.tenant_id
    )
    if rule_id:
        try:
            q = q.where(TelemetryRuleFiring.rule_id == uuid.UUID(rule_id))
        except ValueError:
            return error(
                "rule_id is not a valid id", 422, error_code="VALIDATION_ERROR"
            )
    if status in ("firing", "cleared", "test"):
        q = q.where(TelemetryRuleFiring.status == status)
    if before:
        try:
            q = q.where(
                TelemetryRuleFiring.fired_at
                < datetime.fromisoformat(before.replace("Z", "+00:00"))
            )
        except ValueError:
            return error(
                "before must be an ISO time", 422, error_code="VALIDATION_ERROR"
            )
    if since:
        try:
            q = q.where(
                TelemetryRuleFiring.fired_at
                > datetime.fromisoformat(since.replace("Z", "+00:00"))
            )
        except ValueError:
            return error(
                "since must be an ISO time", 422, error_code="VALIDATION_ERROR"
            )
    order = (
        TelemetryRuleFiring.fired_at.asc()
        if since
        else TelemetryRuleFiring.fired_at.desc()
    )
    rows = (await db.execute(q.order_by(order).limit(limit))).scalars().all()
    if not everything:
        hidden = {
            str(r.id)
            for r in (
                await db.execute(
                    select(TelemetryRule).where(
                        TelemetryRule.tenant_id == user.tenant_id
                    )
                )
            )
            .scalars()
            .all()
            if not _sees(r, everything, teams)
        }
        scope = await access.scope_for(db, user)
        rows = [
            f
            for f in rows
            if str(f.rule_id) not in hidden
            and (not f.connection_id or scope.sees(f.connection_id))
        ]
    outputs = "outputs" in {x.strip() for x in include.split(",")}
    return success(
        [_firing_json(f, outputs) for f in rows],
        meta={
            "limit": limit,
            "next_since": _iso(rows[-1].fired_at) if since and rows else None,
        },
    )


@router.get("/firings/{firing_id}")
async def get_firing(
    firing_id: str,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """One firing with each step's input, output, duration and status."""
    try:
        fid = uuid.UUID(firing_id)
    except ValueError:
        return error("No firing with that id.", 404, error_code="NOT_FOUND")
    f = (
        await db.execute(
            select(TelemetryRuleFiring).where(
                TelemetryRuleFiring.id == fid,
                TelemetryRuleFiring.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one_or_none()
    if f is None:
        return error("No firing with that id.", 404, error_code="NOT_FOUND")
    everything, teams, _ = await _visible(db, user)
    if not everything:
        rule = await db.get(TelemetryRule, f.rule_id) if f.rule_id else None
        scope = await access.scope_for(db, user)
        if (rule is not None and not _sees(rule, everything, teams)) or (
            f.connection_id and not scope.sees(f.connection_id)
        ):
            return error("No firing with that id.", 404, error_code="NOT_FOUND")
    doc = _firing_json(f, True)
    doc["context"] = f.context or {}
    return success(doc)


@router.get("/health")
async def rules_health(
    user: User = Depends(require_capability("telemetry.view")),
) -> JSONResponse:
    r = _redis()
    raw = await r.hgetall(HEALTH_KEY)
    reps = {}
    for k, v in (raw or {}).items():
        try:
            reps[k] = json.loads(v)
        except ValueError:
            continue
    lat = {}
    try:
        for k, v in (await r.hgetall(K.latency(user.tenant_id)) or {}).items():
            lat[k] = json.loads(v)
    except Exception:  # noqa: BLE001
        pass
    return success(
        {
            "evaluators": reps,
            "ingest_latency": lat,
            "mode": await _mode_doc(user),
        }
    )


MODE_HELP = (
    "Rules run inside the telemetry ingest by default, which suits a few rules on modest "
    "streams. Move them to the rules pool when you have many rules or busy streams: the "
    "ingest then only hands matching readings over, so rules never slow it down, at the "
    "cost of a few milliseconds more before a rule decides."
)


async def _mode_doc(user: User) -> dict[str, Any]:
    from app.core.deps import async_session
    from app.core.platform_settings import get_setting
    from app.telemetry.rules.evaluator import MODE_OVERRIDE, MODE_SETTING, pool_alive
    from models.tenant import Tenant

    default = (
        (await get_setting(MODE_SETTING, "inprocess") or "inprocess").strip().lower()
    )
    async with async_session() as db:
        st = await db.scalar(select(Tenant.settings).where(Tenant.id == user.tenant_id))
    override = (st or {}).get(MODE_OVERRIDE)
    replicas = await pool_alive(_redis())
    chosen = override or default
    return {
        "default": default,
        "override": override,
        "chosen": chosen,
        "effective": "pool" if chosen == "pool" and replicas else "inprocess",
        "pool_replicas": replicas,
        "help": MODE_HELP,
    }


@router.get("/mode")
async def get_mode(
    user: User = Depends(require_capability("telemetry.view")),
) -> JSONResponse:
    return success(await _mode_doc(user))


@router.put("/mode")
async def set_mode(
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Where this workspace's rules run. null goes back to the platform default."""
    from app.core.permissions import is_admin
    from app.telemetry.rules.evaluator import MODE_OVERRIDE, MODES, pool_alive
    from models.tenant import Tenant

    if not is_admin(user):
        return error(
            "Only an admin can choose where rules run.", 403, error_code="FORBIDDEN"
        )
    mode = body.get("mode")
    if mode is not None and mode not in MODES:
        return error(
            "Choose inprocess or pool.",
            422,
            error_code="VALIDATION_ERROR",
            details={"fields": {"mode": "Choose inside the ingest or the rules pool."}},
        )
    if mode == "pool" and not await pool_alive(_redis()):
        return error(
            "The rules pool is not running in this cluster, so rules stay inside the ingest. "
            "An operator turns it on with telemetryRules.enabled in the Helm values.",
            409,
            error_code="POOL_NOT_RUNNING",
        )
    t = (
        await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    ).scalar_one()
    st = dict(t.settings or {})
    old = st.get(MODE_OVERRIDE)
    if mode is None:
        st.pop(MODE_OVERRIDE, None)
    else:
        st[MODE_OVERRIDE] = mode
    t.settings = st
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.rules.mode",
        {"mode": mode},
        request,
        resource_type="tenant",
        resource_id=str(user.tenant_id),
        old_value={"mode": old},
        new_value={"mode": mode},
    )
    await db.commit()
    await _bump()
    return success(await _mode_doc(user))


@router.get("/options")
async def rule_options(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """What the builder's steps can pick from: agents and pipelines, decision tables, people and teams."""
    from models.agent import Agent, AgentStatus, AgentType
    from models.decision import DecisionModel
    from models.governance import PermissionSet
    from models.user import User as U

    agents = (
        await db.execute(
            select(Agent.id, Agent.name, Agent.model_config_, Agent.status)
            .where(
                or_(
                    Agent.tenant_id == user.tenant_id, Agent.agent_type == AgentType.OOB
                ),
                Agent.status != AgentStatus.ARCHIVED,
            )
            .order_by(Agent.name)
            .limit(1000)
        )
    ).all()
    decisions = (
        await db.execute(
            select(DecisionModel.key, DecisionModel.name)
            .where(
                DecisionModel.tenant_id == user.tenant_id,
                DecisionModel.archived_at.is_(None),
            )
            .order_by(DecisionModel.name)
        )
    ).all()
    people = (
        await db.execute(
            select(U.id, U.full_name, U.email)
            .where(U.tenant_id == user.tenant_id, U.is_active.is_(True))
            .order_by(U.email)
            .limit(1000)
        )
    ).all()
    teams = (
        await db.execute(
            select(PermissionSet.id, PermissionSet.name)
            .where(PermissionSet.tenant_id == user.tenant_id)
            .order_by(PermissionSet.name)
        )
    ).all()
    return success(
        {
            "agents": [
                {
                    "id": str(i),
                    "name": n,
                    "kind": (
                        "pipeline" if (cfg or {}).get("mode") == "pipeline" else "agent"
                    ),
                    "status": getattr(st, "value", st),
                }
                for i, n, cfg, st in agents
            ],
            "decisions": [{"key": k, "name": n} for k, n in decisions],
            "people": [
                {"id": str(i), "name": n or e, "email": e} for i, n, e in people
            ],
            "teams": [{"id": str(i), "name": n} for i, n in teams],
            "can_command": await access.has(db, user, "telemetry.command"),
        }
    )


@router.get("/signals")
async def rule_signals(
    group: str = "",
    node: str = "",
    device: str | None = None,
    kind: str = "",
    type: str = "",
    tag: str = "",
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Signals that are streaming now, with their latest value, for the scope being built."""
    r = _redis()
    scope = await access.scope_for(db, user)
    t = user.tenant_id
    nodes: list[tuple[str, str, str | None]] = []
    if group and node:
        nodes = [(group, node, None if device in (None, "*") else device)]
    elif kind in ("type", "tag"):
        facts, _ = await _facts(db, t)
        keys = facts.keys_where(kind, type if kind == "type" else tag.lower(), group)
        seen = set()
        for g, n, d in keys:
            if (g, n, d) not in seen:
                seen.add((g, n, d))
                nodes.append((g, n, d or None))
        nodes = nodes[:30]
    out: dict[str, dict[str, Any]] = {}
    for g, n, d in nodes:
        doc = await reads.node_detail(r, t, g, n, None)
        if doc is None or not scope.sees(doc.get("connection_id")):
            continue
        parts = [("", doc.get("metrics") or [], doc.get("online"))] + [
            (x["device"], x.get("metrics") or [], x.get("online"))
            for x in doc.get("devices") or []
        ]
        for dev, metrics, online in parts:
            if d is not None and dev != d:
                continue
            for m in metrics:
                s = out.setdefault(
                    m["name"],
                    {
                        "signal": m["name"],
                        "type": m.get("type"),
                        "unit": m.get("unit"),
                        "assets": [],
                        "value": m.get("value"),
                        "ts": m.get("ts"),
                    },
                )
                if len(s["assets"]) < 20:
                    s["assets"].append(
                        {
                            "group": g,
                            "node": n,
                            "device": dev,
                            "value": m.get("value"),
                            "ts": m.get("ts"),
                            "online": online,
                        }
                    )
    if not nodes:
        for c in scope.connections:
            if not scope.sees(str(c.id)):
                continue
            for name, raw in (await r.hgetall(K.signals(t, c.id)) or {}).items():
                try:
                    meta = json.loads(raw)
                except ValueError:
                    meta = {}
                s = out.setdefault(
                    name,
                    {
                        "signal": name,
                        "type": meta.get("type"),
                        "unit": meta.get("unit"),
                        "assets": [],
                        "value": None,
                        "ts": meta.get("last_seen"),
                    },
                )
                ex = meta.get("example")
                if ex and len(s["assets"]) < 20:
                    g2, n2, d2 = (ex.split("/", 2) + ["", ""])[:3]
                    s["assets"].append({"group": g2, "node": n2, "device": d2})
    rows = sorted(out.values(), key=lambda s: s["signal"].lower())
    for s in rows:
        s["numeric"] = s.get("type") in ("number", "bool") or isinstance(
            s.get("value"), (int, float, bool)
        )
    return success(rows[:2000], meta={"total": len(rows)})


@router.get("/{rule_id}")
async def get_rule(
    rule_id: str,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    r = await _load(db, user, rule_id)
    if r is None:
        return error(
            "No rule with that id. It may have been deleted.",
            404,
            error_code="NOT_FOUND",
        )
    everything, teams, can_edit = await _visible(db, user)
    if not _sees(r, everything, teams):
        return error(
            "No rule with that id. It may have been deleted.",
            404,
            error_code="NOT_FOUND",
        )
    _, names = await _facts(db, user.tenant_id)
    labels = await _labels(db, [r])
    return success(_rule_json(r, names, labels, can_edit))


async def _load(db: AsyncSession, user: User, rule_id: str) -> TelemetryRule | None:
    try:
        rid = uuid.UUID(rule_id)
    except ValueError:
        return None
    return (
        await db.execute(
            select(TelemetryRule).where(
                TelemetryRule.id == rid, TelemetryRule.tenant_id == user.tenant_id
            )
        )
    ).scalar_one_or_none()


# writing


@router.post("")
async def create_rule(
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _refusal()
    try:
        clean = M.clean(body)
    except M.RuleInvalid as e:
        return _invalid(e.fields)
    err = await _check_actions(db, user, clean["actions"])
    team_id = await _team(db, user, body.get("team_id"), err)
    taken = await db.scalar(
        select(TelemetryRule.id).where(
            TelemetryRule.tenant_id == user.tenant_id,
            func.lower(TelemetryRule.name) == clean["name"].lower(),
        )
    )
    if taken:
        err["name"] = "Another rule already has this name."
    count = await db.scalar(
        select(func.count())
        .select_from(TelemetryRule)
        .where(TelemetryRule.tenant_id == user.tenant_id)
    )
    if int(count or 0) >= MAX_RULES:
        err["name"] = (
            f"This workspace has {MAX_RULES} rules, the most it can have. Delete some first."
        )
    if err:
        return _invalid(err)
    r = TelemetryRule(
        tenant_id=user.tenant_id,
        created_by=user.id,
        updated_by=user.id,
        team_id=team_id,
        **clean,
    )
    db.add(r)
    await db.flush()
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.rule.create",
        {"name": r.name},
        request,
        resource_type="telemetry_rule",
        resource_id=str(r.id),
        new_value=clean,
    )
    await db.commit()
    await db.refresh(r)
    await _bump()
    _, names = await _facts(db, user.tenant_id)
    return success(_rule_json(r, names, await _labels(db, [r]), True))


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _refusal()
    r = await _load(db, user, rule_id)
    if r is None:
        return error(
            "No rule with that id. It may have been deleted.",
            404,
            error_code="NOT_FOUND",
        )
    old = {
        "name": r.name,
        "description": r.description,
        "severity": r.severity,
        "enabled": r.enabled,
        "cooldown_s": r.cooldown_s,
        "scope": r.scope,
        "condition": r.condition,
        "actions": r.actions,
    }
    merged = {**old, **{k: v for k, v in body.items() if k in old}}
    try:
        clean = M.clean(merged)
    except M.RuleInvalid as e:
        return _invalid(e.fields)
    err: dict[str, str] = {}
    if clean["actions"] != (r.actions or []):
        err.update(await _check_actions(db, user, clean["actions"]))
    team_id = (
        await _team(db, user, body.get("team_id"), err)
        if "team_id" in body
        else r.team_id
    )
    if clean["name"].lower() != r.name.lower():
        taken = await db.scalar(
            select(TelemetryRule.id).where(
                TelemetryRule.tenant_id == user.tenant_id,
                func.lower(TelemetryRule.name) == clean["name"].lower(),
                TelemetryRule.id != r.id,
            )
        )
        if taken:
            err["name"] = "Another rule already has this name."
    if err:
        return _invalid(err)
    for k, v in clean.items():
        setattr(r, k, v)
    r.team_id = team_id
    r.updated_by = user.id
    # a changed or stopped rule starts again from what it sees next
    restart = clean["condition"] != old["condition"] or clean["scope"] != old["scope"]
    if restart or (old["enabled"] and not clean["enabled"]):
        from app.telemetry.rules.actions import close_rule

        await close_rule(db, _redis(), user.tenant_id, r.id)
        try:
            await _redis().delete(f"tel:{user.tenant_id}:rs:{r.id}")
        except Exception:  # noqa: BLE001
            pass
    action = "telemetry.rule.update"
    if set(body) == {"enabled"}:
        action = (
            "telemetry.rule.enable" if clean["enabled"] else "telemetry.rule.disable"
        )
    await log_action(
        db,
        user.tenant_id,
        user.id,
        action,
        {"name": r.name},
        request,
        resource_type="telemetry_rule",
        resource_id=str(r.id),
        old_value=old,
        new_value=clean,
    )
    await db.commit()
    await db.refresh(r)
    await _bump()
    _, names = await _facts(db, user.tenant_id)
    return success(_rule_json(r, names, await _labels(db, [r]), True))


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: str,
    request: Request,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if not await access.has(db, user, "telemetry.manage"):
        return _refusal()
    r = await _load(db, user, rule_id)
    if r is None:
        return error(
            "No rule with that id. It may have been deleted.",
            404,
            error_code="NOT_FOUND",
        )
    name = r.name
    from app.telemetry.rules.actions import close_rule

    await close_rule(db, _redis(), user.tenant_id, r.id)
    await db.execute(
        delete(TelemetryRuleFiring).where(TelemetryRuleFiring.rule_id == r.id)
    )
    await db.delete(r)
    await log_action(
        db,
        user.tenant_id,
        user.id,
        "telemetry.rule.delete",
        {"name": name},
        request,
        resource_type="telemetry_rule",
        resource_id=rule_id,
    )
    await db.commit()
    try:
        await _redis().delete(f"tel:{user.tenant_id}:rs:{rule_id}")
    except Exception:  # noqa: BLE001
        pass
    await _bump()
    return success({"deleted": True, "name": name})


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: str,
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Run the rule's steps once now as a test, with the asset's latest value. Commands are never sent."""
    if not await access.has(db, user, "telemetry.manage"):
        return _refusal()
    r = await _load(db, user, rule_id)
    if r is None:
        return error(
            "No rule with that id. It may have been deleted.",
            404,
            error_code="NOT_FOUND",
        )
    if not r.actions:
        return error(
            "This rule has no steps to test. Add one, like raise an alert.",
            422,
            error_code="VALIDATION_ERROR",
        )
    facts, names = await _facts(db, user.tenant_id)
    s = r.scope or {}
    if s.get("kind") == "asset":
        g, n, d = (
            s.get("group"),
            s.get("node"),
            "" if s.get("device") in (None, "*") else s.get("device"),
        )
    else:
        keys = facts.keys_where(
            s.get("kind"), s.get("type") or s.get("tag"), s.get("group") or ""
        )
        if not keys:
            return error(
                "No asset matches this rule yet, so there is nothing to test with.",
                422,
                error_code="VALIDATION_ERROR",
            )
        g, n, d = keys[0]
    sig = (r.condition or {}).get("signal") or (r.condition or {}).get("x_signal")
    value = None
    if sig:
        doc = await reads.node_detail(_redis(), user.tenant_id, g, n, None)
        for dev in [
            {"device": "", "metrics": (doc or {}).get("metrics") or []},
            *((doc or {}).get("devices") or []),
        ]:
            for m in dev.get("metrics") or []:
                if m["name"] == sig and (not d or dev["device"] == d):
                    value, d = m.get("value"), dev["device"]
    from app.telemetry.rules import runner

    asset = AssetFacts.name(facts, g, n, d)
    fid = await runner.test_fire(
        r,
        {
            "type": "fired",
            "tenant": str(user.tenant_id),
            "rule_id": str(r.id),
            "rule": r.name,
            "severity": r.severity,
            "group": g,
            "node": n,
            "device": d or "",
            "asset": asset,
            "signal": sig,
            "value": value,
            "detail": f"Test of {r.name} on {asset}"
            + (f", {sig} is {value}" if sig and value is not None else "")
            + ".",
            "ts": int(time.time() * 1000),
            "at": int(time.time() * 1000),
            "connection_id": None,
        },
    )
    return success({"firing_id": fid, "queued": True})


@router.post("/preview")
async def preview_rule(
    body: dict[str, Any] = Body(...),
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Replay a rule, saved or not, over the last hours of history."""
    hours = body.get("hours") or 1
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        hours = 1.0
    if hours not in PREVIEW_HOURS:
        return error(
            "Preview the last 1, 6 or 24 hours.", 422, error_code="VALIDATION_ERROR"
        )
    err: dict[str, str] = {}
    scope = M.clean_scope(body.get("scope"), err)
    cond = M.clean_condition(body.get("condition"), err)
    cd = body.get("cooldown_s")
    try:
        cooldown = max(0, min(86400, int(float(cd if cd not in (None, "") else 60))))
    except (TypeError, ValueError):
        cooldown = 60
    if err:
        return _invalid(err)
    rule = {"scope": scope, "condition": cond, "cooldown_s": cooldown}
    facts, names = await _facts(db, user.tenant_id)
    compiled = compile_rule(
        {
            "id": "preview",
            "tenant_id": str(user.tenant_id),
            "scope": scope,
            "condition": cond,
            "cooldown_s": cooldown,
        }
    )
    if scope["kind"] == "asset":
        dev = scope.get("device", "*")
        targets: list[tuple[str, str, str | None]] = [
            (scope["group"], scope["node"], None if dev == "*" else dev)
        ]
    else:
        targets = []
        for g, n, d in facts.keys_where(
            scope["kind"],
            scope.get("type") or scope.get("tag"),
            scope.get("group") or "",
        ):
            t3 = (g, n, d or None)
            if t3 not in targets:
                targets.append(t3)
    sc = await access.scope_for(db, user)
    if not sc.everything:
        r = _redis()
        keep_t = []
        for g, n, d in targets:
            if sc.sees(await r.hget(K.device(user.tenant_id, g, n, ""), "_conn")):
                keep_t.append((g, n, d))
        targets = keep_t
    to = P.now()
    frm = to - timedelta(hours=hours)
    from app.routers.telemetry import tsdb

    try:
        pool = await tsdb()
        if cond["kind"] == "stale":
            if scope["kind"] == "asset" and scope.get("device", "*") == "*":
                tt = [(g, n, None) for g, n, _ in targets]
            else:
                tt = targets
            times = await P.fetch_times(
                pool, str(user.tenant_id), tt, cond.get("signal") or None, frm, to
            )
            assets = P.replay_stale(rule, times, to, names)
            cut = False
        else:
            sigs = compiled.cond.signals()
            # a baseline condition warms up on the history before the window shown
            lead = (
                timedelta(seconds=float(cond.get("baseline_s") or 0))
                if cond["kind"] == "deviation"
                else timedelta(0)
            )
            rows, cut = await P.fetch(
                pool, str(user.tenant_id), targets, sigs, frm - lead, to
            )
            assets = P.replay(
                rule,
                rows,
                keep=lambda g, n, d: compiled.matches(g, n, d, facts),
                names=names,
                since_ms=int(frm.timestamp() * 1000),
            )
    except Exception as exc:  # noqa: BLE001
        return error(
            f"History is not available right now, so the preview cannot run: {exc}",
            503,
            error_code="HISTORY_UNAVAILABLE",
        )
    total = sum(len(a["firings"]) for a in assets)
    return success(
        {
            "from": frm.isoformat(),
            "to": to.isoformat(),
            "hours": hours,
            "fired": total,
            "cleared": sum(len(a["clears"]) for a in assets),
            "summary": P.summary(rule, assets, hours),
            "condition_words": M.describe_condition(cond),
            "scope_words": M.describe_scope(scope, names),
            "assets": assets[:20],
            "truncated": cut or len(assets) > 20,
            "targets": len(targets),
        }
    )


# for the Triggers page


@router.get("/as-triggers/list")
async def rules_as_triggers(
    user: User = Depends(require_capability("telemetry.view")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    everything, teams, _ = await _visible(db, user)
    rules = (
        (
            await db.execute(
                select(TelemetryRule)
                .where(TelemetryRule.tenant_id == user.tenant_id)
                .order_by(TelemetryRule.name)
            )
        )
        .scalars()
        .all()
    )
    rules = [r for r in rules if _sees(r, everything, teams)]
    _, names = await _facts(db, user.tenant_id)
    labels = await _labels(db, rules)
    return success(
        [
            {
                "id": str(r.id),
                "name": r.name,
                "enabled": r.enabled,
                "summary": M.describe(
                    {"condition": r.condition, "scope": r.scope, "actions": r.actions},
                    names,
                    labels,
                ),
                "runs": [
                    labels.get(a.get("agent_id") or "", "an agent")
                    for a in r.actions or []
                    if a.get("kind") == "run"
                ],
                "fire_count": r.fire_count or 0,
                "last_fired_at": _iso(r.last_fired_at),
                "link": f"/telemetry/rules?rule={r.id}",
            }
            for r in rules
        ]
    )


__all__ = ["router"]
